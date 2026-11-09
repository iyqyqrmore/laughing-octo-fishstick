"""Real SQLite resources retained strongly, including failed new-policy paths."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest
from coincat_beta_store import BetaBlocked
from coincat_intelligent_trader import IntelligentTrader
from offline_tests.intelligent_fixtures import Clock,frame
from offline_tests.trial_sqlite_resources import trial_sqlite_probe

class IntelligentRecoveryResources(unittest.TestCase):
    def test_success_failed_action_and_corruption_release_handles_without_resetting_trial(self):
        with TemporaryDirectory() as tmp,trial_sqlite_probe() as probe:
            clock=Clock();path=Path(tmp)/'trial.sqlite3';engine=IntelligentTrader(path,clock=clock.wall,monotonic_ns=clock.ns)
            engine.start();f=frame(clock);f['forecast']=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT');engine.review(f)
            before=engine.state();probe.assert_released(self,path)
            with self.assertRaises(BetaBlocked):engine._change('INVALID_REBASE',{},lambda s:s['original'].update(ETH=s['original']['ETH']+1))
            self.assertEqual(engine.state(),before);probe.assert_released(self,path)
            engine.shutdown();probe.assert_released(self,path)
            with closing(sqlite3.connect(path)) as db,db,closing(db.cursor()) as cur:cur.execute("UPDATE trial_state SET digest='corrupted'")
            raw=path.read_bytes();restored=IntelligentTrader(path,clock=clock.wall,monotonic_ns=clock.ns)
            self.assertTrue(restored.load_error);self.assertFalse(restored.running);self.assertEqual(path.read_bytes(),raw)
            probe.assert_released(self,path)
    def test_failed_initial_validation_leaves_no_open_connection_or_silent_retry(self):
        with TemporaryDirectory() as tmp,trial_sqlite_probe() as probe:
            clock=Clock();path=Path(tmp)/'trial.sqlite3';engine=IntelligentTrader(path,clock=clock.wall,monotonic_ns=clock.ns);engine.start()
            def fault(sql):
                if 'INSERT INTO trial_state' in sql:raise sqlite3.OperationalError('SYNTHETIC_INITIAL_WRITE_FAILURE')
            probe.fault=fault
            with self.assertRaises(sqlite3.OperationalError):engine.review(frame(clock))
            probe.fault=None
            probe.assert_released(self,path);raw=path.read_bytes()
            restored=IntelligentTrader(path,clock=clock.wall,monotonic_ns=clock.ns)
            self.assertTrue(restored.load_error);self.assertEqual(path.read_bytes(),raw);probe.assert_released(self,path)
