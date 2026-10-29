from copy import deepcopy
import unittest
from coincat_passive_lab import PassiveLab
from offline_tests.test_v91_full_balance import scan,market,NOW


class PassiveOnly(unittest.TestCase):
    def test_notes_every_three_minutes_and_do_not_change_ranking(self):
        result=scan();original=deepcopy(result);quotes,_=market();lab=PassiveLab()
        self.assertIn('passive',lab.observe(result,quotes,now=NOW).lower())
        self.assertIsNone(lab.observe(result,quotes,now=NOW+179))
        self.assertIsNotNone(lab.observe(result,quotes,now=NOW+180))
        self.assertEqual(result,original)
        self.assertFalse(hasattr(lab,'submit'))

    def test_unchanged_future_marks_compare_receipt_with_hold_without_second_fee(self):
        result=scan();q,_=market();lab=PassiveLab()
        lab.observe(result,q,now=NOW)
        fresh={p:(b[0],b[1],NOW+300) for p,b in q.items()}
        lab.observe({'ranked':[]},fresh,now=NOW+300)
        self.assertGreater(lab.counts['300_ABOVE_HOLD'],0)
        self.assertIn('hypothetical',lab.notes[-1][1])

    def test_missing_endpoints_expire_as_missed_instead_of_losses(self):
        result=scan();q,_=market();lab=PassiveLab()
        lab.observe(result,q,now=NOW)
        lab.observe({'ranked':[]},{},now=NOW+421)
        self.assertGreater(lab.counts['300_MISSED'],0)
        self.assertEqual(lab.counts['300_NOT_ABOVE_HOLD'],0)

    def test_capacity_and_repeat_directions_are_bounded_and_reported(self):
        result=scan();q,_=market();lab=PassiveLab(capacity=1)
        lab.observe(result,q,now=NOW)
        lab.observe(result,q,now=NOW+1)
        self.assertEqual(len(lab.pending),1)
        self.assertGreater(lab.counts['CAPACITY_DEFERRED'],0)
        self.assertLessEqual(len(lab.notes),100)
