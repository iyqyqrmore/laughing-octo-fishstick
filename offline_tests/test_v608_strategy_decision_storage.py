"""v60.8 end-to-end, synthetic REST observations: zero Coinbase clients/orders."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from coincat_live_forward_store import ForwardStore
from coincat_v608_outcomes import ForwardHorizonLab,diagnostics,status_text
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_v605_shadow_bridge import shadow_screen

NOW=1800000000
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'0.01'}
ROOT=Path(__file__).resolve().parents[1]

class V608Learning(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ForwardStore(Path(self.tmp.name)/'CoinCat_Forward_Market.sqlite3')
        self.lab=ForwardHorizonLab(self.store)
        self.store.record_quote('BTC-USD',NOW,'99.99','100')
        self.candidate={'pair':'BTC-USD','strategy':'BREAKOUT','action':'EXPLORE_ONLY',
            'sends_orders':False,'observation_at_utc':NOW,'observed_pct':'1'}
    def tearDown(self):self.tmp.cleanup()
    def test_three_future_horizons_use_actual_book_not_future_at_signal_time(self):
        result=self.lab.record_and_mature([self.candidate],now=NOW,fee_rate='.009')
        self.assertEqual(result['new_rows'],3)
        self.assertFalse(result['eligible_for_shadow'])
        self.assertEqual(self.lab.record_and_mature([self.candidate],now=NOW,fee_rate='.009')['new_rows'],0)
        for horizon in (300,900,3600):
            self.store.record_quote('BTC-USD',NOW+horizon,'105','105.1')
            current=self.lab.record_and_mature([],now=NOW+horizon,fee_rate='.009')
            self.assertEqual(current['matured'],1)
            self.assertIn('OBSERVED',current['study']['BREAKOUT:'+str(horizon//60)+'m'])
        self.assertEqual(current['rows'],3)
        self.assertTrue(all('COLLECTING' in g['maturity'] for g in current['study'].values()))
    def test_stale_later_mark_not_fabricated(self):
        self.lab.record_and_mature([self.candidate],now=NOW,fee_rate='.009')
        self.store.record_quote('BTC-USD',NOW+300+121,'200','201')
        result=self.lab.record_and_mature([],now=NOW+300+122,fee_rate='.009')
        self.assertEqual(result['missing'],1)
        self.assertEqual(result['matured'],0)
    def test_old_observation_stale_or_missing_verified_fee_no_new_rows(self):
        self.assertEqual(self.lab.record_and_mature([self.candidate],now=NOW+200,fee_rate='.009')['new_rows'],0)
        self.assertEqual(self.lab.record_and_mature([self.candidate],now=NOW,fee_rate=None)['new_rows'],0)
    def test_shared_research_size_guard_does_not_delete_financial_data(self):
        with patch('coincat_v608_outcomes.research_sqlite_bytes',return_value=900*1048576):
            result=self.lab.record_and_mature([self.candidate],now=NOW,fee_rate='.009')
        self.assertTrue(result['storage_paused'])
        self.assertEqual(result['new_rows'],0)
        self.assertEqual(result['retention_days'],15)
        self.assertLessEqual(result['max_writes_per_scan'],72)
        with self.store._db() as c:
            names=[row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertFalse(any('balance' in name or 'order' in name or 'lot' in name for name in names))
    def test_horizon_isolation_and_retention(self):
        self.lab.record_and_mature([self.candidate],now=NOW,fee_rate='.009')
        result=self.lab.record_and_mature([],now=NOW+16*86400,fee_rate='.009')
        self.assertEqual(result['rows'],0)
        self.assertFalse(result['eligible_for_live'])

class V608OnePlanner(unittest.TestCase):
    def call(self,*,holdings=None,balance=None,signals=(),strategy=None):
        return auto_rotation_screen(buy_signals=signals,
            strategy_candidates=(strategy or [{'pair':'BTC-USD','action':'EXPLORE_ONLY',
                      'sends_orders':False,'observed_pct':'0.6','strategy':'BREAKOUT'}]),
            holdings=holdings or [{'asset':'USD','remaining_qty':'150','enabled':1}],
            verified_balances=balance or {'USD':'150'},balance_age_s=10,
            catalog=['BTC-USD','ETH-USD','USDC-USD'],
            quotes={'BTC-USD':('49990','50000',NOW),'ETH-USD':('1999','2000',NOW),
                    'USDC-USD':('1','1',NOW)},
            product_rules={p:RULE for p in ['BTC-USD','ETH-USD','USDC-USD']},
            usd_per_order_cap='150',now=NOW,
            fee_rates_by_pair={p:'.009' for p in ['BTC-USD','ETH-USD','USDC-USD']},
            minimum_net_advantage_usd='.10')
    def test_breakout_targets_reviewed_without_legacy_buy(self):
        output=self.call(signals=[])
        self.assertGreater(output['strategy_route_reviews'],0)
        self.assertGreater(output['strategy_routes_feasible'],0)
        self.assertTrue(output['ideas'])
        self.assertTrue(all(i['source_signal']=='STRATEGY_RESEARCH_ONLY' for i in output['ideas']))
        self.assertTrue(all(i['research_decision']=='STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED'
                            and i['oos_validated'] is False for i in output['ideas']))
        self.assertEqual(output['threshold_research']['qualified_predictions'],0)
    def test_standard_buy_and_independent_strategy_share_one_planner(self):
        output=self.call(signals=[{'pair':'ETH-USD','action':'BUY','momentum_pct':'1'}])
        self.assertGreater(output['strategy_route_reviews'],0)
        origins={x.get('source_signal') for x in output['ideas']}
        self.assertIn('STRATEGY_RESEARCH_ONLY',origins)
        self.assertIn('LEGACY_BUY_RESEARCH',origins)
    def test_evolved_shadow_inventory_not_original_real_holdings(self):
        # BTC is newly owned by hypothetical SHADOW. Funded SELL-first works
        # on its simulated quantity, despite original real portfolio being USD.
        result=shadow_screen(balances={'BTC':'0.002','USD':'5'},excluded=set(),
            buy_signals=[],age_s=10,catalog=['BTC-USD','ETH-USD','USDC-USD'],
            quotes={'BTC-USD':('49990','50000',NOW),'ETH-USD':('1999','2000',NOW),
                    'USDC-USD':('1','1',NOW)},
            product_rules={p:RULE for p in ['BTC-USD','ETH-USD','USDC-USD']},
            portfolio_usd_cap='100000',now=NOW,fee_rates_by_pair={'BTC-USD':'.009'},
            relative_evidence=None,strategy_candidates=[])
        self.assertEqual(result['sell_first']['screened'],1)
        self.assertEqual(result['funding_assets'],2)
    def test_cross_tab_dashboard_and_complete_diagnostics_one_source(self):
        src=(ROOT/'app/coincat_app.py').read_text()
        self.assertEqual(src.count('textvariable=self.strategy_pipeline_status'),4)
        self.assertEqual(src.count('auto_rotation_screen('),1)
        self.assertIn('strategy_candidates=annotate_study(',src)
        self.assertIn('strategy_candidates=strategy_candidates',src)
        self.assertIn('self.horizon_lab.record_and_mature(',src)
        report=(ROOT/'app/coincat_complete_diagnostics.py').read_text()
        self.assertIn('v608_decision_diagnostics(',report)
        self.assertIn('SHADOW ROTATION & SIMULATED ROUTES',report)
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        broker=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in broker.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)
        safe=diagnostics({'total_candidates':3},{'strategy_route_reviews':20},
            {'rows':100,'matured':1,'retention_days':15}, {'research':{'used_mb':45,'limit_mb':1024}})
        self.assertNotIn('private',safe.lower())
        self.assertIn('Active storage research MiB: 45/1024',safe)
        self.assertIn('strategy funded-route reviews 20',status_text({}, {'strategy_route_reviews':20},{}))

if __name__=='__main__':unittest.main()
