"""Fake read-only SDK with real Tk; arithmetic and opportunity remain independent."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal as D
import time
import unittest

from coincat_opportunity_policy import OpportunityConfig
from coincat_opportunity_venue import OpportunitySource
from coincat_monitor import capture,encode,validate
from coincat_spot_market import SpotReader
from coincat_spot_public import diagnostic
from coincat_monitor_server import HTML,JS
from offline_tests import test_spot_workspace as manual
from offline_tests.test_opportunity_policy import market
from offline_tests.test_spot_manual import Venue

class OpportunityVenue(Venue):
    def __init__(self,clock):super().__init__(clock);self.trade_calls=[];self.step=0;self.trades=[]
    def get_product(self,product_id,**kwargs):return deepcopy(market(self.clock,self.step)['rules'][product_id])
    def get_product_book(self,product_id,**kwargs):
        b=market(self.clock,self.step)['books'][product_id]
        return dict(pricebook=dict(product_id=product_id,bids=[dict(price=str(p),size=str(q)) for p,q in b['bids']],
            asks=[dict(price=str(p),size=str(q)) for p,q in b['asks']]))
    def get_market_trades(self,**kwargs):self.trade_calls.append(kwargs);return dict(trades=deepcopy(self.trades))

class OpportunitySourceTests(unittest.TestCase):
    def test_one_active_native_trade_get_stays_in_existing_budget_and_never_writes(self):
        from offline_tests.test_resumable_trial import Clock
        c=Clock();venue=OpportunityVenue(c);reader=SpotReader(venue,clock=c.wall,monotonic=c.monotonic,budget=None);source=OpportunitySource(reader)
        self.assertEqual(source.collect()['state'],'PRIMING');c.tick(10)
        venue.trades=[dict(trade_id='1',product_id='ETH-BTC',price='.03',size='.01',time=datetime.fromtimestamp(c.wall(),timezone.utc).isoformat(),side='SELL')]
        result=source.collect('ETH-BTC');self.assertEqual(result['market_trades']['pair'],'ETH-BTC')
        self.assertEqual(venue.trade_calls,[dict(product_id='ETH-BTC',limit=100)]);self.assertLessEqual(reader.calls,16)
        self.assertEqual(venue.posts,[]);self.assertEqual(venue.cancels,[])
        with self.assertRaises(BetaBlocked):source.collect('BTC-USD')

from coincat_beta_store import BetaBlocked

class OpportunityWorkspace(unittest.TestCase):
    setUp=manual.ManualWorkspace.setUp
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump
    connect=manual.ManualWorkspace.connect
    resize=manual.ManualWorkspace.resize
    def reads(self):
        venue=OpportunityVenue(self.clock);self.venue.get_product=venue.get_product;self.venue.get_product_book=venue.get_product_book
        self.venue.get_market_trades=venue.get_market_trades;return venue
    def begin(self):
        venue=self.reads();self.connect();self.app.open_opportunity();self.app.start_opportunity()
        self.pump(lambda:not self.app.busy and self.app.opportunity.store is None and self.app.opportunity.reason!='START_OPPORTUNITY_SHADOW')
        self.app.opportunity_due=0
        self.pump(lambda:self.app.opportunity.store is not None and not self.app.busy)
        return venue
    def test_new_policy_window_keeps_native_arithmetic_controls_and_real_gate_intact(self):
        self.app.open_assumed();native=self.app.assumed_window;self.app.open_opportunity()
        self.assertIs(self.app.assumed_window,native);self.assertTrue(native.root.winfo_exists())
        self.assertEqual(native.buy_price.get(),'ASK');self.assertEqual(len(self.app.tabs.tabs()),7)
        self.assertTrue(all(p.interval.get()=='1h' for p in self.app.panels.values()))
        self.assertTrue(self.app.blocked.get());self.assertFalse(self.app.opportunity.running);self.assertFalse(self.app.assumed.running)
    def test_worker_warms_fourteen_directions_without_fabricated_fills_or_actual_orders(self):
        self.begin();self.app.opportunity_window.render();s=self.app.opportunity.state()
        self.assertEqual(s['metrics']['direction_checks'],14);self.assertEqual(len(self.app.opportunity_window.decisions.get_children()),14)
        self.assertEqual(s['metrics']['orders'],0);self.assertEqual(s['wallet'],s['original'])
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
        self.assertIsNone(self.app.assumed.state());self.assertEqual(self.app.engine.state()['orders'],{})
    def test_shared_wave_does_not_mix_arithmetic_fills_into_opportunity_policy(self):
        self.reads();self.connect();self.app.open_assumed();self.app.start_assumed('BID')
        self.pump(lambda:not self.app.busy and bool(self.app.assumed.rows));self.app.assumed_due=0
        self.pump(lambda:self.app.assumed.state() is not None and not self.app.busy)
        self.app.open_opportunity();self.app.start_opportunity();self.app.opportunity_due=0
        self.pump(lambda:self.app.opportunity.store is not None and not self.app.busy)
        self.assertGreater(self.app.assumed.state()['orders'],0);self.assertEqual(self.app.opportunity.state()['metrics']['fill_events'],0)
        self.assertEqual(self.app.opportunity.state()['wallet'],self.app.opportunity.state()['original'])
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_diagnostics_monitor_expose_only_separate_policy_states_counts_and_uncertainty(self):
        self.begin();self.app.opportunity_public=self.app.opportunity.public()
        snapshot=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall());raw=encode(snapshot).decode();report=diagnostic(self.app)
        self.assertIn('opportunity_shadow',snapshot);self.assertIn('Opportunity shadow policy',report)
        self.assertFalse(snapshot['opportunity_shadow']['live_permission']);self.assertEqual(snapshot['assumed_fill']['orders'],0)
        for secret in ('OPP-',self.app.opportunity.state()['trial_id'],'seed_marks','estimated_future_exit_cost_usd','projected_advantage_usd'):
            self.assertNotIn(secret,raw);self.assertNotIn(secret,report)
        for key in ('wallet','native_price','fee_currency','order_id','projected_advantage_usd'):
            bad=deepcopy(snapshot);bad['opportunity_shadow'][key]='private'
            with self.subTest(key=key),self.assertRaises(ValueError):validate(bad)
        older=deepcopy(snapshot);del older['opportunity_shadow'];validate(older)
        self.assertIn('opportunity_section',HTML);self.assertIn('fills NOT CALIBRATED',JS)
    def test_sizing_policy_freezes_after_start_and_pause_does_not_touch_actual_permissions(self):
        self.begin();window=self.app.opportunity_window;window.render()
        self.assertTrue(all(str(w.cget('state'))=='readonly' for w in window.settings_inputs))
        self.app.pause_opportunity();self.assertFalse(self.app.opportunity.running);self.assertFalse(self.app.opportunity.store.clock['wanted'])
        self.assertTrue(self.app.blocked.get());self.assertIn('Opportunity shadow',self.app.tray_status()[0])
    def test_new_policy_has_no_live_dispatch_even_when_manual_block_is_off(self):
        self.app.engine.set_blocked(False);self.app.blocked.set(False);self.begin()
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[]);self.assertEqual(self.app.engine.state()['orders'],{})
