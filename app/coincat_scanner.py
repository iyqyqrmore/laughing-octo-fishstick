"""Read-only account/market scanner for the full-balance decision policy."""
import time
from copy import deepcopy
from collections import Counter
from decimal import Decimal
from coincat_live import LiveBroker
from coincat_full_balance import rank_full_balances
from coincat_v80_discovery import select_books, book_status
from coincat_v701_quotes import valid_book
from coincat_v703_chain import approved_pairs
from coincat_v701_transport import SCOUT, fetch_snapshot
from coincat_passive_lab import PassiveLab
from coincat_eth_farmer import eth_quote_plan
from coincat_research_admission import service_period
from coincat_working_allocation import assess_allocation
from coincat_eth_cycles import eth_cycle_inventory


class Scanner:
    def __init__(self, ledger, client, fees, market_store):
        self.ledger=ledger
        self.client=client
        self.broker=LiveBroker(ledger,client)  # Submission remains unconditionally blocked.
        self.fees=fees
        self.market_store=market_store
        self.catalog=[];self.rules={};self.balances={};self.books={}
        self.account_at=None;self.catalog_at=None;self.cursor=0
        self.lab=PassiveLab();self.last_result=None;self.sequence=0
        self.observed_books={};self.priced_at={}
        self.eth_cursor=0

    def refresh(self, *, now=None):
        fixed_now=now
        now=time.time() if now is None else now
        self.broker.permissions()
        balances=self.broker.balances()
        if self.catalog_at is None or not 0<=now-self.catalog_at<=7200:
            catalog=self.broker.catalog()
            self.catalog=list(catalog);self.rules=dict(self.broker.catalog_product_rules)
            self.catalog_at=now
        self.fees.refresh_from_client(self.client,now=now)
        # No enrollment, tax-basis, settings, lot or private-ledger mutations.
        self.balances=balances;self.account_at=time.time() if fixed_now is None else now
        return {'balances':dict(balances),'catalog_count':len(self.catalog),'at':self.account_at}

    def scan(self, *, now=None, collect=None, cancel=None, scan_interval_s=5,
             allocation_draft=(),allocation_authorization=None,allocation_reconciliation=None):
        service_period(scan_interval_s)  # Validate cadence before any read request.
        fixed_now=now
        now=time.time() if now is None else now
        if self.account_at is None or not 0<=now-self.account_at<60:self.refresh(now=fixed_now)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        excluded={row['asset'] for row in self.ledger.assets() if not row.get('enabled',1)}
        funding={asset for asset,qty in self.balances.items() if qty>0 and asset not in excluded}
        listed=approved_pairs(self.catalog,self.rules,excluded)
        due=self.lab.quote_groups(now=now,listed=listed)
        allocation_args=dict(balances=self.balances,balances_at=self.account_at,excluded=excluded,
            draft=allocation_draft,authorization=allocation_authorization,reconciliation=allocation_reconciliation)
        working=assess_allocation(now=now,**allocation_args)
        eth_plan=eth_quote_plan(balances=working['eligible_working_balances'] or self.balances,catalog=self.catalog,
            rules=self.rules,excluded=excluded,cursor=self.eth_cursor)
        if working['eligible_working_balances']:
            eth_plan['scope']='AUTHORIZED_RECONCILED_WORKING_ONLY'
        plan=select_books(self.catalog,self.rules,funding,quotes=self.books,now=now,
            cursor=self.cursor,excluded=excluded,priority_groups=due,valuation_groups=eth_plan['groups'],
            service_period_s=service_period(scan_interval_s))
        snapshots,errors,elapsed=(SCOUT.collect if collect is None else collect)(plan['books'],fetch=fetch_snapshot)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        now=time.time() if fixed_now is None else now
        self.cursor=plan['next_route_cursor']
        incoming={pair:item.book() for pair,item in snapshots.items()}
        self.lab.record_service(plan,incoming,errors,now=now)
        if plan['_eth_group'] is not None:
            self.eth_cursor+=1
        self.observed_books.update(incoming)
        catalog_set=set(self.catalog)
        # Remember the last public observation for diagnosis, never for stale
        # pricing. Both caches remain bounded by the current catalog.
        self.observed_books={p:b for p,b in self.observed_books.items() if p in catalog_set}
        self.books={p:b for p,raw in self.observed_books.items()
                    if (b:=valid_book(raw,now,30)) is not None}
        recorded=self.market_store.record_quotes([(p,b[2],b[0],b[1],'COINBASE_PUBLIC_REST_BEST_BID_ASK') for p,b in incoming.items()])
        tier=self.fees.latest_tier(now=now)
        self.sequence+=1
        result=rank_full_balances(balances=self.balances,catalog=self.catalog,rules=self.rules,
            quotes=self.books,fee_rate=tier.get('taker') if tier.get('fresh') else None,
            now=now,balances_at=self.account_at,excluded=excluded)
        result.update(quotes_recorded=recorded,scan=self.sequence,quote_errors=dict(errors),fetch_ms=elapsed,
            fee_rate=tier.get('taker') if tier.get('fresh') else None,
            portfolio_limits='NONE_FULL_AVAILABLE',orders_submitted=0,
            execution='BLOCKED_PENDING_DURABLE_ORDER_FILL_RECOVERY')
        eligible={(p,s) for p,s,source,target in plan['eligible_directions']}
        self.priced_at={d:t for d,t in self.priced_at.items() if d in eligible and t<=now}
        for row in result['ranked']:
            self.priced_at[(row['pair'],row['side'])]=now
        result['coverage_complete']=bool(eligible) and result['priced_directions']==len(eligible)
        result['observation_engine']='RESEARCH_ADMISSION_FAIR_DEADLINES_ETH_GROUPS'
        result['result_scope']='CURRENTLY_PRICED_DIRECTIONS_ONLY'
        result['book_conditions']=dict(Counter(book_status(self.observed_books.get(p),now)
            for p,s in eligible))
        result['coverage_history']={'session_priced_directions':len(self.priced_at),
            'last_5min_priced_directions':sum(0<=now-t<=300 for t in self.priced_at.values()),
            'scope':'CURRENT_ELIGIBLE_UNIVERSE; HISTORICAL_COUNTS_ARE_NOT_FRESH_QUOTES'}
        result['quote_scheduling']={'request_limit':16,'requested_books':len(plan['books']),
            'selected_directions':plan['selected_directions'],
            **{k:plan[k] for k in ('cached_reused_books','request_budget_deferred',
                'missing_independent_paths','endpoint_requests','endpoint_groups_scheduled',
                'endpoint_groups_deferred','endpoint_groups_unavailable')}}
        result['eth_quote_scheduling']={'scope':eth_plan['scope'],
            'account_required_books':eth_plan['account_required_books'],
            'known_dependency_books':eth_plan['known_dependency_books'],
            'structurally_unpriced_assets':eth_plan['missing_asset_count'],
            'all_paths_supported':eth_plan['all_paths_supported'],
            'selected_group_kind':None if plan['_eth_group'] is None else plan['_eth_group']['kind'],
            'requested_books':plan['eth_valuation_requests'],
            'groups_deferred':plan['eth_groups_deferred'],
            'account_total_requires_complete_synchronized_quotes':True}
        result['eth_quote_scheduling']['structural_blockers']=eth_plan['structural_blockers']
        group=plan['_eth_group']
        if group is not None:
            conditions=Counter(book_status(self.observed_books.get(p),now) for p in group['books'])
            coherent=set(conditions)=={'FRESH'}
            span=None
            if coherent:
                stamps=[self.observed_books[p][2] for p in group['books']]
                span=max(stamps)-min(stamps)
                coherent=span<=12
            result['eth_quote_scheduling'].update(selected_group_book_conditions=dict(conditions),
                selected_group_quote_span_s=span,selected_group_synchronized=coherent)
        # Freeze read-only inputs so later GUI settings/STOP cannot combine
        # account quantities from one scan with books from a different scan.
        result['eth_observation'] = dict(balances=dict(self.balances),
            catalog=tuple(self.catalog), rules=deepcopy(self.rules),
            quotes=dict(self.books), observed_quotes=dict(self.observed_books), now=now, balances_at=self.account_at,
            fee_rate=result['fee_rate'], excluded=tuple(sorted(excluded)))
        result['working_allocation']=assess_allocation(now=now,**allocation_args)
        result['eth_cycle_feasibility']=eth_cycle_inventory(catalog=self.catalog,rules=self.rules,excluded=excluded)
        result['lab_note']=self.lab.observe(result,self.observed_books,now=now,
            scan_interval_s=scan_interval_s,listed=listed)
        result['research_scheduler']=self.lab.diagnostics()
        self.last_result=result
        return result
