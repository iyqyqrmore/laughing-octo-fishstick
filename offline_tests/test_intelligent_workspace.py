"""Real Tk v1.05 controls, no private data or exchange requests."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch,MagicMock
import hashlib
import sqlite3
import time
import unittest
from coincat_archive_ui import read_archive
from coincat_beta_store import BetaBlocked,pack,digest
from coincat_intelligent_policy import IntelligentConfig
from coincat_monitor import capture,encode,validate
from coincat_spot_public import diagnostic
from coincat_windows_lifecycle import NativeSessionHook,WindowsLifecycle,without_minimize
from coincat_version import DISPLAY
from offline_tests import test_spot_workspace as manual
from offline_tests.test_intelligent_source import IntelligentVenue,HistoryEstimate
from offline_tests.intelligent_fixtures import frame

class IntelligentWorkspace(unittest.TestCase):
    setUp=manual.ManualWorkspace.setUp
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump
    connect=manual.ManualWorkspace.connect
    def begin(self):
        template=frame(self.clock);venue=IntelligentVenue(self.clock,template)
        self.venue.get_product=venue.get_product;self.venue.get_product_book=venue.get_product_book
        self.venue.get_market_trades=venue.get_market_trades;self.venue.available=deepcopy(template['account']['available'])
        self.app.reader.budget=None;self.app.intelligent_source.history=HistoryEstimate(self.clock,template)
        self.app.history_source.collect=MagicMock(return_value=dict(state='READY'))
        self.connect();self.app.open_intelligent();self.app.start_intelligent()
        self.pump(lambda:self.app.intelligent.store is not None and not self.app.busy)
        self.app.intelligent_window.render();return self.app.intelligent_window
    def test_default_workspace_has_one_shadow_controller_and_keeps_manual_tabs_and_one_hour_charts(self):
        self.app.open_intelligent();w=self.app.intelligent_window
        self.assertIn(DISPLAY,w.root.title());self.assertEqual(w.funding.get(),'ACCOUNT_AVAILABLE')
        for name in ('shadow','assumed','opportunity','tray','market_box','star'):
            self.assertFalse(hasattr(self.app,name))
        self.assertEqual(len(self.app.tabs.tabs()),7);self.assertTrue(all(p.interval.get()=='1h' for p in self.app.panels.values()))
        self.assertTrue(self.app.blocked.get());self.assertIsNone(self.app.intelligent.state());self.assertFalse(self.app.intelligent.running)
        self.assertFalse(self.root.bind('<Unmap>'));self.assertEqual(self.venue.posts,[])
    def test_get_only_worker_seeds_available_once_shows_all_fourteen_and_freezes_settings(self):
        w=self.begin();s=self.app.intelligent.state()
        self.assertEqual(s['funding_mode'],'ACCOUNT_AVAILABLE');self.assertEqual(s['original'],self.venue.available)
        self.assertEqual(len(w.decisions.get_children()),14);self.assertEqual(s['metrics']['direction_checks'],14)
        self.assertTrue(all(str(x.cget('state'))=='readonly' for x in w.inputs));self.assertEqual(str(w.funding_box.cget('state')),'disabled')
        self.assertIn('maker',w.best.get());self.assertIn('UNVALIDATED',w.model.get());self.assertEqual(s['metrics']['fill_events'],0)
        with self.assertRaises(BetaBlocked):self.app.intelligent.start(replace(IntelligentConfig(),max_source_fraction='.2'))
        self.app.pause_intelligent();w.render();self.assertFalse(self.app.intelligent.running);self.assertTrue(self.app.blocked.get())
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_manual_block_off_does_not_authorize_shadow_post_or_mix_manual_journal(self):
        self.app.engine.set_blocked(False);self.app.blocked.set(False);self.begin()
        self.assertEqual(self.app.engine.state()['orders'],{});self.assertEqual(self.app.intelligent.authorization.classification,'READ_ONLY_SHADOW_NO_LIVE_AUTHORITY')
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_monitor_diagnostics_have_current_version_fixed_counts_and_no_private_model_or_holdings(self):
        self.begin();self.app.intelligent_public=self.app.intelligent.public()
        snap=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall());text=encode(snap).decode();report=diagnostic(self.app)
        self.assertEqual(snap['version'],DISPLAY);self.assertEqual(snap['intelligent_shadow']['horizon_s'],86400)
        self.assertEqual(snap['intelligent_shadow']['market_coverage'],7);self.assertFalse(snap['intelligent_shadow']['live_order_authority'])
        self.assertIn('COMPLETE (8/8)',report);self.assertIn('Intelligent 24-hour shadow',report)
        for secret in (self.app.intelligent.state()['trial_id'],'OPP-','seed_marks','projected_advantage_usd','account_scope','maximum_training_end'):
            self.assertNotIn(secret,text);self.assertNotIn(secret,report)
        bad=deepcopy(snap);bad['intelligent_shadow']['portfolio_usd']=500
        with self.assertRaises(ValueError):validate(bad)
        old=deepcopy(snap);del old['intelligent_shadow'];old['version']='CoinCat v1.04';validate(old)
    def test_new_window_fits_at_minimum_and_normal_size_and_loss_projection_remains_renderable(self):
        w=self.begin()
        # A rejected reassessment retains the original ticket for audit display.
        self.app.intelligent._change('TEST_RISK_LOSS',{},lambda s:s['orders'][s['active']].update(latest_projection=dict(state='HOLD',reason='FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE')))
        self.app.intelligent.update_view();w.render()
        for width,height in ((1360,900),(1040,740)):
            w.root.geometry(str(width)+'x'+str(height));self.pump(lambda:w.root.winfo_width()==width and w.root.winfo_height()==height)
            for index,tree in ((1,w.decisions),(2,w.orders),(3,w.holdings)):
                w.tabs.select(index);self.root.update()
                self.assertTrue(tree.winfo_ismapped());self.assertGreater(tree.winfo_width(),100)
                self.assertLessEqual(tree.winfo_rootx()+tree.winfo_width(),w.root.winfo_rootx()+width)
                self.assertLessEqual(tree.winfo_rooty()+tree.winfo_height(),w.root.winfo_rooty()+height)
    def test_close_exits_and_checkpoints_without_withdraw_or_tray(self):
        self.begin();original=self.app.intelligent.state()['original']
        with patch.object(self.root,'withdraw') as hidden:
            self.app.close();self.pump(lambda:self.app.closed);hidden.assert_not_called()
        self.assertTrue(self.app.engine.public()['blocked']);self.assertEqual(self.app.intelligent.state()['original'],original)
        self.assertEqual(self.venue.posts,[])
    def test_historical_archive_is_byte_preserving_and_never_initializes_an_old_controller(self):
        folder=Path(self.tmp.name)/'research_data'/'opportunity_shadow';folder.mkdir(parents=True);path=folder/'active.sqlite3'
        with sqlite3.connect(path) as db:
            for table,value in (('trial_state',dict(trial_id='ARCHIVED',original=dict(ETH='1'),mode='ACTIVE')),('trial_clock',dict(valid_ns=123,wanted=True))):
                db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY,payload TEXT,digest TEXT)');db.execute('INSERT INTO '+table+' VALUES(1,?,?)',(pack(value),digest(value)))
        db.close();saved=path.read_bytes();value=read_archive(self.tmp.name,'opportunity_shadow')
        self.assertEqual(value['trial_state']['trial_id'],'ARCHIVED');self.app.open_archive();self.root.update()
        self.assertEqual(path.read_bytes(),saved);self.assertIsNone(self.app.intelligent.state());self.assertTrue(self.app.blocked.get())
        path.rename(folder/'archive-released.sqlite3') # Native Windows handle-release check.
        with self.assertRaises(BetaBlocked):read_archive(self.tmp.name,'../private_data')

class WindowsLifecycleChecks(unittest.TestCase):
    def test_only_minimize_style_is_removed_and_no_tray_hide_api_is_exposed(self):
        style=0x00CF0000;result=without_minimize(style)
        self.assertEqual(style^result,0x00020000);self.assertEqual(result&0x00010000,style&0x00010000)
        backend=MagicMock();lifecycle=WindowsLifecycle(MagicMock(),MagicMock(),backend=backend)
        self.assertFalse(hasattr(lifecycle,'hide'));lifecycle.close();lifecycle.close();backend.close.assert_called_once()
    def test_native_shutdown_query_never_vetoes_or_waits_for_network(self):
        native=NativeSessionHook.__new__(NativeSessionHook);native.root=MagicMock();native.shutdown=MagicMock()
        self.assertEqual(native.dispatch(0,0x11,1,0),1);native.shutdown.assert_not_called()
        self.assertEqual(native.dispatch(0,0x16,1,0),0);native.root.after.assert_called_once_with(0,native.shutdown)
