"""Real Tk assumed-fill controls; fake GETs and quantity-free monitor exports."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

from coincat_assumed_trader import AssumedTrader
from coincat_monitor import capture,encode,validate
from coincat_monitor_server import HTML,JS
from coincat_portfolio_policy import PortfolioConfig
from coincat_spot_public import diagnostic
from offline_tests import test_spot_workspace as manual
from offline_tests.test_assumed_trader import NativeVenue,native_frame

class AssumedWorkspace(unittest.TestCase):
    setUp=manual.ManualWorkspace.setUp
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump
    connect=manual.ManualWorkspace.connect
    resize=manual.ManualWorkspace.resize
    def native_reads(self):
        venue=NativeVenue(self.clock)
        self.venue.get_product=venue.get_product;self.venue.get_product_book=venue.get_product_book
        return venue
    def first_wave(self):
        self.native_reads();self.connect();self.app.open_assumed();self.app.start_assumed()
        self.pump(lambda:not self.app.busy and bool(self.app.assumed.rows))
        self.app.assumed_due=0
        self.pump(lambda:self.app.assumed.state() is not None and self.app.assumed.state()['orders']==7 and not self.app.busy)
    def test_main_entry_has_no_simulator_spending_fields_and_preserves_real_gate(self):
        limits=deepcopy(self.app.engine.state()['limits']);self.app.open_assumed();window=self.app.assumed_window
        self.assertIn('Native one-leg trial',self.app.assumed_badge.cget('text'));self.assertEqual(window.buy_price.get(),'ASK')
        self.assertFalse(hasattr(window,'fields'));self.assertEqual(len(self.app.tabs.tabs()),7)
        self.assertTrue(self.app.blocked.get());self.assertFalse(self.app.assumed.running)
        self.assertEqual(self.app.engine.state()['limits'],limits);self.assertIsNone(self.app.shadow.state())
    def test_worker_runs_seven_minimum_native_orders_then_updates_all_views_without_posts(self):
        self.first_wave();self.app.assumed_window.render();s=self.app.assumed.state();window=self.app.assumed_window
        self.assertEqual(s['orders'],7);self.assertEqual(s['taker_orders'],7)
        self.assertEqual(len(window.markets.get_children()),7);self.assertEqual(len(window.holdings.get_children()),5)
        self.assertEqual(len(window.orders.get_children()),7);self.assertIn('7 assumed fills',window.summary.get())
        self.assertTrue(all(o['price']==o['ask'] and o['slippage_fraction']==0 for o in self.app.assumed.orders))
        self.assertEqual(str(window.buy_box.cget('state')),'disabled');self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
        self.assertIsNone(self.app.shadow.state());self.assertEqual(self.app.engine.state()['orders'],{})
    def test_slider_applies_future_version_and_retains_previous_assumed_fills(self):
        self.first_wave();window=self.app.assumed_window;old=deepcopy(self.app.assumed.orders)
        window.sizing_vars['ETH-BTC'].set(25);window.slider_changed();self.assertTrue(window.dirty)
        window.apply_sizes();self.pump(lambda:not self.app.busy and self.app.assumed.state()['settings_version']==2)
        self.assertEqual(self.app.assumed.orders,old);self.assertEqual(self.app.assumed.state()['sizing']['ETH-BTC'],25)
        self.clock.tick(10);self.app.assumed_due=0
        self.pump(lambda:self.app.assumed.state()['orders']==14 and not self.app.busy)
        order=next(o for o in self.app.assumed.orders[7:] if o['pair']=='ETH-BTC')
        self.assertEqual(order['allocation_percent'],25);self.assertEqual(order['settings_version'],2)
        self.assertGreater(order['size'],order['min_size']);self.assertEqual(self.app.assumed.orders[:7],old)
        self.assertEqual(self.venue.posts,[])
    def test_assumed_trader_has_no_submit_authority_even_if_manual_switch_is_off(self):
        self.app.engine.set_blocked(False);self.app.blocked.set(False);self.first_wave()
        self.assertFalse(self.app.engine.block.is_set());self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
        self.assertEqual(self.app.engine.state()['orders'],{})
    def test_tray_and_close_control_the_new_trial_without_changing_manual_permissions(self):
        self.first_wave();self.assertIn('One-leg assumed trial',self.app.tray_status()[0]);self.app.toggle_observation()
        self.assertFalse(self.app.assumed.running);self.assertFalse(self.app.assumed.store.clock['wanted'])
        self.app.toggle_observation();self.assertTrue(self.app.assumed.running);self.assertTrue(self.app.blocked.get())
        self.app.tray.available=False;self.app.window_close();self.assertFalse(self.app.closing)
        self.assertTrue(self.app.assumed_window.root.winfo_exists());self.assertEqual(self.venue.posts,[])
    def test_pause_and_restart_do_not_reseed_or_replay_offline_orders(self):
        self.first_wave();self.app.pause_assumed();saved=self.app.assumed.state();self.clock.tick(1000)
        self.app.assumed_due=0;self.root.update();self.assertEqual(self.app.assumed.state(),saved)
        restored=AssumedTrader(self.app.assumed.path,clock=self.clock.wall)
        self.assertEqual(restored.state(),saved);self.assertFalse(restored.running)
        self.assertEqual(self.venue.posts,[])
    def test_account_balance_outage_does_not_become_a_fictional_funding_requirement(self):
        self.native_reads();self.venue.get_accounts=lambda **kwargs:(_ for _ in ()).throw(TimeoutError('synthetic account outage'))
        self.app.start_assumed()
        self.pump(lambda:not self.app.busy and bool(self.app.assumed.rows))
        self.app.assumed_due=0
        self.pump(lambda:self.app.assumed.state() is not None and self.app.assumed.state()['orders']==7 and not self.app.busy)
        self.assertFalse(self.app.connected);self.assertEqual(self.app.assumed.state()['orders'],7)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_transient_native_read_error_waits_and_retries_without_minting_fills(self):
        self.first_wave();saved=self.app.assumed.state();self.clock.tick(10)
        original=self.app.shadow_source.collect
        with patch.object(self.app.shadow_source,'collect',side_effect=TimeoutError('PRIVATE_READ_ERROR')):
            self.app.assumed_due=0
            self.pump(lambda:self.app.assumed.reason=='NATIVE_FEED_UNAVAILABLE_WAITING_FOR_FRESH_GETS' and not self.app.busy)
        self.assertTrue(self.app.assumed.running);self.assertEqual(self.app.assumed.state(),saved)
        self.app.assumed_due=0
        self.pump(lambda:self.app.assumed.state()['orders']==14 and not self.app.busy)
        self.assertEqual(self.venue.posts,[])
    def test_one_leg_fees_visible_and_old_trial_fill_evidence_remains_separate(self):
        self.first_wave();self.app.pause_assumed();self.app.start_trial(PortfolioConfig());self.pump(lambda:not self.app.busy)
        self.app.pause_trial();before=self.app.shadow.state();self.clock.tick(10)
        self.app.assumed.start();self.app.assumed.review(native_frame(self.clock));self.app.assumed.pause()
        self.assertEqual(self.app.assumed.state()['orders'],14);self.assertEqual(self.app.assumed.state()['maker_orders'],7)
        self.assertEqual(self.app.shadow.state(),before);self.assertEqual(self.app.shadow.state()['fills'],{})
        self.app.assumed_window.render();text=self.app.assumed_window.performance.get()
        self.assertIn('Prior trial records remain separate',text);self.assertIn('difference',text)
    def test_monitor_and_diagnostics_show_only_labeled_assumed_counts(self):
        self.first_wave();self.app.pause_assumed();self.app.assumed_public=self.app.assumed.public()
        snap=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall());text=encode(snap).decode();report=diagnostic(self.app)
        self.assertEqual(snap['assumed_fill']['orders'],7);self.assertEqual(snap['shadow_trial']['fills'],0)
        self.assertFalse(snap['assumed_fill']['live_permission']);self.assertIn('ASSUMED_NOT_OBSERVED',report)
        for private in ('SIM-',self.app.assumed.state()['sandbox_id'],'seed_marks','fees_native','wallet'):
            self.assertNotIn(private,text);self.assertNotIn(private,report)
        for key in ('portfolio_usd','fee_currency','order_id','native_price'):
            bad=deepcopy(snap);bad['assumed_fill'][key]='private'
            with self.subTest(key=key),self.assertRaises(ValueError):validate(bad)
        older=deepcopy(snap);del older['assumed_fill'];validate(older)
        self.assertIn('assumed_section',HTML);self.assertIn('NOT observed fills',JS);self.assertIn('Current assumed-fill status unavailable',JS)
    def test_minimum_window_and_close_stop_simulator_and_leave_trial_and_actual_journals_intact(self):
        self.first_wave();self.resize(1040,780);self.app.assumed_window.root.geometry('920x720');self.app.assumed_window.tabs.select(self.app.assumed_window.portfolio_page);self.root.update()
        self.assertTrue(self.app.assumed_window.orders.winfo_ismapped());saved=self.app.assumed.state()
        self.app.close();self.pump(lambda:self.app.closed);self.assertFalse(self.app.assumed.running)
        self.assertEqual(AssumedTrader(self.app.assumed.path,clock=self.clock.wall).state(),saved)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
