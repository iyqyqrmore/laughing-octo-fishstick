"""Release checks: no legacy research cap, honest blockers, persistent SHADOW caps,
private report no exact balance disclosure. No Coinbase/real ledger or orders.
"""
import tempfile,unittest
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
from coincat_v606_budgets import DEFAULT,load,save,validate,effective
from coincat_v503_lab_evidence import grade_lab
from coincat_multicurrency import evaluate_rotation
from coincat_rotation_autopilot import _failure_category
from coincat_v507_shadow_arm import ShadowArmedResearch,shadow_report

class V606Behavior(unittest.TestCase):
 def test_budget_persistence_and_no_automatic_arm(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=Path(tmp)/'budgets.json'
   self.assertEqual(load(f),DEFAULT)
   saved=save(f,{'per_order_usd':'10000','daily_buy_usd':'10000',
        'added_exposure_usd':'10000','attempts_24h':'10000'})
   self.assertEqual(load(f),saved)
   applied=effective(saved,'100')
   self.assertEqual(applied['per_order_usd'],'100')
   self.assertEqual(applied['daily_buy_usd'],'10000')
   self.assertEqual(applied['incremental_exposure_usd'],'100')
   self.assertEqual(applied['max_attempts'],'10000')
   self.assertTrue(applied['clamped'])
   self.assertIsNone(effective(saved,'0'))
   self.assertFalse(hasattr(__import__('coincat_v606_budgets'),'arm'))
 def test_reject_invalid_and_no_secret_keys(self):
  for change in ({'per_order_usd':'nan'},{'per_order_usd':'-1'}, {'attempts_24h':'1.5'},
                 {'added_exposure_usd':'Infinity'},{'daily_buy_usd':'0'}):
   with self.subTest(change=change):
    with self.assertRaises(ValueError):validate(dict(DEFAULT,**change))
 def test_ai_lab_research_advisory_not_constrained_by_manual_caps(self):
  idea={'research_decision':'SWITCH_WORTH_RESEARCH','oos_validated':True,
        'net_p10_usd':Decimal('2'),'net_mean_usd':Decimal('2'),
        'initial_wallet_usd_mark':'500','source_units':'5','input_units_planned':'5'}
  summary=grade_lab(route_ideas=[idea],fee_fresh=True,usd_complete=True,
        scan_fresh=True,current_order_budget='10',minimum_net_advantage_usd='.10')
  self.assertEqual(summary['research_preferred_order_usd'],Decimal('500'))
  self.assertFalse(summary['authorizes_order'])
 def test_route_failure_not_false_missing_conversion(self):
  now=1700000000
  r=evaluate_rotation(source='ETH',target='BTC',authorized_qty='1',verified_available_qty='1',
   balance_age_s=0,catalog=['ETH-USD','BTC-USD'],
   quotes={'ETH-USD':('2000','2001',now),'BTC-USD':('50000','50010',now)},
   now=now,usd_per_order_cap='1000',fee_rate=Decimal('.009'),
   product_rules={'ETH-USD':{'base_increment':'.0001','base_min_size':'999',
                            'quote_min_size':'1','base_max_size':'1000000'},
                 'BTC-USD':{'base_increment':'.000001','base_min_size':'.000001',
                            'quote_min_size':'1','base_max_size':'100000'}})
  self.assertEqual(r['state'],'WAIT')
  self.assertNotIn('conversion',r['reason'].lower())
  self.assertIn('Coinbase pair minimum/maximum or rounded size blocks SELL',r['route_rejections'])
  self.assertEqual(_failure_category(r),'PRODUCT_RULES_OR_MINIMUMS')
  self.assertEqual(_failure_category({'reason':'No fresh conservative USD conversion for source and destination'}),'MISSING_USD_CONVERSION')
 def test_shadow_report_redacts_exact_funds(self):
  s=ShadowArmedResearch()
  s.arm(connected=True,real_arm=False,stopped=False,
        verified_balances={'BTC':'0.123456789','USD':'27.17'},usd_coverage=True,
        enrolled_quantities={'BTC':'0.123456789','USD':'27.17'},
        fresh_usd_rates={'BTC':'50000','USD':'1'})
  report=shadow_report(SimpleNamespace(shadow_pilot=s))
  self.assertIn('REDACTED',report)
  self.assertNotIn('0.123456789',report)
  self.assertNotIn('27.17',report)
  self.assertNotIn("'BTC':",report)
  for wallet in s.fifo_portfolios.values():wallet.close()

if __name__=='__main__':unittest.main()
