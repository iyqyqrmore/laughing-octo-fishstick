"""v60.5: GPU research handoff + isolated evolving multi-currency SHADOW.
Offline synthetic prices only. No exchange clients or real order posting.
"""
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from coincat_v507_shadow_arm import ShadowArmedResearch
from coincat_v605_shadow_bridge import shadow_screen
from coincat_rotation_autopilot import auto_rotation_screen

NOW=1770000000
MARKS={'USD':'1','USDC':'1','BTC':'50000','ETH':'2000'}
BOOKS={'BTC-USD':('50000','50000',NOW+5),'USDC-USD':('1','1',NOW+5),
       'ETH-USD':('2000','2000',NOW+5)}
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'0.01'}
STEPS=[
    dict(pair='USDC-USD',side='SELL',gross_base_quantity=Decimal('80'),
         input_quantity=Decimal('80'),output_quantity=Decimal('79.2'),fee_rate_used=Decimal('.01')),
    dict(pair='BTC-USD',side='BUY',gross_base_quantity=Decimal('.001'),
         input_quantity=Decimal('50.5'),output_quantity=Decimal('.001'),fee_rate_used=Decimal('.01')),
    dict(pair='BTC-USD',side='BUY',gross_base_quantity=Decimal('.0015'),
         input_quantity=Decimal('75.75'),output_quantity=Decimal('.0015'),fee_rate_used=Decimal('.01')),
]
RISK={'per_order_usd':'100','incremental_exposure_usd':'200',
      'daily_buy_usd':'200','max_attempts':'12'}

def multi():
    return {'source':'MULTI','target':'BTC','trigger_pair':'BTC-USD',
      'funding_inputs':{'USDC':Decimal('80'),'USD':Decimal('50.5')},
      'input_units_planned':Decimal('0'),'source_units':Decimal('0'),
      'destination_units_estimate':Decimal('.0025'),
      'shadow_fifo_steps':STEPS,'research_size_cap_usd':Decimal('130.5'),
      'net_p10_usd':Decimal('.14'),
      'research_decision':'SHADOW_COMPONENT_SCREENED',
      'oos_validated':False,'shadow_simulation_eligible':True,
      'joint_heldout_portfolio_validated':False}

class EvolvingShadow(unittest.TestCase):
    def setUp(self):
        self.sh=ShadowArmedResearch(mark_horizon_s=20)
        self.sh.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
                    usd_coverage=True,enrolled_quantities={'USD':'100','USDC':'100'},
                    fresh_usd_rates=MARKS,now=NOW)
    def tearDown(self):
        for portfolio in self.sh.fifo_portfolios.values():portfolio.close()
    def observe(self,ideas,now=NOW+5,books=None,risk=None,floor='.10'):
        return self.sh.observe(now=now,quotes=BOOKS if books is None else books,
            usd_rates=MARKS,route_ideas=ideas,minimum_advantage=floor,
            strict_quotes=True,risk_budgets=RISK if risk is None else risk)
    def test_combined_3_legs_evolve_wallet_and_original_hold_remains_unchanged(self):
        self.observe([multi()])
        s=self.sh.snapshot()
        self.assertEqual(s['shadow_fifo_posted_legs'],3)
        self.assertEqual(s['modeled_basket_scenarios'],4)  # price-band research scenarios
        self.assertEqual(s['rolling_24h_model_attempts'],3)
        after=self.sh.model_balances()
        self.assertEqual(after['USDC'],Decimal('20'))
        self.assertEqual(after['USD'],Decimal('52.95'))
        self.assertEqual(after['BTC'],Decimal('.0025'))
        self.assertEqual(self.sh.fifo_portfolios['TAKER_ASK'].start,
            {'USD':Decimal('100'),'USDC':Decimal('100')})
        self.assertEqual(s['real_order_submissions'],0)
        self.assertFalse(s['execution_certified'])
        self.assertLess(Decimal(s['shadow_fifo_bands']['TAKER_ASK']['counterfactual_portfolio_vs_hold_usd']),0)
    def test_follow_on_uses_acquired_coin_without_reinitializing_wallet(self):
        self.observe([multi()])
        second=dict(pair='BTC-USD',side='SELL',gross_base_quantity=Decimal('.001'),
            input_quantity=Decimal('.001'),output_quantity=Decimal('49.5'),fee_rate_used=Decimal('.01'))
        next_idea={'source':'BTC','target':'USD','trigger_pair':'BTC-USD',
            'input_units_planned':Decimal('.001'),'destination_units_estimate':Decimal('49.5'),
            'shadow_fifo_steps':[second],'net_p10_usd':Decimal('.25'),
            'research_decision':'SWITCH_WORTH_RESEARCH','oos_validated':True,
            'research_size_cap_usd':Decimal('50')}
        self.observe([next_idea],now=NOW+10,books={**BOOKS,'BTC-USD':('50000','50000',NOW+10)})
        bal=self.sh.model_balances()
        self.assertEqual(bal['BTC'],Decimal('.0015'))
        self.assertEqual(bal['USD'],Decimal('102.45'))
        self.assertEqual(self.sh.snapshot()['rolling_24h_model_attempts'],4)
    def test_minimum_is_lower_bound_not_upper_band(self):
        high=multi();high['net_p10_usd']=Decimal('12.00')
        self.observe([high])
        self.assertEqual(self.sh.snapshot()['shadow_fifo_posted_legs'],3)
    def test_joint_unverified_does_not_count_as_certified(self):
        not_ready=multi();not_ready['shadow_simulation_eligible']=False
        self.observe([not_ready])
        self.assertEqual(self.sh.snapshot()['shadow_fifo_posted_legs'],0)
    def test_stale_quotes_reject_instead_of_imputed_fill(self):
        self.observe([multi()],books={'BTC-USD':BOOKS['BTC-USD']})
        s=self.sh.snapshot()
        self.assertEqual(s['shadow_fifo_posted_legs'],0)
        self.assertGreater(s['rejected_quote_freshness_or_drift'],0)
    def test_model_daily_and_per_order_budget_block(self):
        self.observe([multi()],risk={**RISK,'per_order_usd':'10'})
        self.assertEqual(self.sh.snapshot()['shadow_fifo_posted_legs'],0)
        self.assertGreater(self.sh.snapshot()['rejected_shadow_budget'],0)
    def test_strict_limit_price_touch_is_not_counterfeit_fill(self):
        self.observe([multi()])
        before=self.sh.fifo_portfolios['LIMIT_ASK_MINUS_5BPS'].balances()
        later={**BOOKS,'BTC-USD':('49960','49970',NOW+11),
               'USDC-USD':('1','1',NOW+11),'ETH-USD':('2000','2000',NOW+11)}
        self.observe([],now=NOW+11,books=later)
        self.assertEqual(self.sh.fifo_portfolios['LIMIT_ASK_MINUS_5BPS'].balances(),before)
        self.assertGreater(self.sh.snapshot()['passive_price_touches_without_fill_proof'],0)
    def test_no_duplicate_simultaneous_plan_and_rolling_attempt_gate(self):
        self.observe([multi(),multi()])
        self.assertEqual(self.sh.snapshot()['rolling_24h_model_attempts'],3)
        new=multi();new['target']='ETH';new['trigger_pair']='ETH-USD';new['research_size_cap_usd']=Decimal('100')
        new['shadow_fifo_steps']=[dict(pair='ETH-USD',side='BUY',gross_base_quantity=Decimal('.01'),
            input_quantity=Decimal('20.2'),output_quantity=Decimal('.01'),fee_rate_used=Decimal('.01'))]
        new['destination_units_estimate']=Decimal('.01')
        new['funding_inputs']={'USD':Decimal('20.2')}
        new['net_p10_usd']=Decimal('4')
        self.observe([new],now=NOW+10,books={k:(v[0],v[1],NOW+10) for k,v in BOOKS.items()},risk={**RISK,'max_attempts':'3'})
        self.assertEqual(self.sh.snapshot()['rolling_24h_model_attempts'],3)

class OnePlannerGpuFlow(unittest.TestCase):
    def test_gpu_only_reorders_existing_buy_no_auto_signal(self):
        from coincat_rotation_autopilot import auto_rotation_screen
        signals=[{'action':'BUY','pair':'BTC-USD','momentum_pct':'4'},
                 {'action':'BUY','pair':'ETH-USD','momentum_pct':'1'}]
        fake_balances={'USD':'100'}
        common=dict(buy_signals=signals,holdings=[{'asset':'USD','remaining_qty':'100','enabled':1}],
            verified_balances=fake_balances,balance_age_s=5,
            catalog=['BTC-USD','ETH-USD'],quotes=BOOKS,now=NOW+5,
            usd_per_order_cap=Decimal('100'),product_rules={'BTC-USD':RULE,'ETH-USD':RULE},
            fee_rates_by_pair={'BTC-USD':Decimal('.01'),'ETH-USD':Decimal('.01')})
        out=auto_rotation_screen(**common,gpu_advisories={'ETH-USD':{'status':'ADVISORY','probabilities':{'BUY':'.85'}},
            'BTC-USD':{'status':'ADVISORY','probabilities':{'BUY':'.2'}}})
        self.assertEqual(out['considered'],2)
        pairs=[i['trigger_pair'] for i in out['ideas'] if i['source']!='MULTI']
        self.assertTrue(pairs)
        self.assertEqual(pairs[0],'ETH-USD') if all(i['research_decision']==out['ideas'][0]['research_decision'] for i in out['ideas'] if i['source']!='MULTI') else None
        no_signals=auto_rotation_screen(**{**common,'buy_signals':[]},gpu_advisories={'BTC-USD':{'status':'ADVISORY','probabilities':{'BUY':'.99'}}})
        self.assertEqual(no_signals['considered'],0)
        self.assertEqual(no_signals['switch_worth_research'],0)
    def test_shadow_bridge_only_uses_evolved_inventory_and_respects_exclusions(self):
        out=shadow_screen(balances={'BTC':'0.0025','USD':'52.95'},excluded=['ETH'],
            buy_signals=[{'action':'BUY','pair':'ETH-USD','momentum_pct':'1'}],age_s=5,
            catalog=['BTC-USD','ETH-USD'],quotes=BOOKS,
            product_rules={'BTC-USD':RULE,'ETH-USD':RULE},
            portfolio_usd_cap=Decimal('300'),now=NOW+5,
            fee_rates_by_pair={'ETH-USD':Decimal('.01')},relative_evidence=None)
        self.assertEqual(out['funding_assets'],2)
        self.assertEqual(out['considered'],0)
    def test_no_post_import_or_hidden_manual_gpu_button(self):
        base=Path(__file__).resolve().parents[1]/'app'
        bridge=(base/'coincat_v605_shadow_bridge.py').read_text()
        app=(base/'coincat_app.py').read_text()
        self.assertNotIn('create_order(',bridge)
        self.assertNotIn('submit_order(',bridge)
        self.assertNotIn('self.gpu_button=',app)
        self.assertIn('gpu_advisories=result[\'gpu_advisory\']',app)
        self.assertIn('strict_quotes=True',app)

if __name__=='__main__':unittest.main()
