"""Offline fast opportunity scheduler and source safety; no network, no trade calls."""
import sys, unittest, ast
from pathlib import Path
from decimal import Decimal
APP=Path(__file__).resolve().parents[1]/'app'
if str(APP) not in sys.path:sys.path.insert(0,str(APP))
from coincat_v6018_fast_path import select_fast_books,fast_candidates,fast_funnel,MAX_FAST_BOOKS
class FastSnowballTests(unittest.TestCase):
    def test_only_real_direct_funding_and_bounded_rest(self):
        pairs=['SOL-USDC','ETH-USDC','BTC-USD','SOL-USD','ETH-USD','USDC-USD',
               'ABC-USDT','XYZ-BTC','LINK-USDC']
        plan=select_fast_books(['ABC-USDT','SOL-USDC','XYZ-BTC','GHOST-USD','SOL-USD'],
            pairs,['USDC','BTC'],limit=100000)
        self.assertEqual(['SOL','XYZ'],[a for a,p in plan['targets']])
        self.assertTrue(set(plan['books']).issubset(set(pairs)))
        self.assertLessEqual(len(plan['books']),MAX_FAST_BOOKS)
        self.assertIn('SOL-USD',plan['books'])
    def test_eligibility_does_not_invent_any_market(self):
        a=select_fast_books(['SOL-BTC'],['SOL-BTC'],['USD'])
        self.assertEqual([],a['targets'])
        b=select_fast_books(['SOL-BTC'],['SOL-BTC','SOL-USD'],['USD'])
        self.assertEqual(['SOL'],[t[0] for t in b['targets']])
    def test_candidates_require_fresh_actual_rest_bid_ask_and_spread(self):
        t=2_000_000_000
        snap={'rows':[{'pair':'SOL-USDC','change_30s_pct':1.2}]}
        targets=[('SOL','SOL-USDC')]
        good={'SOL-USDC':(Decimal('10'),Decimal('10.01'),t-2)}
        c,n=fast_candidates(targets,good,snap,now=t)
        self.assertEqual(1,len(c));self.assertEqual(0,n)
        self.assertEqual('EXPLORE_ONLY',c[0]['action'])
        self.assertFalse(c[0]['validated'])
        self.assertEqual(Decimal('1.2'),c[0]['momentum_pct'])
        for bad in ({'SOL-USDC':('10','11',t-1)},
                    {'SOL-USDC':('10','10.01',t-40)},{}):
            c,n=fast_candidates(targets,bad,snap,now=t)
            self.assertEqual(0,len(c));self.assertEqual(1,n)
    def test_funnel_no_fake_fill_or_live_auth(self):
        f=fast_funnel(detected=12,selected=3,fetched=9,errors=1,targets=2,
            planner={'viable_routes':4,'route_blockers':{'MINIMUM':5}},
            snowball={'priced':2,'positive':1,'above_floor':0})
        self.assertEqual(4,f['one_order_routes'])
        self.assertEqual(0,f['modeled_fills_this_event'])
        self.assertTrue(f['no_live_orders'])
    def test_same_planner_single_worker_no_submit(self):
        s=(APP/'coincat_app.py').read_text()
        self.assertIn("self._async(self._fast_cycle,operation='fast Snowball research')",s)
        self.assertIn('experimental_shadow.observe',s)
        self.assertIn('shadow_screen(',s)
        self.assertIn('auto_rotation_screen(',s)
        self.assertIn('not needs_fills',s)
        fast=s[s.index('    def _fast_cycle('):s.index('    def _cycle(')]
        self.assertNotIn('.submit_order(',fast)
        self.assertNotIn('.place_order(',fast)
        self.assertNotIn('post_order(',fast)
        self.assertNotIn('self.broker.arm(',fast)
        self.assertIn("'live_order_permission':False",fast)
        self.assertIn('MAX_FAST_BOOKS', (APP/'coincat_v6018_fast_path.py').read_text())
        for p in APP.glob('*.py'):
            ast.parse(p.read_text(encoding='utf-8'),feature_version=(3,11))
if __name__=='__main__':unittest.main()

class FastPathEndToEnd(unittest.TestCase):
    def test_real_shared_planner_synthetic_stream_gets_to_research_without_post(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        from coincat_app import CoinCatApp
        app=CoinCatApp.__new__(CoinCatApp)
        app.broker=SimpleNamespace(catalog_product_rules={})
        app.catalog=['SOL-USDC','SOL-USD','USDC-USD']
        app._last_portfolio_sync_monotonic=time.monotonic()
        app.current_balances={'USDC':'100'}
        app.external_mismatches=[]
        app.ledger=SimpleNamespace(assets=lambda:[{'asset':'USDC','remaining_qty':'100','enabled':1}])
        app.fee_learning=SimpleNamespace(latest_tier=lambda:{'fresh':True,'taker':Decimal('.009')})
        app.stream_research=SimpleNamespace(rank_for_rest_scout=lambda *a,**kw:['SOL-USDC'],
            snapshot=lambda **kw:{'rows':[{'pair':'SOL-USDC','last_trade':10,'change_30s_pct':2.4}]})
        app._fast_candidate_signature=None
        app._fast_candidate_signature_at=0
        app.experimental_shadow=SimpleNamespace(armed=False)
        app.shadow_pilot=SimpleNamespace(armed=False)
        app.relative_lab=SimpleNamespace(paired_outcomes=lambda *a,**kw:{'status':'NOT_VERIFIED'})
        app.switch_minimum_usd=Decimal('.10')
        books={}
        app.forward=SimpleNamespace(record_quote=lambda p,ts,b,a,**kw:books.update({p:(Decimal(str(b)),Decimal(str(a)),float(ts))}))
        app._shadow_valuation_books=lambda:books.copy()
        prices={'SOL-USDC':('9.98','10.00'),'SOL-USD':('9.98','10.00'),'USDC-USD':('0.999','1.001')}
        from coincat_v701_transport import QuoteSnapshot
        def synthetic_snapshot(pair,**kw):
            return QuoteSnapshot(pair,*map(Decimal,prices[pair]),time.time(),time.time(),1)
        with patch('coincat_app.fetch_snapshot',side_effect=synthetic_snapshot):
            result=app._fast_cycle()
            duplicate=app._fast_cycle()
        self.assertEqual('RESEARCHED',result['state'])
        self.assertEqual(3,result['fetched'])
        self.assertEqual('AUTHENTICATED_SPOT_ONE_ORDER',result['plan']['route_policy'])
        self.assertFalse(result['live_order_permission'])
        self.assertEqual('STREAM_PRICES_UNCHANGED_COOLDOWN',duplicate['reason'])
        self.assertIn('NO_IMMEDIATE_ADVANTAGE_VERIFIED',result['snowball']['status'])
