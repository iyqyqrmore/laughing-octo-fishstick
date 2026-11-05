import unittest
from copy import deepcopy
from coincat_trial_clock import *

class ObservationClock(unittest.TestCase):
    def setUp(self):
        self.wall=1793865600.;self.mono=0;self.s=new_clock('synthetic',self.wall)
        begin_run(self.s,wall=self.wall,mono_ns=0,run_id='a');prime_quality(self.s,valid=True,coverage=7)
    def run_hours(self,hours,valid=True,coverage=7):
        for _ in range(round(hours*120)):
            self.wall+=30;self.mono+=30*NS
            advance(self.s,wall=self.wall,mono_ns=self.mono,valid=valid,coverage=coverage,run_id=self.s['run_id'])
    def restart(self,gap):
        end_run(self.s,wall=self.wall);self.s=deepcopy(self.s);self.wall+=gap;self.mono=0
        begin_run(self.s,wall=self.wall,mono_ns=0);prime_quality(self.s,valid=True,coverage=7)
    def test_six_then_ten_offline_then_four_is_ten(self):
        self.run_hours(6);self.restart(10*3600);self.run_hours(4)
        self.assertEqual(self.s['valid_ns'],10*3600*NS);self.assertEqual(self.s['offline_ns'],10*3600*NS)
        self.assertEqual(progress(self.s,self.wall)['calendar_elapsed_s'],20*3600)
    def test_multiple_interrupted_sessions_complete_168_and_freeze(self):
        for _ in range(28):
            self.run_hours(6)
            if self.s['phase']!='COMPLETE':self.restart(2*86400)
        self.assertEqual(self.s['valid_ns'],TARGET_NS);self.assertEqual(self.s['phase'],'COMPLETE')
        saved=deepcopy(self.s);self.run_hours(1);begin_run(self.s,wall=self.wall,mono_ns=0)
        self.assertEqual(self.s,saved)
    def test_user_paused_survives_restart_and_partial_never_full(self):
        self.s['wanted']=False;self.run_hours(1);self.restart(86400);self.run_hours(1)
        self.assertEqual(self.s['valid_ns'],0);self.assertEqual(self.s['phase'],'PAUSED')
        self.s['wanted']=True;prime_quality(self.s,valid=True,coverage=6);self.run_hours(1,coverage=6)
        self.assertEqual(self.s['valid_ns'],0);self.assertGreater(self.s['partial_ns'],0)
    def test_wall_and_dst_changes_do_not_earn_or_remove_hours(self):
        self.run_hours(1);self.wall-=3600;self.run_hours(1)
        self.assertEqual(self.s['valid_ns'],2*3600*NS);self.assertIsNone(progress(self.s,self.wall)['calendar_elapsed_s'])
    def test_duplicate_overlap_suspend_and_stale_rejected(self):
        self.run_hours(.1);before=self.s['valid_ns']
        self.assertEqual(advance(self.s,wall=self.wall,mono_ns=self.mono,valid=True,coverage=7,run_id='a'),'DUPLICATE_IGNORED')
        self.wall+=3600;self.mono+=3600*NS
        self.assertEqual(advance(self.s,wall=self.wall,mono_ns=self.mono,valid=True,coverage=7,run_id='a'),'GAP_NOT_COUNTED')
        self.assertEqual(self.s['valid_ns'],before)
        self.run_hours(.1,valid=False);self.assertEqual(self.s['valid_ns'],before)
        advance(self.s,wall=self.wall,mono_ns=self.mono-1,valid=True,coverage=7,run_id='a')
        self.assertEqual(self.s['phase'],'REVIEW_REQUIRED')
        with self.assertRaises(BetaBlocked):advance(self.s,wall=self.wall,mono_ns=self.mono+1,valid=True,coverage=7,run_id='other')
    def test_unclean_restart_reports_interruption_without_credit(self):
        self.run_hours(1);self.wall+=86400;begin_run(self.s,wall=self.wall,mono_ns=0)
        self.assertEqual(self.s['interruptions'],1);self.assertEqual(self.s['valid_ns'],3600*NS)
