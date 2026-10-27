"""Exact decimal Snowball research tests. No network or actual Coinbase orders."""
import sys,unittest,time
from pathlib import Path
from decimal import Decimal
APP=Path(__file__).resolve().parents[1]/'app'
if str(APP) not in sys.path:sys.path.insert(0,str(APP))
from coincat_snowball import assess_idea,screen,report
from coincat_break_even import one_order_reference,required_moves
from coincat_v507_shadow_arm import ShadowArmedResearch

class SnowballResearch(unittest.TestCase):
    def setUp(self):
        self.now=1_800_000_000
        self.quotes={'SOL-ETH':('0.1100','0.1101',self.now-2),
            'SOL-USD':('10','10.01',self.now-1),
            'ETH-USD':('100','100.02',self.now-3)}
        self.idea={'source':'SOL','target':'ETH','trigger_pair':'SOL-ETH',
                   'input_units_planned':Decimal('10'),
                   'destination_units_estimate':Decimal('1.0901'),
                   'research_size_cap_usd':Decimal('100'),
                   'observed_momentum_pct':Decimal('0'),
                   'immediate_change_usd':Decimal('-1.0'),
                   'sends_live_orders':False,
                   'shadow_fifo_steps':[{'pair':'SOL-ETH','side':'SELL',
                       'gross_base_quantity':'10','input_quantity':'10',
                       'output_quantity':'1.0901','fee_rate_used':'.009'}]}
    def test_immediate_opportunity_can_be_positive_without_momentum(self):
        r=assess_idea(self.idea,self.quotes,now=self.now,taker_fee=Decimal('.009'))
        self.assertEqual('IMMEDIATE_ESTIMATE',r['state'])
        self.assertGreater(r['delta_usd'],Decimal('7'))
        ideas,s=screen([self.idea],self.quotes,now=self.now,taker_fee=Decimal('.009'),minimum_usd='0.10')
        self.assertEqual(1,s['above_floor'])
        self.assertEqual('PROVISIONAL_IMMEDIATE_GAIN_RESEARCH_ONLY',s['status'])
        self.assertFalse(s['live_order_authorized'])
        exp=ShadowArmedResearch(experimental=True)
        self.assertGreater(exp._experimental_score(ideas[0],{'SOL':'10','ETH':'100'}),Decimal('7'))
    def test_immediate_loss_not_false_gain_and_legacy_two_leg_retained_only(self):
        loser=dict(self.idea,destination_units_estimate=Decimal('.89'))
        loser['shadow_fifo_steps']=[dict(self.idea['shadow_fifo_steps'][0],output_quantity='.89')]
        r=assess_idea(loser,self.quotes,now=self.now,taker_fee=Decimal('.009'))
        self.assertEqual('ENTRY_PRICE_DRIFT',r['reason'])
        neg=dict(self.idea,destination_units_estimate=Decimal('1.0901'))
        reduced=dict(self.quotes,**{'SOL-ETH':('0.1100','0.1101',self.now-2),'SOL-USD':('11','11.01',self.now-1)})
        self.assertLess(assess_idea(neg,reduced,now=self.now,taker_fee=Decimal('.009'))['delta_usd'],0)
        single=one_order_reference(Decimal('.009'))
        self.assertGreater(single['one_order_recovery_pct'],Decimal('1.05'))
        self.assertLess(single['one_order_recovery_pct'],Decimal('1.07'))
        self.assertGreater(required_moves('100','0.10',fee_per_leg=Decimal('.009'))['break_even_pct'],Decimal('2.1'))
    def test_stale_skew_wide_quote_and_missing_fee_fail_closed(self):
        for quotes in (
            dict(self.quotes,**{'SOL-ETH':('0.11','0.1101',self.now-31)}),
            dict(self.quotes,**{'SOL-USD':('10','10.01',self.now-21)}),
            dict(self.quotes,**{'ETH-USD':('100','105',self.now-2)})):
            self.assertEqual('NOT_VERIFIED',assess_idea(self.idea,quotes,now=self.now,taker_fee=Decimal('.009'))['state'])
        self.assertEqual('FEE_UNVERIFIED',assess_idea(self.idea,self.quotes,now=self.now,taker_fee=None)['reason'])
        self.assertEqual('RECEIPT_OR_FEE_MISMATCH',assess_idea(self.idea,self.quotes,now=self.now,taker_fee=Decimal('.005'))['reason'])
    def test_momentum_scenario_not_hidden_by_small_immediate_estimate(self):
        idea=dict(self.idea, observed_momentum_pct=Decimal('2'),
                  snowball_state='IMMEDIATE_ESTIMATE',snowball_immediate_usd='.01')
        score=ShadowArmedResearch(experimental=True)._experimental_score(idea,{})
        self.assertEqual(Decimal('1.0'),score)

    def test_direct_usd_route_suffers_cost_drag_not_missing_fx(self):
        idea={'source':'USD','target':'SOL','trigger_pair':'SOL-USD',
              'input_units_planned':'100.9','destination_units_estimate':'.01',
              'research_size_cap_usd':'100.9', 'observed_momentum_pct':'0',
              'sends_live_orders':False,'shadow_fifo_steps':[{
                'pair':'SOL-USD','side':'BUY','gross_base_quantity':'.01',
                'input_quantity':'100.9','output_quantity':'.01','fee_rate_used':'.009'}]}
        result=assess_idea(idea,{'SOL-USD':('9990','10000',self.now-1)},now=self.now,
                           taker_fee=Decimal('.009'))
        self.assertEqual('IMMEDIATE_ESTIMATE',result['state'])
        self.assertLess(result['delta_usd'],0)

    def test_no_two_leg_promotion_or_live_permission(self):
        idea=dict(self.idea,shadow_fifo_steps=self.idea['shadow_fifo_steps']*2)
        self.assertEqual('NOT_SINGLE_ORDER',assess_idea(idea,self.quotes,now=self.now,taker_fee=Decimal('.009'))['reason'])
        live=dict(self.idea,sends_live_orders=True)
        self.assertEqual('NOT_RESEARCH_ONLY',assess_idea(live,self.quotes,now=self.now,taker_fee=Decimal('.009'))['reason'])
    def test_existing_experimental_fifo_only_and_regular_not_armed(self):
        annotated,summary=screen([self.idea],self.quotes,now=self.now,taker_fee=Decimal('.009'),minimum_usd='.10')
        validated=ShadowArmedResearch();experimental=ShadowArmedResearch(experimental=True)
        experimental.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'SOL':'10'},fresh_usd_rates={'SOL':'10','ETH':'100'},now=self.now-1)
        experimental.observe(now=self.now,quotes=self.quotes,usd_rates={'SOL':'10','ETH':'100'},
            route_ideas=annotated,minimum_advantage='.10',risk_budgets=None,strict_quotes=True)
        self.assertEqual(1,experimental.snapshot()['shadow_fifo_posted_routes'])
        self.assertEqual(0,validated.snapshot()['shadow_fifo_posted_routes'])
        self.assertEqual('DISARMED', 'DISARMED' if not validated.armed else 'ARMED')
        self.assertIn('LIVE BLOCKED',report(summary))
    def test_source_matches_single_engine_and_gui_label(self):
        src=(APP/'coincat_app.py').read_text()
        self.assertIn('SNOWBALL • COST & USD ADVANTAGE',src)
        self.assertNotIn('SNOWBALL â€¢ COST & USD ADVANTAGE',src)
        self.assertNotIn("text='◉  BREAK-EVEN ADVISOR'",src)
        self.assertIn('snowball_screen(',src)
        self.assertIn('strict_quotes=True',src)
        broker=(APP/'coincat_live.py').read_text()
        self.assertIn('LiveBlocked',broker)
if __name__=='__main__':unittest.main()
