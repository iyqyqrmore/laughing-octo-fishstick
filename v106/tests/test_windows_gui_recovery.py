"""Windows-log regressions with synthetic state and explicitly owned Tk windows."""
import os
import sys
import threading
import tkinter as tk
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from v106.fee_check import ROOT
from offline_tests import test_spot_workspace as manual

GUI=bool(sys.platform=='win32' or os.environ.get('DISPLAY'))


@unittest.skipUnless(GUI,'Tk display required for window lifetime checks')
class LogoRecovery(unittest.TestCase):
    def test_archived_workspace_logo_uses_its_own_interpreter_with_another_root_alive(self):
        from offline_tests.gui_fixtures import gui_lifetime
        with TemporaryDirectory() as data,patch.dict(os.environ,{'COINCAT_DATA_DIR':data}):
            other=tk.Tk()
            try:
                with gui_lifetime() as (root,app):
                    self.assertIsNot(root.tk,other.tk)
                    self.assertIs(app.logo.tk,root.tk);self.assertIs(app._logo_source.tk,root.tk)
                    self.assertIn(str(app.logo),root.tk.call('image','names'))
                    self.assertNotIn(str(app.logo),other.tk.call('image','names'))
                    self.assertEqual(app.logo_label.cget('image')[0],str(app.logo))
            finally:
                other.update_idletasks();other.destroy()


@unittest.skipUnless(GUI,'Tk display required for window lifetime checks')
class ManualRecovery(unittest.TestCase):
    setUp=manual.ManualWorkspace.setUp
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump

    def tick_timers(self):
        return [timer for timer in self.root.tk.call('after','info')
            if str(self.root.tk.call('after','info',timer)[0]).endswith('tick')]

    def test_direct_ticks_coalesce_to_one_pending_timer_and_do_not_write_orders(self):
        before=self.app.engine.state()
        for _ in range(5):self.app.tick()
        self.assertEqual(len(self.tick_timers()),1)
        self.assertEqual(self.app.engine.state(),before)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])

    def test_reported_callback_error_keeps_a_timer_for_safe_close(self):
        with patch.object(self.app,'refresh_controls',side_effect=RuntimeError('SYNTHETIC_UI_CALLBACK_FAILURE')):
            self.pump(lambda:bool(self.errors))
        self.assertEqual(self.errors,['SYNTHETIC_UI_CALLBACK_FAILURE']);self.errors.clear()
        self.assertEqual(len(self.tick_timers()),1)
        self.app.close();self.pump(lambda:self.app.closed)
        self.assertEqual(self.tick_timers(),[]);self.assertIsNone(self.app._after)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])

    def test_close_cancels_pending_reconnect_and_refresh_callbacks(self):
        reconnect=self.root.after(60000,lambda:self.fail('Reconnect ran after close'))
        self.app._connect_after=reconnect
        self.app.close();self.pump(lambda:self.app.closed)
        self.assertNotIn(reconnect,self.root.tk.call('after','info'))
        self.assertIsNone(self.app._connect_after);self.assertIsNone(self.app._after)
        self.assertEqual(self.tick_timers(),[])

    def test_busy_start_guard_and_default_live_block_still_apply(self):
        self.app.busy=True
        try:
            self.app.start_intelligent()
            self.assertFalse(self.app.current_shadow().running)
            self.assertIsNone(self.app.current_shadow().store)
            self.assertIn('Wait for the bounded request',self.app.status.get())
            self.assertTrue(self.app.engine.block.is_set())
        finally:self.app.busy=False
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])


@unittest.skipUnless(GUI,'Tk display required for window lifetime checks')
class StartupRecovery(unittest.TestCase):
    def test_existing_workspace_helper_waits_for_pending_read_before_start(self):
        from coincat_spot_app import SpotApp
        from offline_tests import test_multi_workspace as multi
        if not hasattr(multi.MultiWorkspace,'forecasts'):multi.MultiWorkspace.setUpClass()
        original=SpotApp.open_intelligent;release=threading.Event();injected=[]
        def open_during_read(app):
            original(app)
            def read():
                if not release.wait(2):raise AssertionError('Synthetic read was not released')
                return dict(state='READY')
            self.assertTrue(app.work('forecast_history',read));injected.append(True)
            app.root.after(50,release.set)
        result=unittest.TestResult()
        try:
            with patch.object(SpotApp,'open_intelligent',open_during_read):
                multi.MultiWorkspace('test_start_is_separate_and_old_24h_trial_remains_unchanged').run(result)
        finally:release.set()
        self.assertEqual(injected,[True])
        self.assertTrue(result.wasSuccessful(),repr(result.failures+result.errors))


if __name__=='__main__':unittest.main()
