"""Rising-market priority within the ONE existing REST/scout/planner path.
All fixtures offline; none proves future returns or permits Coinbase orders.
"""
import sys,tempfile,unittest,time
from pathlib import Path
from decimal import Decimal
APP=Path(__file__).resolve().parents[1]/'app'
if str(APP) not in sys.path:sys.path.insert(0,str(APP))
from coincat_market_intelligence import rank_scouts,balanced_scout_priority,FocusPlanner
from coincat_live_forward_store import ForwardStore
from coincat_relative_strength_research import rank_observed_markets
from coincat_stream_research import StreamResearch

class RisingPriority(unittest.TestCase):
    def test_rest_rank_rising_before_larger_falling_and_keep_sell_scout(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForwardStore(Path(td)/'market.sqlite')
            pairs=['UP1-USD','UP2-USD','UP3-USD','UP4-USD','DOWN-USD']
            for p in pairs:
                store.record_discovery(p,1000,'100','100.05')
            for p,price in [('UP1-USD',101),('UP2-USD',102),('UP3-USD',103),('UP4-USD',104),('DOWN-USD',94)]:
                store.record_discovery(p,1100,str(price),str(price+.05))
            ranked=rank_scouts(store,pairs,now=1101)
            self.assertEqual('UP4-USD',ranked[0]['pair'])
            selected=balanced_scout_priority(ranked,4)
            self.assertIn('DOWN-USD',selected)
            self.assertEqual(4,len(selected))
            planner=FocusPlanner(store,hold_seconds=2700,promotions=4,urgent_per_cycle=4)
            focus=planner.select([],pairs,capacity=4,now=1101)
            self.assertIn('DOWN-USD',focus['watch'])
            self.assertEqual(3,focus['rising_promoted'])
            self.assertEqual(4,len(focus['watch']))
    def test_relative_strength_best_book_per_asset_and_positive_preferred(self):
        reviews=[
            {'pair':'SOL-BTC','bid':'100','ask':'100.1','count':9,'trend':'0.15'},
            {'pair':'SOL-USDC','bid':'100','ask':'100.01','count':9,'trend':'1.5'},
            {'pair':'ETH-USD','bid':'100','ask':'100.01','count':9,'trend':'-4'},
            {'pair':'ADA-USD','bid':'100','ask':'100.01','count':9,'trend':'0.4'},
        ]
        ranking=rank_observed_markets(reviews,max_targets=4)
        self.assertEqual('SOL-USDC',ranking['candidates'][0]['pair'])
        self.assertEqual(3,ranking['unique_assets'])
        self.assertEqual(2,ranking['rising_assets'])
        self.assertEqual('ETH-USD',ranking['candidates'][-1]['pair'])
        self.assertTrue(all(r['action']=='EXPLORE_ONLY' for r in ranking['candidates']))
    def test_stream_rising_scout_priority_and_downside_slot(self):
        sr=StreamResearch();now=5000
        for name,start,end in [('UP-USD',100,102),('DOWN-USD',100,94),('UP2-USD',100,101),('UP3-USD',100,101.5),('UP4-USD',100,100.5)]:
            for offset,price in ((-50,start),(-30,start),(-1,end)):
                self.assertTrue(sr.observe(name,price,at=now+offset))
        result=sr.rank_for_rest_scout(['UP-USD','DOWN-USD','UP2-USD','UP3-USD','UP4-USD'],now=now,limit=4)
        self.assertEqual('UP-USD',result[0]);self.assertIn('DOWN-USD',result)
        self.assertLessEqual(len(result),4)
    def test_no_scanner_or_execution_path_added(self):
        src=(APP/'coincat_app.py').read_text()
        self.assertEqual(1,src.count("result['auto_rotation']=auto_rotation_screen("))
        self.assertIn('rank_capacity=max(4,min(12,4+len(result[\'reviews\'])//16))',src)
        self.assertIn('max_targets=8)',src)
        self.assertIn('max_legs=1', (APP/'coincat_rotation_autopilot.py').read_text())
        for name in ('coincat_market_intelligence.py','coincat_stream_research.py','coincat_relative_strength_research.py'):
            text=(APP/name).read_text()
            for bad in ('.create_order(','.submit_order(','.buy(','.sell(','.ledger.'):
                self.assertNotIn(bad,text)

if __name__=='__main__':unittest.main()

class SharedPlannerRanking(unittest.TestCase):
    def test_rising_observation_reaches_planner_despite_existing_buy_signal(self):
        from coincat_rotation_autopilot import auto_rotation_screen
        ts=1800000000
        cat=['BTC-USD','SOL-USD']
        result=auto_rotation_screen(
            buy_signals=[{'pair':'BTC-USD','action':'BUY','momentum_pct':'.6'}],
            exploratory_candidates=[{'pair':'SOL-USD','action':'EXPLORE_ONLY','momentum_pct':'2.1'}],
            holdings=[{'asset':'USD','remaining_qty':'100','enabled':1}],
            verified_balances={'USD':'100'},balance_age_s=2,catalog=cat,
            quotes={'BTC-USD':('50000','50000.50',ts),
                    'SOL-USD':('150','150.01',ts)},
            product_rules={p:{'base_increment':'0.00000001','base_min_size':'0.000001','quote_min_size':'1'} for p in cat},
            usd_per_order_cap=Decimal('100'),now=ts,
            fee_rates_by_pair={p:Decimal('.009') for p in cat},direct_only=True)
        self.assertEqual(result['exploratory_targets'],1)
        self.assertGreater(result['exploratory_route_attempts'],0)
        self.assertGreater(result['exploratory_viable_routes'],0)
        ranked=[i for i in result['ideas'] if i.get('source_signal')=='RANKED_OBSERVATION_ONLY']
        self.assertTrue(ranked)
        self.assertTrue(all(i.get('oos_validated') is False and
                            i.get('net_p10_usd') is None and
                            i.get('sends_live_orders') is False for i in ranked))
