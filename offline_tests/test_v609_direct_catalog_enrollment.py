"""v60.9 synthetic direct-pair and auto-enrollment tests. No Coinbase API."""
import tempfile,unittest,ast
from pathlib import Path
from decimal import Decimal
from coincat_v609_direct import direct_crypto_pairs,distinct_catalog_assets
from coincat_multicurrency import evaluate_rotation
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_live import LiveLedger

NOW=1800000000
CAT=['ADA-SOL','ADA-USD','SOL-USD','DOGE-USD','LINK-BTC']
QUOTES={'ADA-SOL':('0.02','0.02002',NOW), 'ADA-USD':('0.70','0.701',NOW),
        'SOL-USD':('35','35.05',NOW),'DOGE-USD':('.10','.1001',NOW),
        'LINK-BTC':('.0001','.0001002',NOW)}
RULES={p:{'base_increment':'.00000001','base_min_size':'.00001',
          'quote_min_size':'.000001'} for p in CAT}
class Direct(unittest.TestCase):
    def test_only_authenticated_direct_nonstable_coin_products(self):
        self.assertEqual(direct_crypto_pairs(CAT),['ADA-SOL','LINK-BTC'])
    def test_sol_to_ada_one_order_no_bridge(self):
        result=evaluate_rotation(source='SOL',target='ADA',authorized_qty='1',
            verified_available_qty='1',balance_age_s=0,catalog=CAT,quotes=QUOTES,
            now=NOW,usd_per_order_cap='100',product_rules=RULES,fee_rate='.009',
            max_legs=1,crypto_only=True)
        self.assertEqual(result['state'],'RESEARCH ONLY')
        self.assertEqual(result['routes'][0]['route'],(('ADA-SOL','BUY'),))
        self.assertEqual(len(result['routes'][0]['steps']),1)
        self.assertLess(result['routes'][0]['immediate_change_usd'],0)
    def test_direct_order_updates_shadow_fifo_and_new_coin_can_refuel(self):
        from coincat_v507_shadow_fifo import ShadowFIFOPortfolio
        catalog=CAT+['LINK-ADA','LINK-USD']
        books=dict(QUOTES,**{'LINK-ADA':('2','2.002',NOW),'LINK-USD':('1.4','1.401',NOW)})
        rules=dict(RULES,**{'LINK-ADA':RULES['ADA-SOL'],'LINK-USD':RULES['ADA-SOL']})
        wallet=ShadowFIFOPortfolio({'SOL':'1'}, {'SOL':'35','ADA':'.70','LINK':'1.4'})
        try:
            one=evaluate_rotation(source='SOL',target='ADA',authorized_qty='1',
              verified_available_qty='1',balance_age_s=0,catalog=catalog,quotes=books,
              now=NOW,usd_per_order_cap='100',product_rules=rules,fee_rate='.009',
              max_legs=1,crypto_only=True)['routes'][0]
            result=wallet.post_hypothetical_route(session_id='SHADOW-DIRECT-FIRST',
                steps=one['steps'],usd_rates={'SOL':'35','ADA':'.70','LINK':'1.4'},at_utc=NOW)
            self.assertEqual(result['steps'],1)
            available=wallet.balances()['ADA']
            second=evaluate_rotation(source='ADA',target='LINK',authorized_qty=available,
              verified_available_qty=available,balance_age_s=0,catalog=catalog,quotes=books,
              now=NOW,usd_per_order_cap='100',product_rules=rules,fee_rate='.009',
              max_legs=1,crypto_only=True)
            self.assertTrue(second['routes'])
            result=wallet.post_hypothetical_route(session_id='SHADOW-DIRECT-SECOND',
                steps=second['routes'][0]['steps'],
                usd_rates={'SOL':'35','ADA':'.70','LINK':'1.4'},at_utc=NOW+2)
            self.assertEqual(result['steps'],1)
            self.assertGreater(wallet.balances().get('LINK',0),0)
            self.assertEqual(wallet.legs,2)
        finally:wallet.close()
    def test_missing_direct_pair_does_not_bridge_usd(self):
        res=evaluate_rotation(source='DOGE',target='ADA',authorized_qty='100',
            verified_available_qty='100',balance_age_s=0,catalog=CAT,quotes=QUOTES,
            now=NOW,usd_per_order_cap='100',product_rules=RULES,fee_rate='.009',
            max_legs=1,crypto_only=True)
        self.assertEqual(res['routes'],[])
    def test_usd_assets_cannot_be_funding_or_destination(self):
        res=evaluate_rotation(source='USD',target='ADA',authorized_qty='10',
            verified_available_qty='10',balance_age_s=0,catalog=CAT,quotes=QUOTES,
            now=NOW,usd_per_order_cap='10',product_rules=RULES,fee_rate='.009',
            max_legs=1,crypto_only=True)
        self.assertEqual(res['state'],'WAIT')
    def test_shared_planner_one_leg_only_with_strategy(self):
        outcome=auto_rotation_screen(buy_signals=[],holdings=[{'asset':'SOL','remaining_qty':'1','enabled':1}],
            verified_balances={'SOL':'1'},balance_age_s=0,catalog=CAT,quotes=QUOTES,
            product_rules=RULES,usd_per_order_cap=Decimal('100'),now=NOW,
            fee_rates_by_pair={p:Decimal('.009') for p in CAT},
            strategy_candidates=[{'action':'EXPLORE_ONLY','sends_orders':False,'pair':'ADA-SOL','observed_pct':'1'}],
            direct_only=True,minimum_net_advantage_usd='.10')
        self.assertEqual(outcome['route_policy'],'AUTHENTICATED_SPOT_ONE_ORDER')
        self.assertGreater(outcome['strategy_route_reviews'],0)
        self.assertGreater(outcome['one_order_routes_evaluated'],0)
        self.assertTrue(outcome['ideas'])
        self.assertTrue(all(len(i['route'])==1 for i in outcome['ideas'] if i.get('source')!='MULTI'))
        self.assertFalse(any(i.get('sends_live_orders') for i in outcome['ideas']))
        self.assertFalse(any(i.get('oos_validated') for i in outcome['ideas']))
    def test_catalog_browsing_holdings_pinned_unique(self):
        catalog=distinct_catalog_assets(CAT,{'SOL':'1','DOGE':'5'}, {'ADA':{'enabled':0}})
        self.assertEqual(catalog[:2],['DOGE','SOL'])
        self.assertEqual(catalog[2],'ADA')
        self.assertEqual(len(catalog),len(set(catalog)))
        self.assertIn('LINK',catalog)
class Enrollment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ledger=LiveLedger(Path(self.temp.name)/'ledger.sqlite3')
        self.ledger.initial_auto_enroll_if_empty({'SOL':'1','ADA':'5'})
        self.ledger.set_asset_enabled('ADA',False)
    def tearDown(self):self.temp.cleanup()
    def test_new_asset_auto_enroll_unknown_original_basis_and_exclusion_holds(self):
        a=self.ledger.auto_enroll_new_spot_available({'SOL':'1','ADA':'5','LINK':'4','XYZ':'5'}, {'SOL','ADA','LINK'})
        self.assertEqual(a['created'],1)
        entries={r['asset']:r for r in self.ledger.assets()}
        self.assertTrue(entries['LINK']['enabled'])
        self.assertIsNone(entries['LINK']['basis_unit_quote'])
        self.assertEqual(entries['LINK']['remaining_qty'],'4')
        self.assertEqual(entries['LINK']['basis_source'],'EXTERNAL_AVAILABLE_UNVERIFIED_BASIS')
        self.assertEqual(entries['ADA']['enabled'],0)
        self.assertEqual(entries['SOL']['remaining_qty'],'1')
        self.assertNotIn('XYZ',entries)
        self.assertEqual(self.ledger.auto_enroll_new_spot_available({'LINK':'7','SOL':'4'}, {'SOL','LINK'})['created'],0)
        self.assertEqual({r['asset']:r for r in self.ledger.assets()}['LINK']['remaining_qty'],'4')
    def test_existing_unresolved_orders_blocks_new_enrollment(self):
        from coincat_live import sql
        with sql(self.ledger.path) as c:
            c.execute("INSERT INTO orders(cid,pair,side,requested_size,preview_fee,state,created_at) VALUES('U','SOL-USD','BUY','1','0','PENDING',1)")
        outcome=self.ledger.auto_enroll_new_spot_available({'LINK':'2'}, {'LINK'})
        self.assertEqual(outcome['created'],0)
        self.assertEqual(outcome['deferred'],'UNRESOLVED_ORDER')
    def test_live_submit_remains_unconditionally_blocked(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'app/coincat_live.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)
