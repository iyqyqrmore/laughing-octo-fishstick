"""v60.2: single live-readonly route planner, multi-asset inventory, safe shadow FIFO.
No Coinbase network, no real broker, no local financial-ledger writes.
"""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_shadow_preferences import load, save, validate_amount
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio

TS=1800000000
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'0.01'}

class UnifiedFundingResearch(unittest.TestCase):
    def screen(self,buy=None):
        return auto_rotation_screen(
            buy_signals=buy or [],
            holdings=[{'asset':'USD','remaining_qty':'151.33','enabled':1},
                      {'asset':'USDC','remaining_qty':'88.67','enabled':1}],
            verified_balances={'USD':'151.33','USDC':'88.67'}, balance_age_s=10,
            catalog=['BTC-USD','USDC-USD'],
            quotes={'BTC-USD':('49990','50000',TS), 'USDC-USD':('0.9999','1.0000',TS)},
            product_rules={'BTC-USD':RULE,'USDC-USD':RULE},
            usd_per_order_cap=Decimal('100000000'),now=TS,
            fee_rates_by_pair={'BTC-USD':Decimal('.009'),'USDC-USD':Decimal('.009')},
            minimum_net_advantage_usd='0.10')
    def test_one_planner_values_both_coin_sources_without_buy(self):
        out=self.screen()
        self.assertEqual(out['state'],'WAIT')
        self.assertEqual(out['funding_assets'],2)
        self.assertGreater(out['funding_inventory_usd'],Decimal('239'))
        self.assertEqual(out['route_attempts'],0)
        self.assertEqual(out['funding_size_observations']['source_assets'],2)
        self.assertEqual(out['threshold_research']['state'],'NO_HELD_OUT_EVIDENCE')
        self.assertFalse(out['ideas'])
    def test_combined_route_uses_each_native_source_once(self):
        out=self.screen([{'action':'BUY','pair':'BTC-USD','momentum_pct':'1.5'}])
        self.assertGreater(out['route_attempts'],0)
        self.assertEqual(out['multi_source_research'],1)
        candidates=[i for i in out['ideas'] if i['source']=='MULTI']
        # The combined proposal is research, never a falsely OOS-validated fill.
        self.assertTrue(candidates, 'Best pool must stay visible in shortlist')
        basket=candidates[0]
        self.assertEqual(set(basket['funding_inputs']),{'USD','USDC'})
        self.assertEqual(len(basket['route']),3)
        self.assertFalse(basket['oos_validated'])
        self.assertFalse(basket['sends_live_orders'])
        self.assertEqual(basket['research_decision'],'JOINT_FORWARD_EVIDENCE_REQUIRED')
        self.assertGreater(basket['research_size_cap_usd'],Decimal('150'))
        self.assertTrue(all(step['input_quantity']>0 for step in basket['shadow_fifo_steps']))
    def test_research_limits_not_manual_order_limits(self):
        out=self.screen([{'action':'BUY','pair':'BTC-USD','momentum_pct':'1.5'}])
        self.assertGreater(max(i['research_size_cap_usd'] for i in out['ideas']),Decimal('100'))
        self.assertNotIn('broker',str(out['threshold_research']).lower())

class MultiLegFIFO(unittest.TestCase):
    def test_three_steps_commit_and_late_failure_rolls_back_atomically(self):
        wallet=ShadowFIFOPortfolio({'USD':'100','USDC':'100'}, {'USD':'1','USDC':'1','BTC':'50000'})
        legs=[
            dict(pair='USDC-USD',side='SELL',gross_base_quantity=Decimal('50'),
                 input_quantity=Decimal('50'),output_quantity=Decimal('49.5'),fee_rate_used=Decimal('.01')),
            dict(pair='BTC-USD',side='BUY',gross_base_quantity=Decimal('.0005'),
                 input_quantity=Decimal('25.25'),output_quantity=Decimal('.0005'),fee_rate_used=Decimal('.01')),
            dict(pair='BTC-USD',side='BUY',gross_base_quantity=Decimal('.0002'),
                 input_quantity=Decimal('10.1'),output_quantity=Decimal('.0002'),fee_rate_used=Decimal('.01')),
        ]
        try:
            before=wallet.balances()
            wrong=[*legs[:2],dict(legs[2],input_quantity=Decimal('90000'))]
            with self.assertRaises(Exception):
                wallet.post_hypothetical_route(session_id='SHADOW-MULTI-BAD',steps=wrong,
                    usd_rates={'USD':'1','USDC':'1','BTC':'50000'},at_utc=TS)
            self.assertEqual(wallet.balances(),before)
            self.assertEqual(wallet.db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],0)
            result=wallet.post_hypothetical_route(session_id='SHADOW-MULTI-GOOD',steps=legs,
                usd_rates={'USD':'1','USDC':'1','BTC':'50000'},at_utc=TS)
            self.assertEqual(result['steps'],3)
            self.assertEqual(wallet.db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],3)
            snapshot=wallet.balances()
            wallet.post_hypothetical_route(session_id='SHADOW-MULTI-GOOD',steps=legs,
                usd_rates={'USD':'1','USDC':'1','BTC':'50000'},at_utc=TS)
            self.assertEqual(wallet.balances(),snapshot)
        finally:wallet.close()

class ManualFloorPersistence(unittest.TestCase):
    def test_cent_precision_and_no_exponential_or_three_decimal(self):
        for n in ('0.10','0.14','0.35','1.00','100.00','10000'):
            self.assertEqual(validate_amount(n),Decimal(n))
        for n in ('0.001','0.145','0','10000.01','1e3','Infinity','NaN'):
            with self.assertRaises(ValueError): validate_amount(n)
    def test_manual_override_survives_restart_and_ai_does_not_edit_it(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'prefs.json'
            save(path,'MANUAL','1.00')
            self.assertEqual(load(path),{'mode':'MANUAL','manual_usd':Decimal('1.00')})
            save(path,'AI_SUGGESTED','1.00')
            self.assertEqual(load(path),{'mode':'AI_SUGGESTED','manual_usd':Decimal('1.00')})
            save(path,'MANUAL','0.14')
            self.assertEqual(load(path)['manual_usd'],Decimal('0.14'))
            self.assertEqual(list(Path(d).glob('*.tmp')),[])
    def test_bad_file_fails_to_safe_default(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'bad.json';path.write_text('{')
            self.assertEqual(load(path)['manual_usd'],Decimal('.10'))

if __name__=='__main__':unittest.main()

class ThresholdResearch(unittest.TestCase):
    def test_all_cent_floors_swept_without_duplication_or_ai_trade_permission(self):
        from coincat_rotation_autopilot import threshold_sweep
        def item(src,target,net):
            return {'source':src,'target':target,'trigger_pair':target+'-USD',
                    'net_p10_usd':Decimal(net),'oos_validated':True,
                    'research_decision':'SWITCH_WORTH_RESEARCH'}
        rows=[item('ETH','BTC','0.14'),item('ETH','BTC','0.35'),
              item('SOL','BTC','0.55'),item('USD','BTC','1.01')]
        outcome=threshold_sweep(rows)
        self.assertEqual(outcome['comparison_floors'],9991)
        self.assertEqual(outcome['qualified_route_families'],3) # duplicate sized ETH family
        self.assertEqual(outcome['counts_at_floors'],{
            '0.10':3,'0.14':3,'0.35':3,'0.55':2,'1.00':1,'100.00':0})
        self.assertIsNone(outcome['recommended_floor_usd'])
        self.assertFalse(outcome['selection_authorized'])
    def test_unproven_samples_are_not_threshold_evidence(self):
        from coincat_rotation_autopilot import threshold_sweep
        out=threshold_sweep([{'source':'USD','target':'BTC','trigger_pair':'BTC-USD',
            'net_p10_usd':Decimal('50'),'oos_validated':False,
            'research_decision':'SWITCH_WORTH_RESEARCH'}])
        self.assertEqual(out['state'],'NO_HELD_OUT_EVIDENCE')
        self.assertEqual(out['qualified_route_families'],0)
