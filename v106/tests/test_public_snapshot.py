"""Force checkpoint/publication interleavings without depending on CPU timing."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest.mock import patch
import unittest
from v106.fee_check import ROOT
from coincat_multi_trader import MultiTrader
from coincat_multi_public import validate
from offline_tests.multi_fixtures import Clock,predictions,observed


class PublicSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.forecasts=predictions(Clock())
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=Clock()
        self.engine=MultiTrader(Path(self.tmp.name)/'trial.sqlite3',clock=self.clock.wall,monotonic_ns=self.clock.ns)
        self.engine.start()
    def review(self):self.engine.review(observed(self.clock,self.forecasts))
    def coherent(self,value,reviews):
        validate(value);self.assertEqual(value['reviews'],reviews)
        self.assertEqual(value['direction_checks'],14*reviews)
        for horizon in value['horizons'].values():
            self.assertEqual(horizon['checks'],14*reviews)
            self.assertEqual(horizon['qualified']+horizon['rejected'],horizon['checks'])
        self.assertEqual(sum(r['selected_orders'] for r in value['horizons'].values()),value['orders'])

    def test_committed_review_before_view_publication_keeps_one_consistent_summary(self):
        self.review();self.coherent(self.engine.public(),1);self.clock.tick(30)
        with patch.object(self.engine,'update_view'):self.review()
        self.assertEqual(self.engine.state()['metrics']['reviews'],2)
        self.assertEqual(self.engine.view()['state']['metrics']['reviews'],1)
        before=self.engine.state();digest=hashlib.sha256(self.engine.path.read_bytes()).hexdigest()
        self.coherent(self.engine.public(),1)
        self.assertEqual(self.engine.state(),before)
        self.assertEqual(hashlib.sha256(self.engine.path.read_bytes()).hexdigest(),digest)
        self.engine.update_view();self.coherent(self.engine.public(),2)

    def test_new_view_published_during_summary_cannot_replace_its_captured_counts(self):
        self.review();progress=self.engine.progress
        def publish():
            self.clock.tick(30);self.review();return progress()
        with patch.object(self.engine,'progress',side_effect=publish):value=self.engine.public()
        self.coherent(value,1);self.coherent(self.engine.public(),2)

    def test_worker_commit_between_capture_and_projection_is_deterministic_and_safe(self):
        self.review();captured=threading.Event();finished=threading.Event();errors=[]
        progress=self.engine.progress
        def writer():
            try:
                if not captured.wait(30):raise AssertionError('Reader did not capture its observation')
                self.clock.tick(30);self.review()
            except Exception as error:errors.append(error)
            finally:finished.set()
        def interleave():
            captured.set()
            if not finished.wait(30):raise AssertionError('Synthetic writer did not finish')
            return progress()
        thread=threading.Thread(target=writer,name='PublicSnapshotSyntheticWriter');thread.start()
        try:
            with patch.object(self.engine,'progress',side_effect=interleave):value=self.engine.public()
        finally:captured.set();thread.join(30)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.coherent(value,1);self.coherent(self.engine.public(),2)

    def test_first_initialization_during_summary_keeps_zero_and_first_review_separate(self):
        self.assertIsNone(self.engine.store);progress=self.engine.progress
        with patch.object(self.engine,'progress',side_effect=lambda:(self.review(),progress())[1]):
            value=self.engine.public()
        self.coherent(value,0);self.assertEqual(value['active_orders'],0)
        self.coherent(self.engine.public(),1)

    def test_direct_24h_export_uses_its_published_snapshot_without_a_live_state_reread(self):
        from coincat_intelligent_trader import IntelligentTrader
        engine=IntelligentTrader(Path(self.tmp.name)/'direct.sqlite3',clock=self.clock.wall,monotonic_ns=self.clock.ns)
        engine.start();engine.review(observed(self.clock,self.forecasts));before=engine.public()
        with patch.object(engine,'state',side_effect=AssertionError('Live checkpoint read during projection')):
            self.assertEqual(engine.public(),before)
        raw=json.dumps(before)
        for private in (engine.state()['trial_id'],'wallet','forecast_evidence','source_budget','OPP-'):
            self.assertNotIn(private,raw)

    def test_horizon_totals_selection_and_privacy_validation_remain_strict(self):
        self.review();value=self.engine.public()
        for field in ('checks','qualified','selected_orders'):
            bad=deepcopy(value);bad['horizons']['M5'][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):validate(bad)
        bad=deepcopy(value);bad['horizons']['M5']['wallet']='PRIVATE'
        with self.assertRaises(ValueError):validate(bad)
        # Invalid published counters are still rejected, never repaired/hidden.
        self.engine._view['state']['metrics']['rejection_detail']['horizons']['M5']['checks']+=1
        with self.assertRaises(ValueError):self.engine.public()


if __name__=='__main__':unittest.main()
