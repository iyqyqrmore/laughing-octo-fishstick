"""Read-only v95 direct-ETH observer with staged, attributed observations."""
import time
from copy import deepcopy
from coincat_live import LiveBroker
from coincat_v701_transport import SCOUT,fetch_snapshot,BUDGET
from coincat_working_allocation import assess_allocation
from coincat_eth_maker import MakerStudy,select_markets,model_market
from coincat_continuity import eth_funding,research_identity,quote_reason
from coincat_recovery import read_call,ReadFailure,public_quote_failure


class Scanner:
    def __init__(self,ledger,client,fees,market_store):
        self.ledger=ledger;self.client=client;self.fees=fees;self.market_store=market_store
        self.broker=LiveBroker(ledger,client)
        self.catalog=[];self.rules={};self.balances={}
        self.account_at=None;self.catalog_at=None;self.sequence=0;self.last_result=None
        self.last_successful_account_refresh_at=None;self.last_successful_scan_at=None
        self.maker_study=MakerStudy();self.require_refresh=False

    def pause_observation(self,reason,*,now=None):
        """GUI invokes after its worker finishes; never race an in-flight copy."""
        self.require_refresh=True
        self.maker_study.pause_all(reason,time.time() if now is None else now)

    def refresh(self,*,now=None,cancel=None,force_catalog=False):
        fixed_now=now;now=time.time() if now is None else now
        stopped=lambda:cancel is not None and cancel.is_set()
        if stopped():return {'state':'CANCELLED'}
        read_call('PERMISSIONS',self.broker.permissions)
        if stopped():return {'state':'CANCELLED'}
        balances=read_call('BALANCES',self.broker.balances)
        if stopped():return {'state':'CANCELLED'}
        catalog=self.catalog;rules=self.rules;catalog_at=self.catalog_at
        if force_catalog or catalog_at is None or not 0<=now-catalog_at<=7200:
            catalog=list(read_call('CATALOG',self.broker.catalog))
            rules=deepcopy(self.broker.catalog_product_rules);catalog_at=now
        if stopped():return {'state':'CANCELLED'}
        read_call('FEE_TIER',self.fees.refresh_from_client,self.client,now=now,cancel=cancel,raise_errors=True)
        if stopped():return {'state':'CANCELLED'}
        self.catalog=list(catalog);self.rules=dict(rules);self.catalog_at=catalog_at
        self.balances=balances;self.account_at=time.time() if fixed_now is None else now
        self.last_successful_account_refresh_at=self.account_at;self.require_refresh=False
        return {'balances':dict(balances),'catalog_count':len(catalog),'at':self.account_at}

    def scan_growth(self,config,*,now=None,collect=None,cancel=None,allocation_draft=(),
                    applied_eth_key=None,force_refresh=False):
        config.validate()
        stopped=lambda:cancel is not None and cancel.is_set()
        if stopped():return {'state':'CANCELLED'}
        fixed_now=now;now=time.time() if now is None else now
        if force_refresh or self.require_refresh or self.account_at is None or not 0<=now-self.account_at<60:
            refreshed=self.refresh(now=fixed_now,cancel=cancel,force_catalog=force_refresh or self.require_refresh)
            if refreshed.get('state')=='CANCELLED':return refreshed
        if stopped():return {'state':'CANCELLED'}
        excluded=tuple(sorted(row['asset'] for row in self.ledger.assets() if not row.get('enabled',1)))
        selection=select_markets(tuple(self.catalog),self.rules,config.companions,excluded)
        rules={m['pair']:deepcopy(self.rules[m['pair']]) for m in selection['selected']}
        allocation=assess_allocation(balances=dict(self.balances),balances_at=self.account_at,
            now=now,excluded=excluded,draft=tuple(allocation_draft))
        funding_args=dict(balances=dict(self.balances),balances_at=self.account_at,
                          excluded=excluded,draft=tuple(allocation_draft))
        funding=eth_funding(now=now,**funding_args)
        selected_pairs={m['pair'] for m in selection['selected']}
        removed={p:('SELECTED_MARKET_EXCLUDED' if 'ETH' in excluded or self.maker_study.active[p].get('_asset') in excluded
                    else 'SELECTED_MARKET_REMOVED_OR_INELIGIBLE')
                 for p in self.maker_study.active if p not in selected_pairs}
        if applied_eth_key is not None and funding['key']!=applied_eth_key:
            study=deepcopy(self.maker_study)
            for pair in tuple(study.active):study.invalidate(pair,'ETH_FUNDING_CHANGED_REAPPLY_REQUIRED',now)
            if stopped():return {'state':'CANCELLED'}
            self.maker_study=study
            return dict(state='PAUSED_NEEDS_ATTENTION',reason='ETH_FUNDING_CHANGED_REAPPLY_REQUIRED',
                        study_counts=study.statistics(),study_continuity=study.diagnostics())
        books=tuple(m['pair'] for m in selection['selected'])
        snapshots,errors,elapsed=read_call('PUBLIC_QUOTE',SCOUT.collect if collect is None else collect,
                                         books,fetch=fetch_snapshot)
        if stopped():return {'state':'CANCELLED'}
        now=time.time() if fixed_now is None else now
        incoming={p:item.book() for p,item in snapshots.items() if p in books}
        by_product=getattr(errors,'by_product',{})
        if errors:
            attributed=[public_quote_failure(code,minimum_delay=max(0,BUDGET.blocked_until-time.monotonic()))
                        for code in (list(by_product.values()) or list(errors))]
            denied=next((f for f in attributed if f['status'] in (401,403)),None)
            if denied is not None:raise ReadFailure(denied)
        # No returned observation plus explicit transport failures is an interrupted
        # scan, not a successful all-unpriced collection. Partial collections retain
        # per-market gaps and continue on their actually observed evidence.
        if books and not incoming and errors:
            failures=[public_quote_failure(code,minimum_delay=max(0,BUDGET.blocked_until-time.monotonic()))
                      for code in (list(by_product.values()) or list(errors))]
            detail=next((f for f in failures if not f['transient']),failures[0])
            raise ReadFailure(detail)
        stamps=[b[2] for b in incoming.values()]
        coherent=not stamps or max(stamps)-min(stamps)<=12
        tier=deepcopy(read_call('FEE_TIER',self.fees.latest_tier,now=now))
        funding=eth_funding(now=now,**funding_args)
        funding_ok=funding['valid'] and funding['row'].get('working',0)>=config.amount_eth>0
        rows=[];keys={}
        for market in selection['selected']:
            pair=market['pair'];row=model_market(market,config,rules,incoming.get(pair),tier,now)
            reason=quote_reason(incoming.get(pair),now,by_product.get(pair))
            if reason:
                row.update(state='UNPRICED',hypothesis=None,benchmark=None)
                row['blockers']=[reason]
            if not funding_ok or not coherent:
                row.update(state='UNPRICED',hypothesis=None,benchmark=None)
                row['blockers'].append('ETH_PROPOSAL_EXCEEDS_WORKING_OR_UNAVAILABLE' if not funding_ok else
                                       'QUOTE_DECISION_SPAN_EXCEEDS_12S')
            rows.append(row);keys[pair]=research_identity(config,market,rules,funding)
        study=deepcopy(self.maker_study)
        study.observe(rows,keys=keys,now=now,fees=tier,removed=removed)
        for row in rows:
            h=study.active.get(row['market']['pair'])
            if h is not None:h['_asset']=row['market']['asset']
        result=dict(at=now,mode='ETH_GROWTH',scan=self.sequence+1,rows=rows,
            state='RESEARCH_ONLY' if any(r.get('current_estimate_available') for r in rows) else 'NO_QUALIFIED_EVIDENCE',
            market_selection=selection,study_counts=study.statistics(),study_continuity=study.diagnostics(),
            fee_evidence=tier,allocation_state='UNRECONCILED / RESEARCH ONLY',working_allocation=allocation,
            quote_scheduling=dict(requested_books=len(books),research_books=len(books),request_limit=16,
                research_limit=6,quote_span_s=max(stamps)-min(stamps) if stamps else None),
            quote_errors=dict(errors),fetch_ms=elapsed,orders_submitted=0,live_order_permission=False,
            execution='BLOCKED',lab_note='Manual research only. Gaps pause frozen hypotheses; '
                'touches are uncertain fills. No ETH earnings established.')
        if stopped():return {'state':'CANCELLED'}
        read_call('LOCAL_PUBLIC_QUOTE_STORE',self.market_store.record_quotes,
            [(p,b[2],b[0],b[1],'COINBASE_PUBLIC_REST_BEST_BID_ASK') for p,b in incoming.items()],cancel=cancel)
        if stopped():return {'state':'CANCELLED'}
        self.maker_study=study;self.sequence+=1;self.last_result=result;self.last_successful_scan_at=now
        return result
