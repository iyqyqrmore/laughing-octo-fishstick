from copy import deepcopy
from unittest.mock import MagicMock,patch
import json,time
import unittest
from types import SimpleNamespace
from coincat_monitor import capture,encode,validate
from coincat_spot_public import diagnostic
from coincat_multi_policy import MultiConfig
from coincat_order_explanation_ui import ExplanationWindow
from offline_tests import test_spot_workspace as manual
from offline_tests.test_intelligent_source import IntelligentVenue,HistoryEstimate
from offline_tests.multi_fixtures import Clock,predictions,observed

class Bundle:
    def __init__(self,clock,forecasts):self.clock=clock;self.forecasts=forecasts;self.backfill=SimpleNamespace(reviewed=lambda g:False)
    def estimate(self,at,baseline=None):
        result=deepcopy(self.forecasts)
        for f in result.values():
            if f['state']=='READY':f.update(decision_at=at,forecast_end_at=at+f['horizon_s'])
        return result

class MultiWorkspace(unittest.TestCase):
    def setUp(self):
        # Native UI and direct-label fixtures must share a decision clock. A
        # stale forecast is a separate case, not accidental default coverage.
        with patch.object(manual,'Clock',Clock):manual.ManualWorkspace.setUp(self)
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump
    connect=manual.ManualWorkspace.connect
    @classmethod
    def setUpClass(cls):cls.forecasts=predictions(Clock())
    def begin(self):
        f=observed(self.clock,self.forecasts);venue=IntelligentVenue(self.clock,f)
        self.venue.get_product=venue.get_product;self.venue.get_product_book=venue.get_product_book;self.venue.get_market_trades=venue.get_market_trades
        self.venue.available=deepcopy(f['account']['available']);self.app.intelligent_source.history=HistoryEstimate(self.clock,f)
        self.app.intelligent_source.forecast_bundle=Bundle(self.clock,self.forecasts)
        self.app.history_source.collect=MagicMock(return_value=dict(state='READY'));self.connect();self.app.open_intelligent()
        w=self.app.intelligent_window;w.policy.set('Multi-horizon');w.switch_policy();w.start()
        self.pump(lambda:self.app.multihorizon.store is not None and not self.app.busy);w.render();return w
    def test_start_is_separate_and_old_24h_trial_remains_unchanged(self):
        w=self.begin();self.assertIsNone(self.app.intelligent.state());s=self.app.multihorizon.state()
        self.assertEqual(s['strategy'],'MULTI_HORIZON_ONE_LEG_V1');self.assertEqual(len(w.decisions.get_children()),14);self.assertEqual(len(w.horizon_table.get_children()),84)
        public=self.app.multihorizon.public()
        self.assertEqual(public['horizons']['M5']['state'],'READY');self.assertEqual(public['horizons']['H24']['state'],'HOLD')
        self.assertGreater(public['orders'],0);self.assertIn('supported horizons IMMEDIATE',w.status.get())
        self.assertEqual(self.app.engine.state()['orders'],{});self.assertTrue(self.app.blocked.get())
        original=deepcopy(s['original']);w.policy.set('24-hour baseline');w.switch_policy()
        self.assertIsNone(self.app.intelligent.state());self.assertEqual(self.app.multihorizon.state()['original'],original)
        self.assertTrue(self.app.multihorizon.running);self.assertIn('NOT PAIRED',w.comparison.get())
    def test_history_progress_and_horizon_reasons_have_their_own_visible_views(self):
        w=self.begin();w.tabs.select(5);w.research_tabs.select(2);self.root.update()
        self.assertEqual(len(w.history_table.get_children()),15);self.assertIn('last success',w.history_status.get())
        self.assertIn('H24',str([w.horizon_table.item(i,'values') for i in w.horizon_table.get_children()]))
        self.assertIn('FORECAST_HISTORY_INSUFFICIENT',str([w.horizon_table.item(i,'values') for i in w.horizon_table.get_children()]))
    def test_order_preview_has_no_mutation_path_and_historical_economics_stays_unknown(self):
        self.begin();before=self.app.multihorizon.state();w=ExplanationWindow(self.app)
        w.use_minimum();self.assertTrue(w.budget.get());w.preview();self.assertIn('NATIVE_RULES_AND_FUNDS_PASS',w.answers.get())
        self.assertIn('SHADOW ONLY',w.answers.get());self.assertEqual(len(w.table.get_children()),6)
        w.historical();self.assertIn('UNKNOWN_ORIGINAL',w.answers.get());self.assertIn('Actual unrounded commission and exact settlement UNKNOWN',w.construction.get())
        self.assertEqual(self.app.multihorizon.state(),before);self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_minimum_window_keeps_progress_order_explanation_and_footer_accessible(self):
        main=self.begin();w=ExplanationWindow(self.app);w.root.geometry('1040x740');self.pump(lambda:w.root.winfo_width()==1040)
        w.use_minimum();w.preview();self.root.update()
        for widget in (w.budget_entry,w.price_entry,w.table,w.footer):
            self.assertTrue(widget.winfo_ismapped());self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),w.root.winfo_rootx()+1040)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),w.root.winfo_rooty()+740)
        w.root.destroy();main.root.geometry('1040x740');self.pump(lambda:main.root.winfo_width()==1040)
        main.tabs.select(5);main.research_tabs.select(2);self.root.update()
        self.assertTrue(main.history_table.winfo_ismapped());self.assertGreater(main.history_table.winfo_height(),50)
        self.assertLessEqual(main.footer.winfo_rooty()+main.footer.winfo_height(),main.root.winfo_rooty()+740)
    def test_redacted_snapshot_has_both_identities_horizon_counts_and_no_financial_values(self):
        self.begin();self.app.multihorizon_public=self.app.multihorizon.public();snap=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall())
        validate(snap);raw=encode(snap).decode();report=diagnostic(self.app)
        self.assertEqual(snap['intelligent_shadow']['state'],'OFF');self.assertEqual(snap['multihorizon_shadow']['direction_checks'],14)
        self.assertIn('Historical collector',report);self.assertIn('M5',report);self.assertIn('H24',report)
        for secret in (self.app.multihorizon.state()['trial_id'],'source_budget','fee_currency','forecast_inputs','OPP-'):
            self.assertNotIn(secret,raw);self.assertNotIn(secret,report)
        older=deepcopy(snap);del older['history_backfill'];del older['multihorizon_shadow'];validate(older)
        bad=deepcopy(snap);bad['multihorizon_shadow']['horizons']['M5']['wallet']='PRIVATE'
        with self.assertRaises(ValueError):validate(bad)
    def test_manual_off_does_not_enable_automatic_money_and_pause_cancels_only_local_order(self):
        self.app.engine.set_blocked(False);self.app.blocked.set(False);self.begin();self.app.pause_intelligent()
        self.assertFalse(self.app.multihorizon.running);self.assertFalse(self.app.engine.block.is_set())
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_overdue_history_gets_a_bounded_slot_ahead_of_display_refresh(self):
        self.app.connected=True;self.app.open_intelligent();self.app.forecast_due=0;self.app.refresh_due=0
        with patch.object(self.app.history_source,'overdue',return_value=True),patch.object(self.app,'work',return_value=False) as work:
            self.app.tick()
        self.assertEqual(work.call_args.args[0],'forecast_history')
