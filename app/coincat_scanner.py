"""Read-only account/market scanner for the full-balance decision policy."""
import time
from copy import deepcopy
from decimal import Decimal
from coincat_live import LiveBroker
from coincat_full_balance import rank_full_balances
from coincat_v80_discovery import select_books
from coincat_v701_transport import SCOUT, fetch_snapshot
from coincat_passive_lab import PassiveLab


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

    def scan(self, *, now=None, collect=None, cancel=None):
        fixed_now=now
        now=time.time() if now is None else now
        if self.account_at is None or not 0<=now-self.account_at<60:self.refresh(now=fixed_now)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        excluded={row['asset'] for row in self.ledger.assets() if not row.get('enabled',1)}
        funding={asset for asset,qty in self.balances.items() if qty>0 and asset not in excluded}
        plan=select_books(self.catalog,self.rules,funding,quotes=self.books,now=now,cursor=self.cursor)
        snapshots,errors,elapsed=(SCOUT.collect if collect is None else collect)(plan['books'],fetch=fetch_snapshot)
        if cancel is not None and cancel.is_set():return {'state':'CANCELLED'}
        now=time.time() if fixed_now is None else now
        self.cursor=plan['next_route_cursor']
        incoming={pair:item.book() for pair,item in snapshots.items()}
        self.books.update(incoming)
        self.books={pair:book for pair,book in self.books.items() if 0<=now-book[2]<=30}
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
        # Freeze read-only inputs so later GUI settings/STOP cannot combine
        # account quantities from one scan with books from a different scan.
        result['eth_observation'] = dict(balances=dict(self.balances),
            catalog=tuple(self.catalog), rules=deepcopy(self.rules),
            quotes=dict(self.books), now=now, balances_at=self.account_at,
            fee_rate=result['fee_rate'], excluded=tuple(sorted(excluded)))
        from coincat_v80_immediate import _prepare
        result['lab_note']=self.lab.observe(result,_prepare(self.books,self.rules,now)['books'],now=now)
        self.last_result=result
        return result
