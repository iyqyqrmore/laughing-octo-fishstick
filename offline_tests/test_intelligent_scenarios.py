"""Unseen unfavorable outcomes must survive the strategy comparison report."""
import unittest
from verification.intelligent_scenarios import run_case,render

class ForwardScenarios(unittest.TestCase):
    def test_withheld_reversal_loses_vs_hold_for_both_forecasts_and_retains_costs(self):
        results=[run_case('trend_unseen_reversal',model) for model in ('DIRECT_24H_ANALOG_V1','NAIVE_24H_MOMENTUM')]
        for row in results:
            self.assertGreater(row['metrics']['modeled_fills'],0);self.assertLess(row['performance']['advantage_usd'],0)
            self.assertGreater(row['metrics']['fees_usd_at_fill'],0);self.assertNotEqual(row['chosen']['source'],'BTC');self.assertEqual(row['chosen']['target'],'BTC')
            self.assertEqual(row['unseen_historical_holdout']['count'],14);self.assertGreater(row['max_drawdown'],0)
        self.assertIn('not a historical backtest',render(results));self.assertIn('-',render(results))
    def test_no_fill_retains_original_wallet_and_zero_cost_despite_positive_forecast(self):
        row=run_case('trend_no_fill');self.assertIsNotNone(row['chosen']);self.assertEqual(row['wallet'],row['original'])
        self.assertEqual(row['performance']['advantage_usd'],0);self.assertEqual(row['metrics']['fill_events'],0)
        self.assertTrue(all(q==0 for q in row['native_fees'].values()))
    def test_costs_and_flat_forecast_may_hold_without_orders(self):
        for case in ('flat_costs_hold','high_own_fee_hold'):
            row=run_case(case);self.assertEqual(row['metrics']['orders'],0);self.assertEqual(row['wallet'],row['original'])
