"""Fictional native one-leg fills; no SDK calls or real-account funding."""
from contextlib import closing
from copy import deepcopy
from decimal import Decimal as D,ROUND_FLOOR
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from coincat_assumed_math import initial_state,plan,fill_record,apply_record,marked_performance,rounded
from coincat_assumed_store import AssumedStore,query
from coincat_assumed_trader import AssumedTrader
from coincat_assumed_public import validate as validate_public
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_order_services import native_fill_changes
from coincat_spot_market import SpotReader
from coincat_shadow_source import ShadowMarketSource
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from coincat_trial_clock import TARGET_NS,NS
from offline_tests.test_resumable_trial import Clock,frame
from offline_tests.test_spot_manual import Venue
from offline_tests.trial_sqlite_resources import trial_sqlite_probe

def native_frame(clock):
    result=frame(clock)
    for pair,rule in result['rules'].items():
        base=pair.split('-')[0]
        inc,minimum={'ETH':('.000001','.0001'),'ADA':('.01','.1'),'LINK':('.01','.01'),'SOL':('.001','.001')}[base]
        rule.update(base_increment=inc,base_min_size=minimum,quote_min_size='.00000001',quote_increment='.00000001',price_increment='.00000001')
        book=result['books'][pair];mid=(book['bid']+book['ask'])/2;tick=D('.00000001');mid=rounded(mid,tick)
        book.update(bid=mid-tick,ask=mid+tick,bids=((mid-tick,D(10000)),),asks=((mid+tick,D(10000)),))
    return result

class NativeVenue(Venue):
    """Shared live-collector fake, including correct native price increments."""
    def get_product(self,product_id,**kwargs):return deepcopy(native_frame(self.clock)['rules'][product_id])
    def get_product_book(self,product_id,**kwargs):
        book=native_frame(self.clock)['books'][product_id]
        return dict(pricebook=dict(product_id=product_id,bids=[dict(price=str(book['bid']),size='10000')],asks=[dict(price=str(book['ask']),size='10000')]))

class NativeLegs(unittest.TestCase):
    def setUp(self):self.clock=Clock();self.f=native_frame(self.clock)
    @native_math
    def test_one_link_buy_at_ask_debits_one_taker_fee_in_eth_and_no_slippage(self):
        state=initial_state(self.f,self.clock.wall());before=deepcopy(state['wallet'])
        ticket=plan('LINK-ETH','BUY',self.f);record=fill_record(ticket,1);apply_record(state,record)
        self.assertEqual(ticket['size'],D('.01'));self.assertEqual(ticket['price'],self.f['books']['LINK-ETH']['ask'])
        self.assertEqual(ticket['fee_kind'],'TAKER');self.assertFalse(ticket['post_only']);self.assertEqual(ticket['fee_rate'],D('.009'))
        self.assertEqual(ticket['commission'],D('.0000004500009'));self.assertEqual(ticket['fee_currency'],'ETH')
        self.assertEqual(state['wallet']['ETH'],before['ETH']-ticket['size']*ticket['price']-ticket['commission'])
        self.assertEqual(state['wallet']['LINK'],before['LINK']+D('.01'));self.assertEqual(state['fees_native']['ETH'],ticket['commission'])
        self.assertEqual(ticket['slippage_fraction'],0);self.assertNotIn('target_price',ticket)
    @native_math
    def test_sell_at_ask_uses_one_maker_fee_without_charging_prior_buy_again(self):
        state=initial_state(self.f,self.clock.wall());buy=fill_record(plan('LINK-ETH','BUY',self.f),1);apply_record(state,buy)
        before=deepcopy(state['wallet']);fees=state['fees_native']['ETH']
        sell=fill_record(plan('LINK-ETH','SELL',self.f),2);apply_record(state,sell)
        self.assertEqual(sell['fee_kind'],'MAKER');self.assertTrue(sell['post_only']);self.assertEqual(sell['fee_rate'],D('.005'))
        self.assertEqual(sell['price'],self.f['books']['LINK-ETH']['ask']);self.assertEqual(sell['commission'],D('.0000002500005'))
        self.assertEqual(state['wallet']['ETH'],before['ETH']+sell['size']*sell['price']-sell['commission'])
        self.assertEqual(state['fees_native']['ETH'],fees+sell['commission'])
        self.assertLess(marked_performance(state,self.f,self.clock.wall())['difference_usd'],0)
    def test_bid_buy_is_a_distinct_maker_choice_and_btc_markets_use_btc_commission(self):
        maker=plan('ETH-BTC','BUY',self.f,'BID');taker=plan('ETH-BTC','BUY',self.f,'ASK')
        self.assertEqual(maker['price'],self.f['books']['ETH-BTC']['bid']);self.assertEqual(maker['fee_kind'],'MAKER')
        self.assertEqual(taker['price'],self.f['books']['ETH-BTC']['ask']);self.assertEqual(taker['fee_kind'],'TAKER')
        self.assertEqual(maker['fee_currency'],'BTC');self.assertEqual(taker['fee_currency'],'BTC')
        self.assertEqual(maker['commission'],D('.000000014999995'));self.assertEqual(taker['commission'],D('.000000027000009'))
    def test_minimum_quote_notional_and_base_increment_both_apply(self):
        self.f['rules']['LINK-ETH']['quote_min_size']='.00011'
        order=plan('LINK-ETH','BUY',self.f)
        self.assertEqual(order['size'],D('.03'));self.assertGreaterEqual(order['size']*order['price'],D('.00011'))
        self.assertEqual(order['size']%D('.01'),0)
    def test_each_of_fourteen_directions_has_native_rules_one_fee_and_zero_slippage(self):
        for pair in WATCH_PAIRS:
            for side in ('BUY','SELL'):
                with self.subTest(pair=pair,side=side):
                    t=plan(pair,side,self.f);self.assertEqual(t['price'],self.f['books'][pair]['ask'])
                    self.assertEqual(t['fee_currency'],pair.split('-')[1]);self.assertEqual(t['slippage_fraction'],0)
                    self.assertEqual(t['commission'],t['size']*t['price']*t['fee_rate'])
    def test_current_tier_and_price_replace_old_quotes_without_historical_fee_markup(self):
        first=plan('LINK-ETH','BUY',self.f)
        self.f['books']['LINK-ETH'].update(bid=D('.00399999'),ask=D('.00400001'))
        self.f['tier']['maker']=D('.006')
        sell=plan('LINK-ETH','SELL',self.f)
        self.assertEqual(sell['price'],D('.00400001'));self.assertEqual(sell['fee_rate'],D('.006'))
        self.assertLess(sell['price'],first['price'])
    def test_missing_fee_is_specific_and_no_hard_coded_point_five_or_point_nine_fallback(self):
        self.f['tier']['maker']=D('.0012');self.f['tier']['taker']=D('.0023')
        self.assertEqual(plan('LINK-ETH','BUY',self.f)['fee_rate'],D('.0023'))
        self.assertEqual(plan('LINK-ETH','SELL',self.f)['fee_rate'],D('.0012'))
        del self.f['tier']['taker']
        with self.assertRaisesRegex(BetaBlocked,'TAKER_FEE_REQUIRED'):plan('LINK-ETH','BUY',self.f)
    def test_zero_fee_remains_zero_and_no_extra_markup_is_introduced(self):
        self.f['tier'].update(maker=D(0),taker=D(0))
        for side in ('BUY','SELL'):
            t=plan('LINK-ETH',side,self.f);self.assertEqual(t['commission'],0);self.assertEqual(t['price'],self.f['books']['LINK-ETH']['ask'])
    @native_math
    def test_tiny_eth_quantity_stays_eth_and_only_its_btc_cost_gets_the_fee(self):
        rule=self.f['rules']['ETH-BTC'];rule.update(base_min_size='.00000001',base_increment='.00000001',quote_min_size='.000000000000000001')
        self.f['books']['ETH-BTC'].update(bid=D('.02939999'),ask=D('.0294'))
        ticket=plan('ETH-BTC','BUY',self.f)
        self.assertEqual(ticket['size'],D('.00000001'));self.assertNotEqual(ticket['size'],D('.00000001009'))
        self.assertEqual(ticket['commission'],D('.000000000002646'));self.assertEqual(ticket['fee_currency'],'BTC')
        self.assertEqual(ticket['size']*ticket['price']+ticket['commission'],D('.000000000296646'))
        self.assertEqual(ticket['fee_precision'],'UNVERIFIED_EXACT_RATE_MODEL');self.assertNotIn('fee_quantum',ticket)
    @native_math
    def test_size_slider_ranges_from_native_minimum_to_affordable_inventory_increments(self):
        wallet=initial_state(self.f,self.clock.wall())['wallet']
        minimum=plan('LINK-ETH','BUY',self.f,wallet=wallet)
        half=plan('LINK-ETH','BUY',self.f,wallet=wallet,percent=D(50))
        full=plan('LINK-ETH','BUY',self.f,wallet=wallet,percent=D(100))
        self.assertEqual(minimum['size'],D('.01'));self.assertLess(minimum['size'],half['size']);self.assertLess(half['size'],full['size'])
        self.assertEqual(full['size']%D('.01'),0);self.assertLessEqual(full['size']*full['price']+full['commission'],wallet['ETH'])
        self.assertGreater((full['size']+D('.01'))*full['price']*(1+D('.009')),wallet['ETH'])
        self.assertEqual(full['price'],minimum['price']);self.assertEqual(full['fee_kind'],minimum['fee_kind'])
    def test_native_exchange_maximum_still_bounds_the_slider_without_a_usd_gate(self):
        self.f['rules']['LINK-ETH']['base_max_size']='.07'
        t=plan('LINK-ETH','BUY',self.f,wallet=initial_state(self.f,self.clock.wall())['wallet'],percent=D(100))
        self.assertEqual(t['size'],D('.07'))

class FictionalPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=Clock();self.path=Path(self.tmp.name)/'assumed.sqlite3'
        self.e=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
    def review(self):self.e.review(native_frame(self.clock))
    @native_math
    def test_seed_is_once_only_one_hundred_usd_per_five_coins_and_not_actual_balances(self):
        self.e.start();f=native_frame(self.clock);f['account']['available']={a:D('999999') for a in WATCH_ASSETS};self.e.review(f)
        s=self.e.state();self.assertEqual(s['seed_usd_per_coin'],100);self.assertEqual(s['orders'],7)
        for asset in WATCH_ASSETS:self.assertLess(abs(s['original'][asset]*s['seed_marks'][asset]-100),D('.000000001'))
        original=deepcopy(s['original']);self.e.pause();self.e.start();self.clock.tick(10);self.review()
        self.assertEqual(self.e.state()['original'],original);self.assertEqual(self.e.state()['orders'],14)
    def test_shared_wallet_can_never_spend_the_same_source_twice(self):
        f=native_frame(self.clock)
        for pair in ('ADA-ETH','LINK-ETH','SOL-ETH'):f['rules'][pair]['quote_min_size']='.03'
        self.e.start();self.e.review(f);s=self.e.state()
        self.assertTrue(all(q>=0 for q in s['wallet'].values()))
        blocked=[r for r in self.e.rows if r['reason']=='INSUFFICIENT_SIMULATED_SOURCE_INCLUDING_NATIVE_FEE']
        self.assertTrue(blocked);self.assertNotEqual(s['wallet'],s['original'])
    def test_no_usd_turnover_attempt_or_session_expiry_gate_on_this_mode(self):
        self.e.start()
        for i in range(20):
            f=native_frame(self.clock);f['rules']['ETH-BTC']['base_min_size']='.01';self.e.review(f);self.clock.tick(10)
        s=self.e.state();self.assertEqual(s['orders'],140);self.assertEqual(s['waves'],20)
        self.assertNotIn('max_orders',s);self.assertNotIn('max_order_usd',s);self.assertNotIn('expires_at',s)
        self.assertEqual(s['buys'],70);self.assertEqual(s['sells'],70)
    def test_usd_mark_gap_after_seeding_does_not_block_native_order_arithmetic(self):
        self.e.start();self.review();self.clock.tick(10);f=native_frame(self.clock);del f['books']['ETH-USD'];self.e.review(f)
        self.assertEqual(self.e.state()['orders'],14);self.assertIsNone(self.e.view()['performance'])
    def test_stale_partial_or_duplicate_frames_and_pause_do_not_create_fills(self):
        self.e.start();self.review();saved=self.e.state();self.review();self.assertEqual(self.e.state(),saved)
        self.clock.tick(31);self.e.review(frame(Clock()));self.assertEqual(self.e.state(),saved)
        self.e.review(dict(state='PRIMING',at=self.clock.wall()));self.assertEqual(self.e.state(),saved)
        self.e.pause();self.clock.tick(10);self.review();self.assertEqual(self.e.state(),saved)
    def test_one_missing_market_blocks_that_market_and_keeps_specific_reason(self):
        self.e.start();f=native_frame(self.clock);del f['books']['LINK-BTC'];self.e.review(f)
        self.assertEqual(self.e.state()['orders'],6)
        row=next(r for r in self.e.rows if r['pair']=='LINK-BTC')
        self.assertEqual(row['state'],'WAITING');self.assertIn('BOOK_MISSING_OR_STALE',row['reason'])
    def test_restart_preserves_balances_fee_ids_seed_and_resumes_opt_in_without_downtime_fills(self):
        self.e.start();self.review();self.clock.tick(10);self.review();saved=self.e.state();orders=deepcopy(self.e.orders)
        self.clock.tick(36000);restored=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
        self.assertFalse(restored.load_error);self.assertTrue(restored.running);self.assertEqual(restored.state(),saved);self.assertEqual(restored.orders,orders)
        restored.start();restored.review(native_frame(self.clock));self.assertEqual(restored.state()['orders'],21)
        self.assertTrue(all(o['order_id'].startswith('SIM-') for o in restored.orders))
        self.assertEqual(len({o['order_id'] for o in restored.orders}),21)
    def test_buy_price_choice_frozen_for_saved_simulation(self):
        self.e.start('BID');self.review();self.e.pause()
        with self.assertRaisesRegex(BetaBlocked,'FROZEN'):self.e.start('ASK')
        self.assertEqual(self.e.state()['taker_orders'],0)
    def test_sizing_versions_change_only_future_orders_and_survive_audit_and_restart(self):
        self.e.start();self.review();old=deepcopy(self.e.orders);original=self.e.state()['original']
        values=deepcopy(self.e.state()['sizing']);values['ETH-BTC']=D(25);self.e.configure(values)
        self.assertEqual(self.e.state()['settings_version'],2);self.assertEqual(self.e.orders,old)
        self.e.configure(values);self.assertEqual(self.e.state()['settings_version'],2)
        self.clock.tick(10);self.review();new=next(o for o in self.e.orders[7:] if o['pair']=='ETH-BTC')
        self.assertEqual(new['settings_version'],2);self.assertEqual(new['allocation_percent'],25)
        self.assertGreater(new['size'],D('.0001'));self.assertEqual(self.e.orders[:7],old)
        self.assertEqual(self.e.state()['original'],original)
        restored=AssumedStore(self.path);self.assertEqual(restored.state(),self.e.state())
    def test_stale_or_missing_authenticated_fees_wait_without_fallback_or_fake_fills(self):
        self.e.start();f=native_frame(self.clock);f['tier']['at']-=3601;self.e.review(f)
        self.assertEqual(self.e.state()['orders'],0);self.assertEqual(self.e.public()['state'],'WAITING')
        self.assertTrue(all('TAKER_FEE_REQUIRED' in r['reason'] for r in self.e.rows))
    def test_read_only_shared_collector_calls_no_create_cancel_or_real_fill_endpoint(self):
        venue=NativeVenue(self.clock);reader=SpotReader(venue,clock=self.clock.wall,monotonic=self.clock.monotonic,budget=None)
        source=ShadowMarketSource(reader);self.e.start();self.e.review(source.collect());self.assertIsNone(self.e.state())
        self.clock.tick(10);self.e.review(source.collect())
        self.assertEqual(self.e.state()['orders'],7);self.assertEqual(venue.posts,[]);self.assertEqual(venue.cancels,[])
    def test_public_counts_are_explicit_assumptions_not_trial_or_profit_evidence(self):
        self.e.start();self.review();public=validate_public(self.e.public())
        self.assertEqual(public['orders'],7);self.assertFalse(public['live_permission'])
        self.assertEqual(public['fill_evidence'],'ASSUMED_NOT_OBSERVED');self.assertEqual(public['profit_evidence'],'NOT_ESTABLISHED')
        for key,value in (('wallet',{}),('fee_currency','ETH'),('order_id','SIM-private'),('portfolio_usd',500)):
            bad=dict(public);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_public(bad)

class JournalRecovery(unittest.TestCase):
    def setUp(self):
        self.probe=self.enterContext(trial_sqlite_probe());self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'assumed.sqlite3';self.addCleanup(self.probe.assert_released,self,self.path)
        self.clock=Clock();self.e=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns);self.e.start();self.e.review(native_frame(self.clock))
    def test_successful_and_failed_database_owners_release_handles_before_native_cleanup(self):
        other=AssumedStore(self.path);self.assertEqual(other.state(),self.e.state())
        with closing(sqlite3.connect(self.path)) as db,db,closing(db.cursor()) as cursor:cursor.execute('PRAGMA application_id=1')
        before=self.path.read_bytes()
        with self.assertRaisesRegex(BetaBlocked,'WRONG_ASSUMED'):AssumedStore(self.path)
        self.assertTrue(AssumedTrader(self.path).load_error);self.assertEqual(self.path.read_bytes(),before)
    def test_corrupt_missing_checkpoint_or_order_evidence_preserved_without_reset(self):
        original=self.path.read_bytes()
        for sql in ("UPDATE assumed_state SET digest='bad'","DELETE FROM assumed_state","UPDATE assumed_orders SET digest='bad'"):
            self.path.write_bytes(original)
            with closing(sqlite3.connect(self.path)) as db,db,closing(db.cursor()) as cursor:cursor.execute(sql)
            broken=self.path.read_bytes();e=AssumedTrader(self.path,clock=self.clock.wall)
            self.assertTrue(e.load_error);self.assertEqual(self.path.read_bytes(),broken)
            with self.assertRaises(BetaBlocked):e.start()
    def test_failed_transaction_rolls_back_without_inventing_orders_or_leaking_handles(self):
        before=self.e.state();self.clock.tick(10);record=fill_record(plan('LINK-ETH','SELL',native_frame(self.clock)),2)
        real_query=query
        def failing(db,sql,args=(),**kwargs):
            if sql.startswith('UPDATE assumed_state'):raise KeyboardInterrupt('synthetic interrupted commit')
            return real_query(db,sql,args,**kwargs)
        with patch('coincat_assumed_store.query',side_effect=failing),self.assertRaises(KeyboardInterrupt):self.e.store.append([record],at=self.clock.wall())
        self.assertEqual(self.e.state(),before);self.assertEqual(AssumedStore(self.path).state(),before)
    def test_stale_writer_cannot_overwrite_committed_wallet(self):
        other=AssumedStore(self.path);self.clock.tick(10);self.e.review(native_frame(self.clock));saved=self.e.state()
        record=fill_record(plan('LINK-ETH','SELL',native_frame(self.clock)),2)
        with self.assertRaisesRegex(BetaBlocked,'STALE_ASSUMED_WRITER'):other.append([record],at=self.clock.wall())
        self.assertEqual(AssumedStore(self.path).state(),saved)
    def test_clock_and_sizing_history_corruption_release_handles_and_never_reset(self):
        original=self.path.read_bytes()
        for sql in ("UPDATE assumed_clock SET digest='bad'","DELETE FROM assumed_clock","UPDATE assumed_settings SET digest='bad'"):
            self.path.write_bytes(original)
            with closing(sqlite3.connect(self.path)) as db,db,closing(db.cursor()) as cursor:cursor.execute(sql)
            broken=self.path.read_bytes();e=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
            self.assertTrue(e.load_error);self.assertEqual(self.path.read_bytes(),broken)
    def test_failed_initialization_releases_its_connection_without_deleting_partial_evidence(self):
        path=Path(self.tmp.name)/'failed.sqlite3';seed=initial_state(native_frame(self.clock),self.clock.wall());real_query=query
        def failing(db,sql,args=(),**kwargs):
            if sql.startswith('CREATE TABLE assumed_orders'):raise sqlite3.OperationalError('synthetic initialization failure')
            return real_query(db,sql,args,**kwargs)
        with patch('coincat_assumed_store.query',side_effect=failing),self.assertRaises(sqlite3.OperationalError):AssumedStore(path,initial=seed)
        self.assertTrue(path.exists());broken=path.read_bytes();self.assertTrue(AssumedTrader(path).load_error);self.assertEqual(path.read_bytes(),broken)
        self.probe.assert_released(self,path)

class AssumedTrialClock(unittest.TestCase):
    setUp=FictionalPortfolio.setUp
    review=FictionalPortfolio.review
    def start(self):self.e.start();self.review()
    def test_valid_time_uses_monotonic_lease_and_pause_time_does_not_count(self):
        self.start();self.clock.tick(10);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],10)
        self.e.pause();saved=self.e.state();self.clock.tick(20);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],10);self.assertEqual(self.e.progress()['paused_s'],20)
        self.assertEqual(self.e.state(),saved)
    def test_partial_coverage_and_missing_usd_marks_allow_native_math_but_not_full_trial_hours(self):
        self.start();self.clock.tick(10);f=native_frame(self.clock);del f['books']['ETH-USD'];self.e.review(f)
        seconds=self.e.progress()['valid_seconds'];orders=self.e.state()['orders'];self.clock.tick(10);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],seconds);self.assertEqual(orders,14)
        self.assertGreater(self.e.progress()['partial_s'],0)
    def test_lease_expiry_and_suspend_do_not_credit_unwatched_hours(self):
        self.start();self.clock.tick(26);self.e.heartbeat(persist=True);self.assertEqual(self.e.progress()['valid_seconds'],0)
        self.e.review(native_frame(self.clock));before=self.e.progress()['valid_seconds']
        self.clock.at+=3600;self.clock.mono+=NS;self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],before);self.assertTrue(self.e.store.clock['calendar_uncertain'])
    def test_duplicate_cached_frame_cannot_renew_the_valid_observation_lease(self):
        self.start();cached=native_frame(self.clock);self.clock.tick(20);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],20);self.e.review(cached)
        self.clock.tick(6);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],20);self.assertEqual(self.e.state()['orders'],7)
    def test_restart_keeps_hours_and_original_funding_and_waits_for_fresh_coverage(self):
        self.start();self.clock.tick(10);self.e.heartbeat(persist=True);saved=self.e.state();self.e.shutdown();self.clock.tick(3600)
        restored=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
        self.assertTrue(restored.running);self.assertEqual(restored.progress()['valid_seconds'],10);self.assertEqual(restored.state(),saved)
        self.clock.tick(10);restored.heartbeat();self.assertEqual(restored.progress()['valid_seconds'],10)
        self.assertGreaterEqual(restored.progress()['downtime_s'],3600)
        restored.pause();again=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
        self.assertFalse(again.running);self.assertEqual(again.progress()['valid_seconds'],10)
    def test_completion_freezes_trial_and_report_even_after_restart_and_new_prices(self):
        self.start();self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock()
        self.clock.tick(10);self.e.heartbeat();self.assertEqual(self.e.public()['state'],'COMPLETE')
        saved=self.e.state();report=deepcopy(self.e.store.completion)
        self.assertEqual(self.e.progress()['valid_seconds'],168*3600);self.assertFalse(self.e.running)
        with self.assertRaisesRegex(BetaBlocked,'FROZEN'):self.e.start()
        with self.assertRaisesRegex(BetaBlocked,'FROZEN'):self.e.configure(saved['sizing'])
        self.clock.tick(36000);self.e.review(native_frame(self.clock));self.assertEqual(self.e.state(),saved)
        restored=AssumedTrader(self.path,clock=self.clock.wall,monotonic_ns=self.clock.ns)
        self.assertFalse(restored.load_error);self.assertEqual(restored.store.completion,report);self.assertEqual(restored.state(),saved)
        self.assertEqual(restored.view()['performance'],report['performance'])
