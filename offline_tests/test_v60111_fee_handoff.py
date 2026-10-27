"""v60.11.1 controlled no-stacking fee audit. Fake quotes, no Coinbase requests or live orders."""
from __future__ import annotations
import ast
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from coincat_v502_fee_learning import FeeLearning
from coincat_multicurrency import evaluate_rotation
from coincat_v502_relative_learning import evaluate_hold_switch
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio
from coincat_v502_microstructure import microstructure_report

ROOT=Path(__file__).resolve().parents[1]


class SingleLegFeeHandoff(unittest.TestCase):
    def test_old_two_leg_signal_hurdle_no_longer_blocks_one_order_research(self):
        with tempfile.TemporaryDirectory() as d:
            f=FeeLearning(Path(d)/'fee.sqlite3')
            f.capture_tier({'fee_tier': {'maker_fee_rate': '.005', 'taker_fee_rate': '.009'}},now=100000)
            current=f.research_screen('ADA-USDC','1.40','8',now=100001)
            historical=f.research_screen('ADA-USDC','1.40','8',legs=2,now=100001)
            self.assertEqual(current['state'],'UNVALIDATED_MOMENTUM_ABOVE_COST')
            self.assertEqual(historical['state'],'MOMENTUM_BELOW_COST')
            self.assertEqual(current['hurdle_pct'],Decimal('1.13'))
            self.assertEqual(historical['hurdle_pct'],Decimal('2.18'))
            self.assertEqual(current['cost_screen_legs'],1)
            self.assertEqual(historical['cost_screen_legs'],2)
            self.assertTrue(current['fee_hurdle_is_advisory_only'])
            self.assertFalse(current['trade_authorized'])
            self.assertFalse(current['pair_verified'])

    def test_production_gui_research_call_explicitly_uses_one_leg(self):
        tree=ast.parse((ROOT/'app/coincat_app.py').read_text())
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
               and isinstance(node.func,ast.Attribute) and node.func.attr=='research_screen']
        self.assertEqual(len(calls),1)
        leg_kw=[k for k in calls[0].keywords if k.arg=='legs']
        self.assertEqual(len(leg_kw),1)
        self.assertIsInstance(leg_kw[0].value,ast.Constant)
        self.assertEqual(leg_kw[0].value.value,1)
        # Active planner must still enforce one ORDER on eligible products.
        planner=(ROOT/'app/coincat_rotation_autopilot.py').read_text()
        self.assertIn('max_legs=1 if direct_only else 2',planner)

    def _one_order_plan(self,fee):
        now=1770000200
        return evaluate_rotation(source='BTC',target='ETH',
            authorized_qty='0.01',verified_available_qty='0.01',balance_age_s=10,
            catalog={'ETH-BTC','BTC-USD','ETH-USD'},
            quotes={'ETH-BTC':('0.04','0.04',now),
                    'BTC-USD':('80000','80000',now),
                    'ETH-USD':('3200','3200',now)},
            now=now,usd_per_order_cap='800',
            product_rules={'ETH-BTC':{'base_increment':'0.00000001','base_min_size':'0.000001','quote_min_size':'0.00000001'}},
            fee_rates_by_pair={'ETH-BTC':str(fee)},slippage_bps='0',max_legs=1)

    def test_direct_planner_fee_one_time_and_shadow_fifo_same_receipt(self):
        free=self._one_order_plan('0')
        fee=self._one_order_plan('0.009')
        self.assertEqual(fee['state'],'RESEARCH ONLY')
        route=fee['routes'][0]
        self.assertEqual(len(route['steps']),1)
        receipt=route['steps'][0]
        self.assertEqual(receipt['pair'],'ETH-BTC')
        self.assertEqual(receipt['side'],'BUY')
        self.assertEqual(receipt['fee_rate_used'],Decimal('0.009'))
        self.assertEqual(receipt['input_quantity'],receipt['gross_base_quantity']*Decimal('.04')*Decimal('1.009'))
        self.assertLess(route['destination_units_estimate'],free['routes'][0]['destination_units_estimate'])
        # SHADOW consumes the same planned receipt and must not debit a fee again.
        starting={'BTC':'0.01'}
        marks={'USD':'1','BTC':'80000','ETH':'3200'}
        wallet=ShadowFIFOPortfolio(starting,marks)
        try:
            outcome=wallet.post_hypothetical_route(session_id='SHADOW-FEE-HANDOFF',
                steps=route['steps'],usd_rates=marks,at_utc=1770000200)
            self.assertEqual(outcome['steps'],1)
            simulated=wallet.balances()
            self.assertEqual(simulated['ETH'],route['destination_units_estimate'])
            self.assertEqual(simulated['BTC'],route['residual_wallet_estimate']['BTC'])
            self.assertEqual(wallet.mark_vs_hold(marks)['delta_usd'],route['immediate_change_usd'])
            step_fee=receipt['input_quantity']-receipt['input_quantity']/Decimal('1.009')
            self.assertEqual(outcome['estimated_fee_usd'],step_fee*Decimal('80000'))
        finally:
            wallet.close()

    def test_hold_comparison_does_not_charge_second_fee(self):
        route=self._one_order_plan('0.009')['routes'][0]
        idea={**route,'source_units':Decimal('0.01')}
        evidence={'state':'OBSERVED_WINDOWS_READY_NOT_PREDICTIVE','n':35,
                  'oos_validated':True,'oos_state':'TEST_FIXTURE',
                  'mean_relative_return':Decimal(0),'p10_relative_return':Decimal(0)}
        result=evaluate_hold_switch(idea,evidence,minimum_net_advantage_usd='.10')
        self.assertEqual(result['net_mean_usd'],route['immediate_change_usd'])
        self.assertEqual(result['net_p10_usd'],route['immediate_change_usd'])
        self.assertFalse(result['minimum_satisfied'])

    def test_combined_report_names_active_one_leg_and_historical_two_leg(self):
        with tempfile.TemporaryDirectory() as d:
            f=FeeLearning(Path(d)/'fee.sqlite3')
            f.capture_tier({'fee_tier': {'maker_fee_rate': '.005', 'taker_fee_rate': '.009'}},now=100000)
            class App: pass
            a=App();a.last_cycle={'auto_rotation':{'ideas':[]}};a.fee_learning=f
            # No live fee tier is fresh at current time, but legend must be correct.
            report=microstructure_report(a)
            self.assertIn('ACTIVE ONE-ORDER conversion screening hurdle',report)
            self.assertIn('HISTORICAL TWO-ORDER entry+later-exit',report)
            self.assertIn('NO DOUBLE FEE:',report)
            self.assertNotIn('Two-leg fee-tier + slippage research hurdle:',report)

if __name__=='__main__': unittest.main()
