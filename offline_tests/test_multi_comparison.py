import unittest
from verification.multi_horizon_scenarios import run_case,render

class PairedComparisons(unittest.TestCase):
    def test_unseen_reversal_retains_losses_after_realistic_conditional_costs_for_all_policies(self):
        row=run_case('long_trend_reversal');self.assertEqual(row['hold']['advantage_usd'],0)
        for label in ('24H_ONLY','MULTI_HORIZON'):
            trial=row['outcomes'][label];self.assertGreater(trial['metrics']['fill_events'],0);self.assertLess(trial['performance']['advantage_usd'],0)
            self.assertGreater(sum(trial['native_fees'].values()),0)
        originals=[x['original'] for x in row['outcomes'].values()];self.assertTrue(all(x==originals[0] for x in originals))
        self.assertIn('not a continuous market backtest',render([row]))
    def test_no_fill_cannot_credit_a_projected_edge_or_charge_a_fee(self):
        row=run_case('long_trend_no_fill')
        for trial in row['outcomes'].values():
            self.assertEqual(trial['performance']['advantage_usd'],0);self.assertEqual(trial['wallet'],row['common_original'])
            self.assertEqual(trial['metrics']['fill_events'],0);self.assertTrue(all(q==0 for q in trial['native_fees'].values()))
    def test_short_horizon_can_propose_while_missing_24h_history_stays_a_legitimate_hold(self):
        row=run_case('short_history_reversal');self.assertEqual(row['outcomes']['24H_ONLY']['metrics']['orders'],0)
        trial=row['outcomes']['MULTI_HORIZON'];self.assertLess(trial['proposed_horizon'],86400);self.assertGreater(trial['metrics']['fill_events'],0)
        self.assertLess(trial['performance']['advantage_usd'],0)
