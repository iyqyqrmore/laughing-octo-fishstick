"""Forward scenario comparisons retain misses, adverse outcomes and HOLD."""
from decimal import Decimal as D
import unittest
from verification.opportunity_scenarios import run_case

class ForwardScenarios(unittest.TestCase):
    def test_no_fills_match_original_hold_and_adverse_path_keeps_losses_after_native_fees(self):
        miss,_=run_case('trend_no_fills');adverse,_=run_case('reversal_conditional_fills')
        self.assertEqual(miss['original'],adverse['original'])
        self.assertGreater(miss['metrics']['orders'],0);self.assertEqual(miss['metrics']['fill_events'],0)
        self.assertEqual(miss['wallet'],miss['original']);self.assertEqual(miss['performance']['advantage_usd'],0)
        self.assertTrue(all(fee==0 for fee in miss['native_fees'].values()))
        self.assertGreater(adverse['metrics']['fill_events'],0);self.assertGreater(adverse['metrics']['fees_usd_at_fill'],0)
        self.assertLess(adverse['performance']['advantage_usd'],0);self.assertGreater(adverse['max_drawdown'],0)
        self.assertEqual(adverse['performance']['actual_profit'],'NOT_ESTABLISHED')
    def test_identical_forward_events_reproduce_all_financial_results_and_rejection_counts(self):
        one,tape=run_case('trend_conditional_fills',waves=91);two,again=run_case('trend_conditional_fills',waves=91)
        self.assertEqual(one,two);self.assertEqual(tape,again);self.assertGreater(one['metrics']['modeled_fills'],0)
        self.assertEqual(one['initial_usd'],D(500));self.assertEqual(one['metrics']['replay_fills'],0)
        self.assertEqual(one['metrics']['direction_checks'],14*one['metrics']['reviews'])
