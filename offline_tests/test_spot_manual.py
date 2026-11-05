"""Fake SDK only: native manual tickets, order races and CSV corroboration."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D,localcontext
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid

from coincat_beta_store import BetaBlocked
from coincat_spot_market import SpotReader,limit_rules
from coincat_spot_execution import ManualExecution
from coincat_live_beta import LiveLimits
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from offline_tests.test_live_beta import Clock,PORTFOLIO,OID,NOW

def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def cid(i=100):return str(uuid.UUID(int=i))

class Venue:
    def __init__(self,clock):
        self.clock=clock;self.posts=[];self.cancels=[];self.orders={};self.fills={};self.fail=False
        self.available={a:D(10) for a in WATCH_ASSETS};self.permission={};self.rule_change={}
        self.preview_errors=[];self.preview_delay=0;self.before_post=None;self.fill_on_cancel=None
    def get_api_key_permissions(self):
        value=dict(can_view=True,can_trade=True,can_transfer=False,portfolio_uuid=PORTFOLIO);value.update(self.permission);return value
    def get_accounts(self,**kwargs):
        return dict(accounts=[dict(uuid=cid(i+500),retail_portfolio_id=PORTFOLIO,currency=a,
            available_balance={'value':str(q)},hold={'value':'0.1'}) for i,(a,q) in enumerate(self.available.items())],has_next=False)
    def get_product(self,product_id,**kwargs):
        base,quote=product_id.split('-')
        result=dict(product_id=product_id,product_type='SPOT',status='online',view_only=False,
            base_currency_id=base,quote_currency_id=quote,base_increment='.000001',price_increment='.000001',
            quote_increment='.00000001',base_min_size='.000001',base_max_size='1000',quote_min_size='.00000001',quote_max_size='1000')
        result.update(self.rule_change);return result
    def get_product_book(self,product_id,**kwargs):
        bid,ask=('2000','2001') if product_id=='ETH-USD' else ('.030000','.030010') if product_id=='ETH-BTC' else ('.001000','.001010')
        return {'pricebook':dict(product_id=product_id,bids=[dict(price=bid,size='100')],asks=[dict(price=ask,size='100')])}
    def get_transaction_summary(self,**kwargs):return {'fee_tier':dict(maker_fee_rate='.005',taker_fee_rate='.009')}
    def get_public_candles(self,**kwargs):return {'candles':[dict(start=str(int(self.clock.wall())-300),open='.03',high='.031',low='.029',close='.0301',volume='2')]}
    def preview_limit_order_gtc_buy(self,**kwargs):
        self.clock.tick(self.preview_delay)
        if self.before_post:self.before_post()
        return dict(errs=self.preview_errors,base_size=kwargs['base_size'],commission_total=str(D(kwargs['base_size'])*D(kwargs['limit_price'])*D('.009')))
    preview_limit_order_gtc_sell=preview_limit_order_gtc_buy
    def _post(self,side,kwargs):
        self.posts.append((side,kwargs));oid=cid(1000+len(self.posts))
        self.orders[oid]=dict(order_id=oid,client_order_id=kwargs['client_order_id'],retail_portfolio_id=PORTFOLIO,
            product_id=kwargs['product_id'],side=side,status='OPEN',created_time=iso(self.clock.wall()),
            filled_size='0',filled_value='0',total_fees='0',number_of_fills='0',
            order_configuration={'limit_limit_gtc':{k:kwargs[k] for k in ('base_size','limit_price','post_only')}})
        self.fills[oid]=[]
        if self.fail:raise TimeoutError('SYNTHETIC_UNKNOWN_POST')
        return dict(success=True,success_response=dict(order_id=oid,client_order_id=kwargs['client_order_id'],product_id=kwargs['product_id'],side=side))
    def limit_order_gtc_buy(self,**kwargs):return self._post('BUY',kwargs)
    def limit_order_gtc_sell(self,**kwargs):return self._post('SELL',kwargs)
    def get_order(self,order_id):return {'order':deepcopy(self.orders[order_id])}
    def get_fills(self,order_ids,**kwargs):return {'fills':deepcopy(self.fills[order_ids[0]]),'cursor':''}
    def list_orders(self,**kwargs):return {'orders':deepcopy(list(self.orders.values())),'has_next':False}
    def cancel_orders(self,order_ids):
        self.cancels.append(order_ids)
        for oid in order_ids:
            if self.fill_on_cancel:self.fill(oid,self.fill_on_cancel)
            if self.orders[oid]['status']!='FILLED':self.orders[oid]['status']='CANCELED'
        return {'results':[dict(order_id=oid,success=True) for oid in order_ids]}
    def fill(self,oid,size,*,currency=None):
        o=self.orders[oid];p=D(o['order_configuration']['limit_limit_gtc']['limit_price']);q=D(size);fee=q*p*D('.005')
        f=dict(trade_id=cid(2000+len(self.fills[oid])),order_id=oid,retail_portfolio_id=PORTFOLIO,
            product_id=o['product_id'],side=o['side'],size=str(q),price=str(p),commission=str(fee),size_in_quote=False,
            trade_time=iso(self.clock.wall()),liquidity_indicator='M')
        if currency:f['fee_currency']=currency
        self.fills[oid].append(f)
        o.update(filled_size=str(sum(D(f['size']) for f in self.fills[oid])),filled_value=str(sum(D(f['size'])*D(f['price']) for f in self.fills[oid])),
            total_fees=str(sum(D(f['commission']) for f in self.fills[oid])),number_of_fills=str(len(self.fills[oid])))
        if D(o['filled_size'])==D(o['order_configuration']['limit_limit_gtc']['base_size']):o['status']='FILLED'


class ManualLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=Clock();self.venue=Venue(self.clock)
        self.reader=SpotReader(self.venue,clock=self.clock.wall,monotonic=self.clock.monotonic,budget=None)
        self.path=Path(self.tmp.name)/'manual.sqlite3';self.engine=ManualExecution(self.path,self.reader,clock=self.clock.wall)
        self.ticket=dict(pair='ETH-BTC',side='SELL',size=D('.001'),price=D('.030010'),post_only=False)
    def send(self,ticket=None,i=100):
        self.engine.set_blocked(False);return self.engine.submit(ticket or self.ticket,cid(i))
    def test_default_block_and_read_only_connect_do_not_create_or_cancel(self):
        snap=self.reader.snapshot('ETH-BTC',account=True,candles=True,history=True)
        self.assertEqual(snap['book']['ask'],D('.030010'));self.assertEqual(snap['account']['available']['ETH'],10)
        self.assertEqual(snap['chart']['candles'][0]['volume'],2)
        with self.assertRaises(BetaBlocked):self.engine.submit(self.ticket,cid())
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_all_fourteen_native_directions_work_without_research_profit_or_websocket_inputs(self):
        for i,pair in enumerate(WATCH_PAIRS):
            for j,side in enumerate(('BUY','SELL')):
                with self.subTest(pair=pair,side=side),TemporaryDirectory(dir=self.tmp.name) as d:
                    e=ManualExecution(Path(d)/'m.sqlite3',self.reader,clock=self.clock.wall);e.set_blocked(False)
                    price=D('.030010') if pair=='ETH-BTC' else D('.001010')
                    t=dict(pair=pair,side=side,size=D('.001'),price=price,post_only=False)
                    o=e.submit(t,cid(10+i*2+j));self.assertEqual(o['state'],'OPEN')
                    self.assertEqual(self.venue.posts[-1][1]['post_only'],False)
    def test_buy_at_ask_is_marketable_limit_and_post_only_cross_is_rejected(self):
        t=dict(self.ticket,side='BUY',post_only=True)
        with self.assertRaisesRegex(BetaBlocked,'POST_ONLY_PRICE'):self.send(t)
        o=self.send(dict(t,post_only=False));self.assertEqual(o['state'],'OPEN')
        self.assertEqual(self.venue.posts[0][0],'BUY');self.assertFalse(self.venue.posts[0][1]['post_only'])
    def test_maker_buy_at_bid_and_limit_only_product_are_allowed(self):
        self.venue.rule_change={'limit_only':True};self.send(dict(self.ticket,side='BUY',price=D('.030000'),post_only=True))
        self.assertTrue(self.venue.posts[0][1]['post_only'])
    def test_cancel_partial_unknown_fee_units_allows_only_confirmed_remaining_quantity(self):
        o=self.send();self.venue.fill(o['order_id'],'.0004')
        self.engine.reconcile(o['cid']);self.assertEqual(self.engine.state()['orders'][o['cid']]['state'],'PARTIAL')
        self.assertEqual(self.engine.state()['orders'][o['cid']]['report']['native_settlement'],'UNKNOWN')
        self.engine.cancel(o['cid']);draft=self.engine.remaining_ticket(o['cid']);self.assertEqual(draft['size'],D('.0006'))
        self.assertEqual(len(self.venue.posts),1)
        new=self.engine.submit(draft,cid(101));self.assertEqual(new['size'],D('.0006'))
        self.engine.cancel(new['cid'])
        with self.assertRaises(BetaBlocked):self.engine.submit(draft,cid(102))
        self.assertEqual(len(self.venue.posts),2)
    def test_fill_racing_cancel_never_suggests_full_replacement(self):
        o=self.send();self.venue.fill_on_cancel='.001';final=self.engine.cancel(o['cid'])
        self.assertEqual(final['state'],'FILLED')
        with self.assertRaises(BetaBlocked):self.engine.remaining_ticket(o['cid'])
    def test_timeout_is_never_retried_and_recovers_original_identity_after_restart(self):
        self.venue.fail=True
        with self.assertRaisesRegex(BetaBlocked,'UNKNOWN'):self.send()
        self.assertTrue(self.engine.block.is_set());self.assertEqual(len(self.venue.posts),1)
        restarted=ManualExecution(self.path,self.reader,clock=self.clock.wall)
        self.assertTrue(restarted.block.is_set());self.venue.fail=False
        final=restarted.poll();self.assertEqual(final['orders'][cid()]['state'],'CANCELED')
        self.assertEqual(len(self.venue.posts),1)
    def test_absent_unknown_order_is_locked_even_when_history_page_is_complete(self):
        self.venue.fail=True
        with self.assertRaises(BetaBlocked):self.send()
        self.venue.orders={}
        with self.assertRaisesRegex(BetaBlocked,'LOCKED'):self.engine.reconcile(cid())
        with self.assertRaises(BetaBlocked):self.engine.set_blocked(False)
        self.assertEqual(len(self.venue.posts),1)
    def test_duplicate_click_is_idempotent_and_changed_duplicate_is_rejected(self):
        first=self.send();again=self.engine.submit(self.ticket,cid());self.assertEqual(first,again)
        with self.assertRaises(BetaBlocked):self.engine.submit(dict(self.ticket,size=D('.002')),cid())
        self.assertEqual(len(self.venue.posts),1)
    def test_preview_error_stale_or_stop_sends_no_order(self):
        for mode in ('error','stale','stop'):
            with self.subTest(mode=mode):
                self.engine.set_blocked(False);self.venue.preview_errors=[{'error':'REJECTED'}] if mode=='error' else []
                self.venue.preview_delay=31 if mode=='stale' else 0
                self.venue.before_post=(lambda:self.engine.set_blocked(True)) if mode=='stop' else None
                with self.assertRaises(BetaBlocked):self.engine.submit(self.ticket,cid())
                self.assertEqual(self.engine.state()['orders'],{});self.assertEqual(self.venue.posts,[])
    def test_permissions_precision_native_minimum_and_available_source_are_binding(self):
        changes=[{'view_only':True},{'cancel_only':True},{'status':'offline'},{'base_min_size':'.002'},
            {'quote_min_size':'1'},{'base_increment':'.003'},{'price_increment':'.002'},{'post_only':True}]
        self.engine.set_blocked(False)
        for change in changes:
            self.venue.rule_change=change
            with self.subTest(change=change),self.assertRaises(BetaBlocked):self.engine.submit(self.ticket,cid())
        self.venue.rule_change={};self.venue.available['ETH']=D('.001')
        with self.assertRaisesRegex(BetaBlocked,'AVAILABLE'):self.engine.submit(self.ticket,cid())
        self.assertEqual(self.venue.posts,[])
    def test_low_sell_limit_cannot_hide_source_market_value_from_usd_cap(self):
        with self.assertRaisesRegex(BetaBlocked,'USD_CAP'):self.send(dict(self.ticket,size=D('.01'),price=D('.000001')))
        self.assertEqual(self.venue.posts,[])
    def test_cancellation_ack_is_not_final_and_fill_page_gap_keeps_quantity_locked(self):
        o=self.send();self.venue.fill(o['order_id'],'.0002');self.venue.fills[o['order_id']]=[]
        with self.assertRaises(BetaBlocked):self.engine.cancel(o['cid'])
        with self.assertRaises(BetaBlocked):self.engine.remaining_ticket(o['cid'])
        self.assertTrue(self.engine.block.is_set())
    def test_block_or_expiry_cancels_only_owned_order_and_never_places_again(self):
        o=self.send();self.clock.tick(1801);self.engine.poll()
        self.assertTrue(self.engine.block.is_set());self.assertEqual(self.venue.cancels,[[o['order_id']]])
        self.assertEqual(len(self.venue.posts),1)
    def test_spending_and_order_caps_survive_restarts_without_hidden_reseed(self):
        self.engine.configure(LiveLimits(max_orders=1));o=self.send();self.engine.cancel(o['cid'])
        e=ManualExecution(self.path,self.reader,clock=self.clock.wall);e.set_blocked(False)
        with self.assertRaisesRegex(BetaBlocked,'ORDER_CAP'):e.submit(self.ticket,cid(101))
        with self.assertRaises(BetaBlocked):e.configure(LiveLimits())
    def test_read_interface_rejects_every_write_method(self):
        for name in ('cancel_orders','limit_order_gtc_buy','preview_limit_order_gtc_buy','market_order_buy'):
            with self.assertRaises(BetaBlocked):self.reader.call(name)
    def test_new_session_preserves_completed_journal_and_caps_and_refuses_unresolved(self):
        self.engine.configure(LiveLimits(max_orders=2));o=self.send()
        with self.assertRaises(BetaBlocked):self.engine.new_session()
        self.engine.cancel(o['cid']);self.engine.new_session()
        self.assertTrue(self.engine.block.is_set());self.assertEqual(self.engine.state()['orders'],{})
        self.assertEqual(self.engine.state()['limits']['max_orders'],2)
        archives=list(self.path.parent.glob('completed-*.sqlite3'));self.assertEqual(len(archives),1)
        old=ManualExecution(archives[0],self.reader,clock=self.clock.wall)
        self.assertEqual(old.state()['orders'][o['cid']]['state'],'CANCELED')
        self.assertEqual(len(self.venue.posts),1)
    def test_cancel_checks_remote_identity_before_sending_for_an_owned_id(self):
        o=self.send();self.venue.orders[o['order_id']]['client_order_id']=cid(777)
        with self.assertRaises(BetaBlocked):self.engine.cancel(o['cid'])
        self.assertEqual(self.venue.cancels,[])
    def test_transfer_permission_and_portfolio_change_block_without_creating(self):
        self.engine.set_blocked(False)
        for change in ({'can_transfer':True},{'can_transfer':None},{'can_trade':False},{'portfolio_uuid':None}):
            self.venue.permission=change
            with self.subTest(change=change),self.assertRaises(BetaBlocked):self.engine.submit(self.ticket,cid())
        self.assertEqual(self.venue.posts,[])
    def test_nonfinite_and_eth_usd_tickets_never_reach_preview_or_create(self):
        self.engine.set_blocked(False)
        for change in ({'size':'NaN'},{'price':'Infinity'},{'pair':'ETH-USD'},{'size':True},{'post_only':1},{'side':'MARKET'}):
            with self.subTest(change=change),self.assertRaises((BetaBlocked,ValueError)):
                self.engine.submit(dict(self.ticket,**change),cid())
        self.assertEqual(self.venue.posts,[])
    def test_retry_enabled_sdk_adapter_is_refused_before_preview_and_create(self):
        from types import SimpleNamespace
        self.venue.session=SimpleNamespace(get_adapter=lambda url:SimpleNamespace(max_retries=SimpleNamespace(total=3)))
        with self.assertRaisesRegex(BetaBlocked,'RETRIES'):self.send()
        self.assertEqual(self.venue.posts,[])
    def test_book_with_stale_exchange_time_is_rejected_and_fx_is_read_only(self):
        from coincat_spot_market import native_book
        raw=self.venue.get_product_book('ETH-BTC');raw['pricebook']['time']=iso(self.clock.wall()-31)
        with self.assertRaises(BetaBlocked):native_book('ETH-BTC',raw,self.clock.wall())
        with self.assertRaises(BetaBlocked):self.reader.product('ETH-USD')
        with self.assertRaises(BetaBlocked):self.reader.candles('ETH-USD')
    def test_optional_candle_failure_does_not_destroy_valid_native_book(self):
        self.venue.get_public_candles=lambda **k:(_ for _ in ()).throw(TimeoutError())
        snap=self.reader.snapshot('ETH-BTC',candles=True)
        self.assertIsNone(snap['chart']);self.assertEqual(snap['book']['ask'],D('.030010'))
        self.assertIn('CANDLES_UNAVAILABLE',snap['errors'])
    def test_native_preflight_and_preview_do_not_depend_on_callers_decimal_precision(self):
        ticket=dict(self.ticket,size=D('.001234'),price=D('.030011'))
        with localcontext() as context:
            context.prec=6;order=self.send(ticket)
        self.assertEqual(order['preview_fee'],D('.000000333302166'))
        self.assertEqual(order['size'],D('.001234'));self.assertEqual(order['price'],D('.030011'))


class StatementCorroboration(unittest.TestCase):
    def evidence(self):
        from offline_tests.test_beta_evidence import native_record
        from coincat_manual_trade import order_report
        from coincat_statement_math import reconstruct
        order,fills=native_record(currency=None)
        record=dict(order=order,fills=fills,report=order_report(order,fills,portfolio=PORTFOLIO),complete=True)
        row={'Timestamp':iso(NOW+106),'Transaction Type':'Advanced Trade Sell','Asset':'ETH','Quantity Transacted':'-.005',
            'Notes':'Sold 0.005 ETH for 0.0001505833 BTC on ETH-BTC at 0.030268 BTC/ETH'}
        return record,{'reports':[reconstruct(row)]}
    def test_exact_native_settlement_is_corroborated_without_rewriting_api_currency_or_fill(self):
        from coincat_statement_math import corroborate
        record,statement=self.evidence();before=deepcopy(record);result=corroborate(record,statement)
        self.assertEqual(result['report']['native_settlement'],'STATEMENT_CORROBORATED_NATIVE_FLOW')
        self.assertEqual(result['report']['quote_change'],D('.0001505833'));self.assertEqual(result['report']['base_change'],D('-.005'))
        self.assertEqual(record,before);self.assertEqual(result['fills'],record['fills'])
        self.assertEqual(result['report']['fee_currencies'],[None]);self.assertEqual(result['report']['profit'],'NOT_ASSESSED')
        self.assertEqual(result['report']['statement_identifier_join'],'NOT_PROVEN_FIELD_MATCH_ONLY')
    def test_duplicate_row_wrong_time_fee_or_reported_currency_remains_unknown(self):
        from coincat_statement_math import corroborate
        for mode in ('duplicate','time','fee','currency'):
            record,statement=self.evidence()
            if mode=='duplicate':statement['reports']*=2
            if mode=='time':statement['reports'][0]['timestamp']+=1
            if mode=='fee':statement['reports'][0]['implied_quote_deduction']+=D('.000000000001')
            if mode=='currency':record['fills'][0]['fee_currency']='ETH'
            with self.subTest(mode=mode):self.assertEqual(corroborate(record,statement)['report']['native_settlement'],'UNKNOWN')
    def test_one_statement_row_cannot_be_reused_for_two_orders_with_identical_native_fields(self):
        from coincat_statement_math import corroborate_many
        record,statement=self.evidence();other=deepcopy(record)
        other['order']['order_id']=cid(600);other['report']['order_id']=cid(600)
        other['fills'][0].update(order_id=cid(600),trade_id=cid(601))
        results=corroborate_many([record,other],statement)
        self.assertEqual([r['report']['native_settlement'] for r in results],['UNKNOWN','UNKNOWN'])
