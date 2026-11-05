"""Real Tk shadow controls with fake reads; no exchange/private data."""
from copy import deepcopy
from unittest.mock import MagicMock,patch
import unittest
from offline_tests import test_spot_workspace as manual
from offline_tests.test_resumable_trial import Clock,frame,account
from coincat_portfolio_policy import PortfolioConfig
from coincat_monitor import capture,encode,validate
from coincat_spot_public import diagnostic
from coincat_shadow_trader import ShadowTrader

class TrialWorkspace(unittest.TestCase):
    setUp=manual.ManualWorkspace.setUp
    finish=manual.ManualWorkspace.finish
    pump=manual.ManualWorkspace.pump
    connect=manual.ManualWorkspace.connect
    def test_dashboard_start_pause_preserves_manual_default_and_no_post(self):
        self.connect();self.app.open_trial();self.app.start_trial(PortfolioConfig());self.pump(lambda:not self.app.busy)
        self.assertIsNotNone(self.app.shadow.state());self.assertTrue(self.app.blocked.get())
        self.app.pause_trial();self.app.trial_window.render();self.assertEqual(self.app.shadow.public()['state'],'PAUSED')
        text=self.app.trial_window.details.get('1.0','end');self.assertIn('Original HOLD',text)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_new_privacy_extension_rejects_money_and_arbitrary_fields(self):
        snap=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall())
        self.assertEqual(snap['shadow_trial']['state'],'OFF');self.assertFalse(snap['shadow_trial']['live_permission'])
        self.assertIn('168',diagnostic(self.app).replace('604800','168'))
        for key,value in (('portfolio_usd',12),('trial_id','secret'),('fee_currency','BTC')):
            altered=deepcopy(snap);altered['shadow_trial'][key]=value
            with self.assertRaises(ValueError):encode(altered)
        self.assertEqual(len(self.app.tabs.tabs()),7)
    def test_close_to_tray_does_not_pause_or_exit_and_manual_block_remains_on(self):
        self.app.tray.available=True;self.app.window_close();self.assertFalse(self.app.closing)
        self.assertEqual(self.root.state(),'withdrawn');self.app.tray.open();self.root.update()
        self.assertTrue(self.app.blocked.get());self.app.close();self.pump(lambda:self.app.closed)
