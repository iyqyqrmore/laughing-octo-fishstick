"""Read-only v95 direct-ETH observer. No order API or financial writes."""
import time
from copy import deepcopy
from coincat_live import LiveBroker
from coincat_v701_transport import SCOUT,fetch_snapshot
from coincat_working_allocation import assess_allocation
from coincat_eth_maker import MakerStudy,select_markets,model_market


class Scanner:
    def __init__(self,ledger,client,fees,market_store):
        self.ledger=ledger;self.client=client;self.fees=fees;self.market_store=market_store
        self.broker=LiveBroker(ledger,client)
        self.catalog=[];self.rules={};self.balances={}
        self.account_at=None;self.catalog_at=None;self.sequence=0;self.last_result=None
        self.maker_study=MakerStudy()

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


    def scan_growth(self,config,*,now=None,collect=None,cancel=None,allocation_draft=()):
        """v95 active flow: one shared collection of at most three direct books.

        Legacy USD ranking, multi-leg enumeration and scheduled experiments do
        not run here. Frozen proposal/rules/fees and a staged RAM study prevent
        cancelled work from posting results or touching financial records.
        """
        config.validate()
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        fixed_now=now;now=time.time() if now is None else now
        if self.account_at is None or not 0<=now-self.account_at<60:self.refresh(now=fixed_now)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        excluded=tuple(sorted(row['asset'] for row in self.ledger.assets() if not row.get('enabled',1)))
        selection=select_markets(tuple(self.catalog),self.rules,config.companions,excluded)
        rules={m['pair']:deepcopy(self.rules[m['pair']]) for m in selection['selected']}
        allocation=assess_allocation(balances=dict(self.balances),balances_at=self.account_at,
            now=now,excluded=excluded,draft=tuple(allocation_draft))
        eth_row=next((r for r in allocation['rows'] if r['asset']=='ETH'),{})
        funding_ok=(allocation['state']!='INVALID_DRAFT' and eth_row.get('working',0)>=config.amount_eth>0
            and 'ETH' not in excluded and 0<=now-self.account_at<=120)
        books=tuple(r['pair'] for r in selection['selected'])
        snapshots,errors,elapsed=(SCOUT.collect if collect is None else collect)(books,fetch=fetch_snapshot)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        now=time.time() if fixed_now is None else now
        incoming={p:item.book() for p,item in snapshots.items() if p in books}
        stamps=[b[2] for b in incoming.values()]
        coherent=not stamps or max(stamps)-min(stamps)<=12
        tier=deepcopy(self.fees.latest_tier(now=now))
        # Retain the provider's exact capture time, including missing/stale evidence.
        tier.setdefault('captured_at',now-tier['age_s'] if 'age_s' in tier else None)
        funding_ok=funding_ok and 0<=now-self.account_at<=120
        rows=[]
        for market in selection['selected']:
            row=model_market(market,config,rules,incoming.get(market['pair']),tier,now)
            if not funding_ok or not coherent:
                row.update(state='UNPRICED',hypothesis=None,benchmark=None)
                row['blockers'].append('ETH_PROPOSAL_EXCEEDS_WORKING_OR_UNAVAILABLE' if not funding_ok else
                                       'QUOTE_DECISION_SPAN_EXCEEDS_12S')
            rows.append(row)
        study=deepcopy(self.maker_study)
        # Exact account/draft contents and exclusions invalidate prior hypotheses,
        # even when the proposed ETH amount itself has not changed.
        key=(config,allocation['snapshot_key'],allocation['draft_key'],excluded,str(rules))
        study.observe(rows,key=key,now=now)
        result=dict(at=now,mode='ETH_GROWTH',scan=self.sequence+1,rows=rows,
            state='RESEARCH_ONLY' if any(r['hypothesis'] for r in rows) else 'NO_QUALIFIED_EVIDENCE',
            market_selection=selection,study_counts=dict(study.counts),fee_evidence=tier,
            allocation_state='UNRECONCILED / RESEARCH ONLY',working_allocation=allocation,
            quote_scheduling=dict(requested_books=len(books),research_books=len(books),
                request_limit=16,research_limit=6,quote_span_s=max(stamps)-min(stamps) if stamps else None),
            quote_errors=dict(errors),fetch_ms=elapsed,orders_submitted=0,live_order_permission=False,
            execution='BLOCKED',lab_note='Manual research only. Touches are uncertain fills; '
                'no ETH earnings established. Compare the required move and waiting risk before changing controls.')
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        self.market_store.record_quotes([(p,b[2],b[0],b[1],'COINBASE_PUBLIC_REST_BEST_BID_ASK')
                                         for p,b in incoming.items()])
        self.maker_study=study;self.sequence+=1;self.last_result=result
        return result
