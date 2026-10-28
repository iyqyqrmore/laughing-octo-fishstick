"""v60.15: separate, explicit, unvalidated SHADOW what-if studies; NEVER LIVE."""
import unittest
from pathlib import Path
from decimal import Decimal
from coincat_v507_shadow_arm import ShadowArmedResearch,experimental_shadow_report
from offline_tests.selection_fixtures import calibrated,SyntheticCalibratedProvider
NOW=1770000000
MARKS={'USD':'1','USDC':'1','BTC':'50000'}
BOOKS={'BTC-USD':('50000','50000',NOW+1), 'BTC-USDC':('50000','50000',NOW+1)}
BUDGET={'per_order_usd':'100','incremental_exposure_usd':'100','daily_buy_usd':'100','max_attempts':'12'}

def buy():
    # One USD-funded Coinbase spot order; gross quote 50, taker fee 0.9%.
    return calibrated({'source':'USD','target':'BTC','trigger_pair':'BTC-USD',
        'route':[('BTC-USD','BUY')], 'input_units_planned':Decimal('50.45'),
        'destination_units_estimate':Decimal('.001'),'research_size_cap_usd':Decimal('50.45'),
        'immediate_change_usd':Decimal('-.45'),'observed_momentum_pct':Decimal('2.0'),
        'shadow_fifo_steps':[{'pair':'BTC-USD','side':'BUY','gross_base_quantity':Decimal('.001'),
            'input_quantity':Decimal('50.45'),'output_quantity':Decimal('.001'),'fee_rate_used':Decimal('.009'),
            'approx_usd_notional':Decimal('50.45'),'output_usd_mark':Decimal('50')}],
        'research_decision':'STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED',
        'oos_validated':False,'net_p10_usd':None,'sends_live_orders':False},NOW+1)

def arm(obj):
    obj.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'USD':'100'},fresh_usd_rates=MARKS,now=NOW)

class Experimental(unittest.TestCase):
    def setUp(self):
        self.normal=ShadowArmedResearch(mark_horizon_s=300)
        self.exp=ShadowArmedResearch(mark_horizon_s=300,experimental=True)
        arm(self.normal);arm(self.exp)
    def tearDown(self):
        for sh in (self.normal,self.exp):
            for p in sh.fifo_portfolios.values():p.close()
    def observe(self,shadow,ideas,now=NOW+1,quotes=BOOKS,marks=MARKS,budget=BUDGET):
        shadow.observe(now=now,quotes=quotes,usd_rates=marks,route_ideas=ideas,
            strict_quotes=True,minimum_advantage='.10',risk_budgets=budget)
    def test_unvalidated_one_order_executes_only_in_experimental_memory(self):
        self.observe(self.normal,[buy()]);self.observe(self.exp,[buy()])
        self.assertEqual(self.normal.snapshot()['shadow_fifo_posted_routes'],0)
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_routes'],1)
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_legs'],1)
        self.assertEqual(self.exp.model_balances()['BTC'],Decimal('.001'))
        self.assertEqual(self.normal.model_balances(),{'USD':Decimal('100')})
        self.assertEqual(self.exp.snapshot()['historically_qualified_route_reviews'],0)
        self.assertFalse(self.exp.snapshot()['execution_certified'])
        self.assertEqual(self.exp.snapshot()['real_order_submissions'],0)
        self.assertTrue(self.exp.entries[0]['experimental_unvalidated'])
        self.assertIsNone(self.exp.entries[0]['projected_net_p10_usd'])
    def test_no_multi_leg_basket_or_momentum_only_fill(self):
        basket=buy();basket['shadow_fifo_steps']*=2
        self.observe(self.exp,[basket])
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_routes'],0)
        self.exp.disarm();arm(self.exp)
        neg=buy();neg['observed_momentum_pct']='-1.4';neg.pop('forward_edge_evidence')
        self.observe(self.exp,[neg],now=NOW+3,
            quotes={k:(v[0],v[1],NOW+3) for k,v in BOOKS.items()})
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_routes'],0)
    def test_budget_and_bad_quote_reject(self):
        self.observe(self.exp,[buy()],budget={**BUDGET,'per_order_usd':'4'})
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_routes'],0)
        self.assertEqual(self.exp.snapshot()['rejected_shadow_budget'],1)
    def test_marked_future_price_and_portfolio_hold_comparison(self):
        self.observe(self.exp,[buy()])
        self.observe(self.exp,[],now=NOW+302,
            quotes={'BTC-USD':('51000','51000',NOW+302)},
            marks={'USD':'1','BTC':'51000','USDC':'1'})
        s=self.exp.snapshot()
        self.assertEqual(s['marked_counterfactuals'],1)
        self.assertEqual(s['marked_positive'],1)
        self.assertEqual(Decimal(s['shadow_fifo_bands']['TAKER_ASK']['counterfactual_portfolio_vs_hold_usd']),Decimal('.55'))
    def test_safely_disarmed_and_no_exchange_client(self):
        self.exp.disarm()
        self.observe(self.exp,[buy()])
        self.assertEqual(self.exp.snapshot()['shadow_fifo_posted_routes'],0)
        source=(Path(__file__).parent.parent/'app'/'coincat_v507_shadow_arm.py').read_text()
        self.assertNotIn('client_from_credentials',source)
        self.assertNotIn('create_order(',source)
    def test_redacted_diagnostics(self):
        self.observe(self.exp,[buy()])
        class Dummy:pass
        app=Dummy();app.experimental_shadow=self.exp
        report=experimental_shadow_report(app)
        self.assertIn('Simulated taker FIFO routes: 1',report)
        self.assertIn('UNVALIDATED',report)
        self.assertNotIn('BTC-USD',report)
        self.assertNotIn('50.45',report)

if __name__=='__main__':unittest.main()

class ExperimentalIntegration(unittest.TestCase):
    def test_unverified_track_exposes_5_15_60m_checkpoints(self):
        sh=ShadowArmedResearch(mark_horizon_s=300,experimental=True)
        arm(sh)
        try:
            sh.observe(now=NOW+1,quotes=BOOKS,usd_rates=MARKS,route_ideas=[buy()],
                       minimum_advantage='.10',strict_quotes=True,risk_budgets=BUDGET)
            for delta,h in ((302,300),(902,900),(3602,3600)):
                sh.observe(now=NOW+delta,quotes={'BTC-USD':('51000','51000',NOW+delta)},
                    usd_rates={**MARKS,'BTC':'51000'},route_ideas=[],strict_quotes=True,risk_budgets=BUDGET)
                self.assertEqual(sh.snapshot()['experimental_forward_horizons'][str(h)]['matured'],1)
        finally:
            for wallet in sh.fifo_portfolios.values():wallet.close()
    def test_source_contains_second_independent_arm_and_reuses_planner(self):
        src=(Path(__file__).parent.parent/'app'/'coincat_app.py').read_text()
        self.assertIn('def _toggle_experimental_shadow(self)',src)
        self.assertIn('self.experimental_shadow=ShadowArmedResearch(experimental=True)',src)
        self.assertIn("result['experimental_rotation']=shadow_screen(",src)
        self.assertIn("result['experimental_rotation']=result['auto_rotation']",src)
        self.assertIn('self.experimental_pnl_status',src)
        self.assertIn('max_targets=8,experimental=True',src)
        self.assertIn("self.experimental_shadow.disarm()",src)
        self.assertNotIn('self.broker.arm()\n            self.experimental_shadow',src)
    def test_shareable_diagnostics_includes_experiment(self):
        s=(Path(__file__).parent.parent/'app'/'coincat_complete_diagnostics.py').read_text()
        self.assertIn('experimental_shadow_report(app)',s)

class ActualPlannerIntegration(unittest.TestCase):
    def test_real_unified_planner_hands_off_unvalidated_one_order_to_experiment(self):
        from coincat_rotation_autopilot import auto_rotation_screen
        plan=auto_rotation_screen(
            buy_signals=[{'action':'BUY','pair':'BTC-USD','momentum_pct':'3'}],
            holdings=[{'asset':'USD','remaining_qty':'100','enabled':1}],
            verified_balances={'USD':'100'},balance_age_s=3,catalog=['BTC-USD'],
            quotes={'BTC-USD':('50000','50000',NOW)},
            product_rules={'BTC-USD':{'base_increment':'0.00000001','base_min_size':'0.00001','quote_min_size':'1'}},
            usd_per_order_cap=Decimal(100),now=NOW,
            fee_rates_by_pair={'BTC-USD':Decimal('.009')},direct_only=True,
            forward_evidence=SyntheticCalibratedProvider().forecasts(pairs=['BTC-USD'],now=NOW,
                snapshot={'rows':[{'pair':'BTC-USD','age_ms':0,'change_30s_pct':3}]}))
        self.assertGreater(len(plan['ideas']),0)
        self.assertTrue(all(x.get('oos_validated') is not True for x in plan['ideas']))
        sh=ShadowArmedResearch(experimental=True)
        validated=ShadowArmedResearch()
        arm(sh);arm(validated)
        try:
            for instance in (sh,validated):
                instance.observe(now=NOW+1,quotes={'BTC-USD':('50000','50000',NOW+1)},
                    usd_rates=MARKS,route_ideas=plan['experimental_ideas'],
                    strict_quotes=True,minimum_advantage='.10',risk_budgets=BUDGET)
            self.assertGreater(sh.snapshot()['shadow_fifo_posted_routes'],0)
            self.assertEqual(validated.snapshot()['shadow_fifo_posted_routes'],0)
            self.assertEqual(sh.snapshot()['real_order_submissions'],0)
        finally:
            for x in (sh,validated):
                for p in x.fifo_portfolios.values():p.close()
