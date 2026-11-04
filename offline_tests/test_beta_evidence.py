"""Synthetic native evidence only; no account, network, credentials or fills."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import unittest

from coincat_beta_store import BetaBlocked
from coincat_manual_trade import (order_report,HistoryReader,ReadOnlyAPI,ManualTradeStore,fill_count)
from coincat_order_book import BookHub,BookInvalid,display_levels,scheduled_products
from coincat_book_stream import BookStream
from coincat_beta_public import project,validate
from offline_tests.test_live_beta import PORTFOLIO,OID,TID,NOW


def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat()


def native_record(*,side='SELL',currency='BTC',status='FILLED'):
    # Synthetic IDs with native arithmetic modeled on a small limit trade.
    order=dict(order_id=OID,retail_portfolio_id=PORTFOLIO,product_id='ETH-BTC',side=side,
        status=status,created_time=iso(NOW),filled_size='0.005',filled_value='0.000151340',
        total_fees='0.000000756700',number_of_fills='1',order_configuration={'limit_limit_gtc':{'post_only':True}})
    fill=dict(trade_id=TID,order_id=OID,retail_portfolio_id=PORTFOLIO,product_id='ETH-BTC',side=side,
        price='0.030268',size='0.005',size_in_quote=False,commission='0.000000756700',
        trade_time=iso(NOW+106),liquidity_indicator='M')
    if currency is not None:fill['fee_currency']=currency
    return order,[fill]


class ReadVenue:
    def __init__(self):self.order,self.fills=native_record();self.calls=[];self.cursor_only=False;self.conflict=False
    def get_api_key_permissions(self):return {'can_view':True,'can_trade':False,'portfolio_uuid':PORTFOLIO}
    def get_order(self,**kwargs):self.calls.append(('order',kwargs));return {'order':deepcopy(self.order)}
    def get_fills(self,**kwargs):
        self.calls.append(('fills',kwargs));fills=deepcopy(self.fills)
        if self.cursor_only and not kwargs.get('cursor'):return {'fills':fills,'cursor':'next'}
        if self.cursor_only:
            if self.conflict:fills[0]['commission']='0.000000756701'
            return {'fills':fills,'cursor':''}
        return {'fills':fills,'cursor':''}
    def list_orders(self,**kwargs):return {'orders':[deepcopy(self.order)],'has_next':False}
    def get_accounts(self,**kwargs):return {'accounts':[dict(uuid='00000000-0000-0000-0000-000000000009',
        retail_portfolio_id=PORTFOLIO,currency='ETH',available_balance={'value':'0.5'},hold={'value':'0.2'})],'has_next':False}
    def create_order(self,**kwargs):raise AssertionError('READ_ONLY_IMPORT_CANNOT_POST')
    def cancel_orders(self,**kwargs):raise AssertionError('READ_ONLY_IMPORT_CANNOT_CANCEL')


class ManualEvidence(unittest.TestCase):
    def test_numeric_exchange_trade_id_is_supported_without_guessing_order_uuid(self):
        order,fills=native_record();fills[0]['trade_id']='12345678901234567890'
        result=order_report(order,fills,portfolio=PORTFOLIO)
        self.assertEqual(result['native_settlement'],'KNOWN_FILL_FLOW_NOT_ACCOUNT_RECONCILIATION')

    def test_two_quote_fee_legs_use_one_minus_f_over_one_plus_f_with_visible_dust(self):
        from coincat_paper_policy import receipt
        from offline_tests.test_live_beta import profitable_frame
        frame=profitable_frame();fee=D('.005')
        sold=receipt(frame,'ETH-BTC','SELL',D(1),D(1),fee)
        bought=receipt(frame,'ETH-BTC','BUY',sold['output_quantity'],D(1),fee)
        correct=(1-fee)/(1+fee)
        self.assertEqual(sold['output_quantity'],D('.995'))
        self.assertLessEqual(bought['output_quantity'],correct)
        self.assertLess(correct-bought['output_quantity'],D('.00000001'))
        self.assertGreater(bought['output_quantity'],D('.990025'))
        self.assertGreaterEqual(sold['output_quantity']-bought['input_quantity'],0)

    def test_statement_percent_is_derived_historical_deduction_not_live_fee_setting(self):
        from coincat_statement_math import reconstruct
        row={'Transaction Type':'Advanced Trade Sell','Asset':'ETH','Quantity Transacted':'-0.005',
            'Notes':'Sold 0.005 ETH for 0.0001505833 BTC on ETH-BTC at 0.030268 BTC/ETH',
            'Price Currency':'USD','Price at Transaction':'2432.31650312','Fees and/or Spread':'0.060807912578'}
        result=reconstruct(row);self.assertEqual(result['implied_fee_fraction'],D('.005'))
        self.assertEqual(result['implied_fee_percent'],D('.5'));self.assertTrue(result['usd_fee_consistent'])
        self.assertEqual(result['statement_quote_total'],D('.0001505833'));self.assertFalse(result['future_fee_authority'])
        self.assertEqual(result['order_identifier_join'],'NOT_PROVEN')
    def test_exact_sell_and_buy_quote_commission_once_and_no_profit_claim(self):
        order,fills=native_record();sell=order_report(order,fills,portfolio=PORTFOLIO)
        self.assertEqual(sell['quote_change'],D('.000150583300'));self.assertEqual(sell['base_change'],D('-.005'))
        self.assertEqual(sell['fee_amount']/sell['gross_quote'],D('.005'))
        self.assertEqual(sell['creation_to_first_fill_s'],106);self.assertEqual(sell['accepted_resting_duration'],'UNKNOWN')
        self.assertEqual(sell['manual_origin'],'OWNER_ATTESTATION_REQUIRED');self.assertEqual(sell['profit'],'NOT_ASSESSED')
        order,fills=native_record(side='BUY');buy=order_report(order,fills,portfolio=PORTFOLIO)
        self.assertEqual(buy['quote_change'],D('-.000152096700'));self.assertEqual(buy['base_change'],D('.005'))

    def test_unknown_or_third_asset_fee_does_not_become_quote_commission(self):
        for currency in (None,'ETH','SOL'):
            with self.subTest(currency=currency):
                order,fills=native_record(currency=currency);report=order_report(order,fills,portfolio=PORTFOLIO)
                self.assertEqual(report['state'],'FILLED');self.assertEqual(report['native_settlement'],'UNKNOWN');self.assertIsNone(report['quote_change'])

    def test_conflicting_order_totals_and_missing_size_flag_remain_unresolved(self):
        for change in ('totals','flag','portfolio','zero'):
            order,fills=native_record()
            if change=='totals':order['total_fees']='0.000000756701'
            elif change=='flag':fills[0].pop('size_in_quote')
            elif change=='portfolio':fills[0]['retail_portfolio_id']=OID
            else:order.update(number_of_fills='0',filled_size='0',filled_value='0',total_fees='0');fills=[]
            report=order_report(order,fills,portfolio=PORTFOLIO)
            self.assertEqual(report['state'],'HISTORY_INCOMPLETE');self.assertEqual(report['native_settlement'],'UNKNOWN')
        for raw in (True,1.0,'1.0',None,'-1','1e0'):
            with self.assertRaises(BetaBlocked):fill_count(raw)

    def test_view_only_key_and_cursor_only_pagination_dedup_without_write_interface(self):
        venue=ReadVenue();venue.cursor_only=True;api=ReadOnlyAPI(venue)
        reader=HistoryReader(api,clock=lambda:NOW+120);record=reader.one(OID)
        self.assertTrue(record['complete']);self.assertEqual(len(record['fills']),1)
        self.assertEqual(len([c for c in venue.calls if c[0]=='fills']),2)
        self.assertTrue(all('start_sequence_timestamp' not in c[1] for c in venue.calls))
        with self.assertRaises(BetaBlocked):api.call('create_order')
        venue.conflict=True
        with self.assertRaises(BetaBlocked):HistoryReader(api).one(OID)

    def test_store_keeps_canceled_cases_and_corrections_without_crediting_any_wallet(self):
        with TemporaryDirectory() as directory:
            store=ManualTradeStore(Path(directory)/'manual.sqlite3');venue=ReadVenue()
            reader=HistoryReader(ReadOnlyAPI(venue),clock=lambda:NOW+120);record=reader.one(OID)
            run=dict(records=[record],complete=True,reason='SYNTHETIC_READ',portfolio=PORTFOLIO,at=NOW+120)
            store.append(run);store.append(run);self.assertEqual(len(store.records()),1)
            state=store.store.state();self.assertEqual(len(next(iter(state['orders'].values()))),1)
            self.assertNotIn('wallet',state);self.assertNotIn('orders_submitted',store.public())
            changed=deepcopy(run);changed['records'][0]['fills'][0]['commission']='0.000000756701'
            store.append(changed);self.assertEqual(store.records()[0]['report']['native_settlement'],'UNKNOWN')
            self.assertEqual(next(iter(store.store.state()['fills'].values()))['commission'],'0.000000756700')

    def test_available_snapshot_already_excludes_venue_holds(self):
        reader=HistoryReader(ReadOnlyAPI(ReadVenue()),clock=lambda:NOW)
        snap=reader.account_snapshot();self.assertEqual(snap['available']['ETH'],D('.5'));self.assertEqual(snap['holds']['ETH'],D('.2'))


def packet(seq,pair='ETH-BTC',kind='snapshot',updates=None,at=NOW):
    return dict(channel='l2_data',sequence_num=seq,timestamp=iso(at),events=[dict(type=kind,product_id=pair,
        updates=updates or [dict(side=side,price_level=price,new_quantity=size,event_time=iso(at)) for side,price,size in
        (('bid','1','2'),('bid','.9','3'),('offer','1.1','4'),('offer','1.2','5'))])])


class BookEvidence(unittest.TestCase):
    def setUp(self):
        self.hub=BookHub();self.generation=self.hub.begin(('ETH-BTC','SOL-BTC'))
    def apply(self,value,at=NOW,mono=0):return self.hub.apply(value,generation=self.generation,at=at,mono=mono)
    def heartbeat(self,at=NOW,mono=0):self.apply(dict(channel='heartbeats',timestamp=iso(at),events=[dict(current_time=iso(at),heartbeat_counter='1')]),at,mono)

    def test_connection_channel_sequence_interleaves_products_and_absolute_zero_deletes(self):
        self.apply(packet(40));self.apply(packet(41,'SOL-BTC'));self.heartbeat()
        update=packet(42,kind='update',updates=[dict(side='bid',price_level='1',new_quantity='7',event_time=iso(NOW))])
        self.apply(update);self.assertFalse(self.apply(update));view=self.hub.view('ETH-BTC',at=NOW,mono=0)
        self.assertEqual(view.bids[0],(D(1),D(7)))
        update['sequence_num']=43;update['events'][0]['updates'][0]['new_quantity']='0';self.apply(update)
        self.assertEqual(self.hub.view('ETH-BTC',at=NOW,mono=0).bids[0][0],D('.9'))

    def test_gap_reconnect_requires_new_snapshot_and_rejects_previous_generation(self):
        self.apply(packet(2));self.heartbeat()
        with self.assertRaises(BookInvalid):self.apply(packet(4,kind='update'))
        self.assertNotEqual(self.hub.view('ETH-BTC',at=NOW,mono=0).state,'HEALTHY')
        previous=self.generation;self.generation=self.hub.begin(('ETH-BTC',))
        self.assertFalse(self.hub.apply(packet(3),generation=previous,at=NOW,mono=0))
        with self.assertRaises(BookInvalid):self.apply(packet(9,kind='update'))
        self.apply(packet(90));self.heartbeat();self.assertEqual(self.hub.view('ETH-BTC',at=NOW,mono=0).state,'HEALTHY')

    def test_product_staleness_is_not_refreshed_by_connection_heartbeat(self):
        self.apply(packet(0));self.heartbeat(NOW+31,31)
        view=self.hub.view('ETH-BTC',at=NOW+31,mono=31)
        self.assertEqual(view.state,'STALE');self.assertEqual(view.observed_at,NOW)
        self.heartbeat();self.assertEqual(self.hub.view('ETH-BTC',at=NOW+1,mono=6).reason,'HEARTBEAT_TIMEOUT')

    def test_fresh_snapshot_can_contain_old_unchanged_levels_and_diagnostic_heartbeat_clock(self):
        value=packet(0)
        for update in value['events'][0]['updates']:update['event_time']='1970-01-01T00:00:00Z'
        self.apply(value)
        self.apply(dict(channel='heartbeats',timestamp=iso(NOW),events=[dict(current_time='server diagnostic +0000 UTC m=+1.0',heartbeat_counter=2)]))
        self.assertEqual(self.hub.view('ETH-BTC',at=NOW,mono=0).state,'HEALTHY')

    def test_malformed_crossed_and_overflow_invalidate_instead_of_using_partial_delta(self):
        for changes in ([('bid','1.2','1')],[('bid','NaN','1')],[('bid','1','-1')]):
            self.generation=self.hub.begin(('ETH-BTC',));self.apply(packet(0));self.heartbeat()
            update=packet(1,kind='update',updates=[dict(side=s,price_level=p,new_quantity=q,event_time=iso(NOW)) for s,p,q in changes])
            with self.assertRaises(BookInvalid):self.apply(update)
            self.assertNotEqual(self.hub.view('ETH-BTC',at=NOW,mono=0).state,'HEALTHY')
        hub=BookHub(max_levels=2);gen=hub.begin(('ETH-BTC',));hub.apply(packet(0),generation=gen,at=NOW,mono=0)
        with self.assertRaises(BookInvalid):hub.apply(packet(1,kind='update',updates=[dict(side='bid',price_level='.8',new_quantity='1',event_time=iso(NOW))]),generation=gen,at=NOW,mono=0)

    def test_outward_grouping_and_quote_cumulative_use_actual_native_prices(self):
        self.apply(packet(0));self.heartbeat();view=self.hub.view('ETH-BTC',at=NOW,mono=0)
        rows=display_levels(view,tick=D('.1'),multiple=1,quote_amount=True)
        self.assertEqual(rows['asks'],((D('1.2'),D(6),D('10.4')),(D('1.1'),D('4.4'),D('4.4'))))
        grouped=display_levels(view,tick=D('.1'),multiple=5,quote_amount=True)
        self.assertEqual(grouped['asks'],((D('1.5'),D('10.4'),D('10.4')),))
        self.assertEqual(grouped['bids'][1][0],D('.5'))
        self.assertEqual(view.asks[0][0],D('1.1'))

    def test_six_products_include_four_eth_anchors_and_selected_cross_pair(self):
        for rotation in range(3):
            products=scheduled_products(rotation,'ADA-BTC');self.assertEqual(len(products),6)
            self.assertIn('ADA-BTC',products);self.assertTrue({'ADA-ETH','ETH-BTC','SOL-ETH','LINK-ETH'}<=set(products))

    def test_stream_processes_every_delta_before_render_and_closes_on_stop(self):
        done=threading.Event();hub=BookHub();stream=None
        messages=[json.dumps(packet(i,kind='snapshot' if i==0 else 'update',updates=[
            dict(side='bid',price_level='1',new_quantity=str(i+1),event_time=iso(NOW)),
            dict(side='offer',price_level='1.1',new_quantity='2',event_time=iso(NOW))])) for i in range(200)]
        class Socket:
            def __init__(self):self.sent=[];self.closed=False
            def send(self,value):self.sent.append(json.loads(value))
            def recv(self,timeout):
                if messages:return messages.pop(0)
                stream.stop();done.set();raise TimeoutError()
            def close(self):self.closed=True
        socket=Socket();stream=BookStream(hub,connect=lambda:socket,clock=lambda:NOW)
        stream.start('ETH-BTC');self.assertTrue(done.wait(3));stream.thread.join(3)
        self.assertFalse(stream.alive());self.assertTrue(socket.closed)
        self.assertEqual(hub.view('ETH-BTC',at=NOW).bids[0][1],D(200));self.assertEqual(len(socket.sent),2)


class BetaPrivacy(unittest.TestCase):
    def test_only_known_count_enum_flags_survive_and_unknown_fields_are_rejected(self):
        value=project(dict(blocked=False,state='ACTIVE',orders=2,balance='PRIVATE',order_id=OID),
            dict(orders=1,fee_amount='PRIVATE'),dict(state='HEALTHY',subscribed=6,healthy=5,price='PRIVATE'))
        validate(value);self.assertNotIn('PRIVATE',str(value));self.assertNotIn(OID,str(value))
        for path in ('live','manual','book'):
            bad=deepcopy(value);bad[path]['unexpected']='PRIVATE'
            with self.assertRaises(ValueError):validate(bad)
        bad=deepcopy(value);bad['live']['blocked']=1
        with self.assertRaises(ValueError):validate(bad)
