"""No real network. An enabled beta can POST only its qualified bounded intent."""
from copy import deepcopy
from contextlib import closing
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
import unittest
import uuid

from coincat_adaptive_eth import Frame
from coincat_beta_store import BetaStore,BetaBlocked
from coincat_live import LiveBroker,LiveBlocked
from coincat_live_beta import LiveBeta,LiveLimits
from coincat_global_paper import GlobalSettings
from coincat_fee_prices import ask_costs
from offline_tests import test_global_paper as g
from offline_tests import test_auto_paper as old
from offline_tests.sqlite_resources import held_sqlite_connections

NOW=old.NOW
PORTFOLIO='00000000-0000-0000-0000-000000000002'
OID='00000000-0000-0000-0000-000000000003'
TID='00000000-0000-0000-0000-000000000004'


class Clock:
    def __init__(self):self.at=NOW+10;self.mono=10
    def wall(self):return self.at
    def tick(self,seconds):self.at+=seconds;self.mono+=seconds
    def monotonic(self):return self.mono


def profitable_frame(at=NOW+10,*,units=True,second_buy=False):
    cross=(D(1),D('1.001'),at) if second_buy else (D('.999'),D(1),at)
    base=g.evidence_frame(at,changes={'ETH-BTC':(D('.999'),D(1),at),'SOL-BTC':cross})
    rules=deepcopy(base._rules)
    for row in rules.values():row.update(base_increment='.00000001',quote_increment='.00000000000001',price_increment='.000001')
    return Frame(at,base._catalog,rules,base._quotes,base._tier,base._excluded,
        _depth=base._depth,_fee_units=base._fee_units if units else {})


class Venue:
    def __init__(self,frame):self.frame=frame;self.posts=[];self.cancel_posts=[];self.fail=False
    def get_api_key_permissions(self):return dict(can_view=True,can_trade=True,can_transfer=False,portfolio_uuid=PORTFOLIO)
    def get_product(self,product_id,**kwargs):return deepcopy(self.frame._rules[product_id])
    def get_product_book(self,product_id,**kwargs):
        bid,ask,_=self.frame.book(product_id)
        return {'pricebook':{'product_id':product_id,'bids':[{'price':str(bid),'size':'100'}],'asks':[{'price':str(ask),'size':'100'}]}}
    def limit_order_gtc_sell(self,**kwargs):
        self.posts.append(kwargs)
        if self.fail:raise TimeoutError('SYNTHETIC_UNCERTAIN_POST')
        return {'success':True,'success_response':{'order_id':str(uuid.UUID(int=3+len(self.posts)-1))}}
    def limit_order_gtc_buy(self,**kwargs):return self.limit_order_gtc_sell(**kwargs)
    def market_order_buy(self,**kwargs):raise AssertionError('NO_MARKET_ORDER')
    def market_order_sell(self,**kwargs):raise AssertionError('NO_MARKET_ORDER')
    def cancel_orders(self,**kwargs):self.cancel_posts.append(kwargs);return {'results':[{'order_id':OID,'success':True}]}
    def get_order(self,order_id):
        return {'order':dict(order_id=order_id,client_order_id=self.posts[-1]['client_order_id'],retail_portfolio_id=PORTFOLIO,
            product_id=self.posts[-1]['product_id'],side='SELL',status='OPEN',filled_size='0',filled_value='0',total_fees='0',number_of_fills='0')}


class LiveBetaGate(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.clock=Clock()
        self.engine=LiveBeta(Path(self.temp.name)/'live',clock=self.clock.wall,monotonic=self.clock.monotonic)
        self.frame=profitable_frame();self.venue=Venue(self.frame)
        self.broker=LiveBroker(None,self.venue);self.broker.live_runtime=self.engine

    def funded(self):
        self.engine.create(LiveLimits(max_eth=D('.00408612')),GlobalSettings(),funding=old.funding(),portfolio=PORTFOLIO,at=NOW)
        self.engine.set_blocked(False);self.engine.start(at=NOW+10)

    def prepare(self,frame=None):
        frame=frame or self.frame
        return self.engine.prepare(frame,g.usd(frame.at),account=dict(at=frame.at,portfolio=PORTFOLIO,available={'ETH':D(1)},carveouts={}))

    def test_switch_starts_blocked_and_legacy_calls_cannot_bypass_it(self):
        self.assertTrue(self.engine.blocked.is_set())
        with self.assertRaises(LiveBlocked):self.broker.submit('BUY','BTC-USD','1')
        self.assertEqual(self.venue.posts,[])

    def test_enabled_qualified_bounded_intent_reaches_real_post_only_adapter_once(self):
        self.funded();cid=self.prepare();self.assertIsNotNone(cid,self.engine.view_rows)
        order=self.engine.private_state()['orders'][cid]
        self.assertEqual(order['pair'],'ETH-BTC');self.assertEqual(order['source_budget'],D('.00408612'))
        self.broker.submit(live_dispatch=cid)
        self.assertEqual(len(self.venue.posts),1)
        self.assertEqual(self.venue.posts[0]['post_only'],True);self.assertEqual(self.venue.posts[0]['retail_portfolio_id'],PORTFOLIO)
        self.assertEqual(self.engine.private_state()['orders'][cid]['state'],'OPEN')
        with self.assertRaises(LiveBlocked):self.broker.submit(live_dispatch=cid)
        self.assertEqual(len(self.venue.posts),1)

    def test_reblocking_after_reserve_prevents_post_and_does_not_liquidate(self):
        self.funded();cid=self.prepare();self.engine.set_blocked(True)
        with self.assertRaises(LiveBlocked):self.broker.submit(live_dispatch=cid)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D('.00408612')})

    def test_unknown_native_units_still_block_enabled_first_entry(self):
        self.funded();self.assertIsNone(self.prepare(profitable_frame(units=False)))
        self.assertEqual(self.engine.private_state()['orders'],{});self.assertEqual(self.venue.posts,[])

    def test_fee_gap_holds_without_permanent_storage_error_and_fresh_evidence_can_resume(self):
        self.funded();missing=Frame(self.frame.at,self.frame._catalog,self.frame._rules,self.frame._quotes,{},self.frame._excluded)
        self.assertIsNone(self.prepare(missing));self.assertIsNone(self.engine.problem);self.assertEqual(self.engine.private_state()['mode'],'ACTIVE')
        self.assertTrue(all(r['state']=='HOLD' for r in self.engine.view_rows.values()))
        self.clock.tick(31);self.assertIsNotNone(self.prepare(profitable_frame(self.clock.at)))

    def test_placement_timeout_locks_original_identity_and_cannot_retry(self):
        self.funded();cid=self.prepare();self.venue.fail=True
        with self.assertRaises(LiveBlocked):self.broker.submit(live_dispatch=cid)
        self.assertEqual(self.engine.private_state()['mode'],'UNKNOWN_LOCKED');self.assertTrue(self.engine.blocked.is_set())
        with self.assertRaises(LiveBlocked):self.broker.submit(live_dispatch=cid)
        self.assertEqual(len(self.venue.posts),1)

    def test_restart_forces_block_on_and_reconciliation_without_reseeding(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);before=self.engine.private_state()
        restored=LiveBeta(self.engine.directory,clock=self.clock.wall,monotonic=self.clock.monotonic)
        self.assertTrue(restored.blocked.is_set());self.assertEqual(restored.private_state()['mode'],'RECONCILIATION_REQUIRED')
        self.assertEqual(restored.private_state()['wallet'],before['wallet']);self.assertEqual(restored.private_state()['orders'],before['orders'])

    def test_fee_adjusted_ask_benchmark_is_not_a_ten_percent_or_0001_percent_markup(self):
        result=ask_costs('ETH-BTC',D('.030255'),D('.005'),fee_currency='BTC',price_increment=D('.000001'))
        self.assertEqual(result['buy_cost_per_base'],D('.030406275'))
        self.assertEqual(result['sell_limit_retaining_market_ask'],D('.030408'))
        self.assertEqual(result['classification'],'FEE_COST_BENCHMARK_NOT_SUBMITTED_LIMIT')

    def test_live_journal_rejects_financial_database_and_conflicting_event_ids(self):
        path=Path(self.temp.name)/'unrelated.sqlite3'
        import sqlite3
        with held_sqlite_connections() as handles:
            with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE original(value)')
            self.assertTrue(handles[0].closed,'The fixture must close before Windows temporary-directory cleanup')
            before=path.read_bytes()
            with self.assertRaises((ValueError,sqlite3.Error)):BetaStore(path,7,initial={})
            self.assertEqual(path.read_bytes(),before)
            self.funded();store=self.engine.store
            store.change('TEST','fixed',{'x':D(1)},lambda s:None)
            revision=store.revision;store.change('TEST','fixed',{'x':D(1)},lambda s:None)
            self.assertEqual(store.revision,revision)
            with self.assertRaises(BetaBlocked):store.change('TEST','fixed',{'x':D(2)},lambda s:None)
            self.assertTrue(all(db.closed for db in handles),'Rejected stores and duplicate/conflicting events must close every handle')

    def test_corrupt_live_store_rejection_closes_handle_without_mutating_the_file(self):
        import sqlite3
        path=Path(self.temp.name)/'malformed.sqlite3';before=b'SYNTHETIC non-SQLite data; preserve unchanged'
        path.write_bytes(before)
        with held_sqlite_connections() as handles:
            with self.assertRaises(sqlite3.DatabaseError):BetaStore(path,7,initial={})
            self.assertTrue(handles,'The rejection must exercise an actual SQLite connection')
            self.assertTrue(all(db.closed for db in handles),'Corrupt-header rejection must release its SQLite handle')
            self.assertEqual(path.read_bytes(),before)

    def receipt(self,cid,*,fraction=D(1),currency='BTC',status='FILLED'):
        order=self.engine.private_state()['orders'][cid];quantity=order['base_size']*fraction;gross=quantity*order['limit_price'];fee=gross*D('.005')
        raw=dict(trade_id=TID,order_id=OID,retail_portfolio_id=PORTFOLIO,product_id=order['pair'],side=order['side'],
            price=str(order['limit_price']),size=str(quantity),size_in_quote=False,commission=str(fee),liquidity_indicator='M',
            trade_time=datetime.fromtimestamp(self.clock.at,timezone.utc).isoformat())
        if currency is not None:raw['fee_currency']=currency
        actual=dict(order_id=OID,client_order_id=cid,retail_portfolio_id=PORTFOLIO,product_id=order['pair'],side=order['side'],
            status=status,number_of_fills='1',filled_size=str(quantity),filled_value=str(gross),total_fees=str(fee))
        return actual,[raw]

    def test_actual_quote_fee_fill_settles_once_and_is_not_a_paper_or_legacy_credit(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);self.clock.tick(1)
        actual,fills=self.receipt(cid)
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        state=self.engine.private_state();self.assertEqual(state['wallet'],{'ETH':D(0),'BTC':D('.0040656894')})
        self.assertEqual(state['orders'][cid]['state'],'FILLED');self.assertEqual(len(state['fills']),1)
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        self.assertEqual(self.engine.private_state()['wallet'],state['wallet'])
        self.assertEqual(self.engine.private_state()['fills'],state['fills'])

    def test_missing_real_fee_units_retains_evidence_and_full_locks_without_guessing(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);self.clock.tick(1)
        actual,fills=self.receipt(cid,currency=None)
        self.assertFalse(self.engine.reconcile_order(cid,actual,fills,complete=True))
        state=self.engine.private_state();self.assertEqual(state['wallet'],{'ETH':D('.00408612')})
        self.assertEqual(state['orders'][cid]['reserved'],D('.00408612'))
        self.assertEqual(state['mode'],'UNKNOWN_LOCKED');self.assertTrue(state['unresolved_evidence'][cid])
        fills[0]['fee_currency']='BTC'
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        self.engine.finish_reconciliation();self.assertEqual(self.engine.private_state()['mode'],'PAUSED');self.assertTrue(self.engine.blocked.is_set())

    def test_canceled_partial_keeps_actual_fill_fees_and_only_unspent_source_is_released(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);self.clock.tick(1)
        actual,fills=self.receipt(cid,fraction=D('.5'),status='OPEN')
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        self.assertEqual(self.engine.available('BTC'),0)
        self.engine.set_blocked(True);self.broker.cancel_live_beta(cid)
        mid=self.engine.private_state()['orders'][cid];self.assertEqual(mid['state'],'CANCEL_PENDING');self.assertGreater(mid['reserved'],0)
        actual['status']='CANCELED';self.clock.tick(3)
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        state=self.engine.private_state();self.assertEqual(state['wallet'],{'ETH':D('.00204306'),'BTC':D('.0020328447')})
        self.assertEqual(state['orders'][cid]['reserved'],0);self.assertEqual(len(self.venue.cancel_posts),1)

    def test_changed_fee_correction_never_debits_or_credits_twice(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);self.clock.tick(1)
        actual,fills=self.receipt(cid);self.engine.reconcile_order(cid,actual,fills,complete=True);before=self.engine.private_state()['wallet']
        fills[0]['commission']=str(D(fills[0]['commission'])+D('.000000001'));actual['total_fees']=fills[0]['commission']
        self.assertFalse(self.engine.reconcile_order(cid,actual,fills,complete=True))
        self.assertEqual(self.engine.private_state()['wallet'],before);self.assertEqual(self.engine.private_state()['mode'],'UNKNOWN_LOCKED')
        self.assertEqual(self.engine.public()['unresolved'],1)
        with self.assertRaises(BetaBlocked):self.engine.finish_reconciliation()

    def test_real_buy_uses_only_settled_owned_btc_and_fee_inside_half_source_budget(self):
        self.funded();cid=self.prepare();self.broker.submit(live_dispatch=cid);actual,fills=self.receipt(cid)
        gross=D(actual['filled_value']);fills[0]['commission']=str(gross*D('.02'));actual['total_fees']=fills[0]['commission']
        self.assertTrue(self.engine.reconcile_order(cid,actual,fills,complete=True))
        self.clock.tick(31);frame=profitable_frame(self.clock.at,second_buy=True);self.venue.frame=frame
        owned=self.engine.private_state()['wallet']['BTC']
        second=self.engine.prepare(frame,g.usd(frame.at),account=dict(at=frame.at,portfolio=PORTFOLIO,available={'BTC':owned},carveouts={}))
        self.assertIsNotNone(second,self.engine.view_rows);order=self.engine.private_state()['orders'][second]
        self.assertEqual(order['pair'],'SOL-BTC');self.assertEqual(order['side'],'BUY');self.assertEqual(order['source_budget'],owned/2)
        self.broker.submit(live_dispatch=second);sent=self.venue.posts[-1]
        self.assertTrue(sent['post_only']);self.assertEqual(D(sent['limit_price']),D(1))
        self.assertEqual(D(sent['base_size'])*D(sent['limit_price'])*D('1.02'),owned/2)
