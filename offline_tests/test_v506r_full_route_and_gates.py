"""CoinCat v50.6R pure and mocked regression; cannot authorize live trading."""
from __future__ import annotations
import tempfile,unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from coincat_v502_relative_learning import evaluate_hold_switch
from coincat_v503_lab_evidence import grade_lab
from coincat_v506_gate_verifier import report,synthetic_predictive_cases
from coincat_v506_profit_sensitivity import compare_route_ideas

class FullRouteAdvantage(unittest.TestCase):
    def setUp(self):
        self.idea=dict(initial_wallet_usd_mark='100',post_route_wallet_usd_mark='99.5',
                       source_units='1',input_units_planned='1')
        self.evidence=dict(state='OBSERVED_WINDOWS_READY_NOT_PREDICTIVE',n=42,
                           oos_validated=True,mean_relative_return='.012',p10_relative_return='.012')

    def test_complete_route_means_and_downside_clear_half_dollar(self):
        low=evaluate_hold_switch(self.idea,self.evidence,'0.55')
        high=evaluate_hold_switch(self.idea,self.evidence,'0.98')
        self.assertEqual(low['net_p10_usd'],Decimal('.70'))
        self.assertEqual(low['research_decision'],'SWITCH_WORTH_RESEARCH')
        self.assertEqual(high['research_decision'],'HOLD_PREFERRED')

    def test_higher_projected_gain_not_capped_at_floor(self):
        e=dict(self.evidence,mean_relative_return='.10',p10_relative_return='.10')
        result=evaluate_hold_switch(self.idea,e,'0.55')
        self.assertGreater(result['net_mean_usd'],Decimal('5'))
        self.assertTrue(result['minimum_satisfied'])

    def test_unverified_is_still_recorded_not_executable(self):
        e=dict(self.evidence,oos_validated=False)
        result=evaluate_hold_switch(self.idea,e,'0.55')
        self.assertEqual(result['research_decision'],'HOLD_UNTIL_VERIFIED')
        self.assertTrue(result['minimum_satisfied'])

    def test_tenth_percentile_below_threshold_blocks_even_if_mean_passes(self):
        e=dict(self.evidence,mean_relative_return='.02',p10_relative_return='.01')
        result=evaluate_hold_switch(self.idea,e,'0.55')
        self.assertEqual(result['research_decision'],'HOLD_PREFERRED')
        self.assertFalse(result['minimum_satisfied'])

    def test_invalid_and_nonfinite_preferences_block(self):
        for value in ('NaN','Infinity','-1','0','10001','bogus'):
            result=evaluate_hold_switch(self.idea,self.evidence,value)
            self.assertNotEqual(result['research_decision'],'SWITCH_WORTH_RESEARCH')

    def test_fee_stale_or_no_portfolio_usd_prices_keep_budget_zero(self):
        route=dict(self.idea,net_p10_usd=Decimal('.7'),net_mean_usd=Decimal('.7'),
                   research_decision='SWITCH_WORTH_RESEARCH',oos_validated=True)
        case=dict(catalog_total=10,catalog_seen=10,focused_total=5,focused_mature=5,
                  verified_forward_labels=240,route_ideas=[route],fee_fresh=True,
                  usd_complete=True,gpu_heldout=True,current_order_budget='100',scan_fresh=True)
        good=grade_lab(**case)
        self.assertTrue(good['budget_eligible'])
        self.assertFalse(good['changes_broker_limits'])
        self.assertFalse(good['authorizes_order'])
        self.assertFalse(grade_lab(**dict(case,minimum_net_advantage_usd='.98'))['budget_eligible'])
        self.assertFalse(grade_lab(**dict(case,fee_fresh=False))['budget_eligible'])
        self.assertFalse(grade_lab(**dict(case,usd_complete=False))['budget_eligible'])

    def test_comparison_uses_only_oos_and_never_counts_as_real_fills(self):
        study=compare_route_ideas([
            dict(net_mean_usd='.8',net_p10_usd='.7',oos_validated=True),
            dict(net_mean_usd='2',net_p10_usd='1.2',oos_validated=True),
            dict(net_mean_usd='100',net_p10_usd='100',oos_validated=False)])
        self.assertEqual((study['above_055'],study['above_098'],study['unverified']), (2,1,1))
        self.assertEqual(study['new_ideas'],1)

    def test_synthetic_gate_report_never_claims_production_ready(self):
        self.assertEqual(synthetic_predictive_cases()['good_net_usd'],Decimal('.70'))
        body=report(None)
        self.assertIn('[PASS / SYNTHETIC ONLY]',body)
        self.assertIn('[NOT VERIFIED / LIVE]',body)
        self.assertIn('[BLOCKED / PRODUCTION]',body)
        self.assertIn('POST intentionally disabled',body)

    def test_missing_file_ui_error_cannot_be_hidden(self):
        fake=SimpleNamespace(last_cycle={},catalog=[],ledger=None,
                             _last_ui_callback_error_type='FileNotFoundError',
                             _last_ui_callback_error_origin='poll')
        body=report(fake)
        self.assertIn('Missing-file UI callback root cause',body)
        self.assertIn('Callback source: poll',body)
        self.assertIn('[BLOCKED] Missing-file',body)

if __name__=='__main__':unittest.main()
