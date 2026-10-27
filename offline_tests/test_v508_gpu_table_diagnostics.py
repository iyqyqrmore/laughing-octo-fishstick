"""v50.8 guarded UI/research tests; no user data, Coinbase or orders."""
from __future__ import annotations
import tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from coincat_v508_table_ui import needs_tooltip
from coincat_v508_gpu_schedule import GPUResearchSchedule,FIRST_DELAY_S,RETRAIN_INTERVAL_S
from coincat_complete_diagnostics import _section,CompleteReportSession

class TableTests(unittest.TestCase):
    def test_only_clipped_cells_need_hover(self):
        self.assertFalse(needs_tooltip('BTC-USD',150,measure=len))
        self.assertTrue(needs_tooltip('hello\nworld',500,measure=len))
        self.assertTrue(needs_tooltip('A'*151,150,measure=len))

class ResearchScheduleTests(unittest.TestCase):
    def setUp(self):
        self.sch=GPUResearchSchedule(now=100)
        self.good=dict(connected=True,real_armed=False,stop_latched=False,
                       pending_orders=False,busy=False,shutdown=False,free_disk_bytes=2**30)
    def test_no_training_until_due_and_safe(self):
        self.assertFalse(self.sch.eligible(100,**self.good))
        self.assertTrue(self.sch.eligible(100+FIRST_DELAY_S,**self.good))
        for blocker in ('real_armed','stop_latched','pending_orders','busy','shutdown'):
            self.assertFalse(self.sch.eligible(100+FIRST_DELAY_S,**dict(self.good,**{blocker:True})))
        self.assertFalse(self.sch.eligible(100+FIRST_DELAY_S,**dict(self.good,connected=False)))
        self.assertFalse(self.sch.eligible(100+FIRST_DELAY_S,**dict(self.good,free_disk_bytes=0)))
    def test_claim_no_parallel_jobs_and_six_hour_throttle(self):
        when=100+FIRST_DELAY_S
        self.assertTrue(self.sch.claim(when))
        self.assertFalse(self.sch.claim(when))
        self.assertFalse(self.sch.eligible(when,**self.good))
        self.sch.finish(when+1,exception_type='RuntimeError')
        self.assertEqual(self.sch.last_error_type,'RuntimeError')
        self.assertEqual(self.sch.runs,1)
        self.assertFalse(self.sch.eligible(when+RETRAIN_INTERVAL_S-1,**self.good))

class DiagnosticsTests(unittest.TestCase):
    def test_redacted_failure_class_only(self):
        def fail():raise FileNotFoundError('/SECRET/DONT-SHARE/LEDGER.sqlite3')
        body,ok=_section('TEST',fail)
        self.assertFalse(ok)
        self.assertIn('FileNotFoundError',body)
        self.assertNotIn('SECRET',body)
    def test_session_wraps_bounded_sequential_reporting(self):
        from coincat_complete_diagnostics import _finish_complete_report
        body=_finish_complete_report(1700000000,1,['BODY\n'],[],elapsed_s=0.1)
        self.assertIn('COMPLETE (1/1)',body)
        self.assertIn('NO COINBASE REQUESTS OR ORDER SUBMISSIONS',body)
        self.assertIn('collection duration:',body)
    def test_source_launcher_verifies_before_private_data_access(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        launch=(root/'app/coincat_v60_launcher.py').read_text()
        self.assertLess(launch.index("if len(sys.argv)==2"), launch.index("if not ensure_private_data():return 2"))
        self.assertFalse((root/'build_windows').exists())

if __name__=='__main__':unittest.main()
