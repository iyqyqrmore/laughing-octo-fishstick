"""V60.4 offline-only research coverage and non-actionable forward learning."""
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

APP=Path(__file__).resolve().parents[1]/'app'
if str(APP) not in sys.path:sys.path.insert(0,str(APP))
from coincat_v604_adaptive_focus import AdaptiveFocusCapacity
from coincat_v604_forward_windows import observed_windows,research_summary
from coincat_live_forward_store import ForwardStore
from coincat_market_intelligence import FocusPlanner


class AdaptiveResearch(unittest.TestCase):
    def test_more_coverage_only_after_healthy_scans(self):
        controller=AdaptiveFocusCapacity()
        for _ in range(2):
            self.assertEqual(64,controller.observe(elapsed=4,scan_interval=45,
                quotes=76,failures=0,websocket_healthy=True))
        self.assertEqual(80,controller.observe(elapsed=4,scan_interval=45,
                quotes=76,failures=0,websocket_healthy=True))
        self.assertEqual(64,controller.observe(elapsed=42,scan_interval=45,
                quotes=76,failures=5,websocket_healthy=True))
        self.assertEqual(48,controller.observe(elapsed=42,scan_interval=45,
                quotes=76,failures=5,websocket_healthy=True))
    def test_no_growth_without_observations_or_stream(self):
        c=AdaptiveFocusCapacity()
        for _ in range(10):
            self.assertEqual(64,c.observe(elapsed=1,scan_interval=60,
                quotes=0,failures=0,websocket_healthy=True))
        for _ in range(10):
            self.assertEqual(64,c.observe(elapsed=1,scan_interval=60,
                quotes=100,failures=0,websocket_healthy=False))
    def test_invalid_scan_does_not_change_size(self):
        c=AdaptiveFocusCapacity()
        self.assertEqual(64,c.observe(elapsed=float('nan'),scan_interval=40,
            quotes=55,failures=0,websocket_healthy=True))
    def test_forward_no_lookahead_or_fabricated_fills(self):
        samples=[(1000,100,100),(1059,102,102)]
        out=observed_windows(samples,horizon_s=60)
        self.assertEqual(0,out['matured'])
        self.assertIsNone(out['mean_net_pct'])
        samples.append((1061,105,105))
        out=observed_windows(samples,horizon_s=60)
        self.assertEqual(1,out['matured'])
        self.assertGreater(out['net_returns'][0],0)
        self.assertIn('NOT portfolio',out['caveat'])
    def test_cost_drag_and_nonoverlap(self):
        samples=[(1000+i*60,100,100) for i in range(8)]
        result=observed_windows(samples,horizon_s=180)
        self.assertEqual(2,result['matured'])
        self.assertEqual(0,result['positive'])
        self.assertLess(result['mean_net_pct'],-2)
    def test_no_false_matured_result_across_missing_quotes(self):
        samples=[(1000,100,101),(10000,100,101)]
        output=observed_windows(samples,horizon_s=60)
        self.assertEqual(0,output['matured'])
        self.assertEqual(1,output['missing_future'])
    def test_canonical_storage_only_and_no_ledger_writes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'research_data'/'CoinCat_Forward_Market.sqlite3'
            store=ForwardStore(path)
            for i in range(15):store.record_quote('SOL-USD',30000+i*60,100,100)
            results=research_summary(store,['SOL-USD'],now=30000+14*60,fee_rate=Decimal('.009'))
            self.assertGreaterEqual(results['horizons'][60]['matured'],1)
            self.assertEqual('DESCRIPTIVE_ONLY_NOT_PORTFOLIO_ALPHA',results['state'])
            with store._db() as c:
                names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn('v604_forward_trades',names)
    def test_urgent_focus_rest_verified_only_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForwardStore(Path(td)/'cache.sqlite')
            # First cohort uses broad stable list, no market movement.
            catalog=['BTC-USD']+[f'TEST{i}-USD' for i in range(20)]
            planner=FocusPlanner(store,hold_seconds=2700,promotions=8,urgent_per_cycle=4)
            first=planner.select(['BTC-USD'],catalog,capacity=8,now=1000)
            self.assertEqual(8,len(first['watch']))
            # Two real REST bid/ask discovery samples, >60s apart and fresh.
            target='TEST19-USD'
            store.record_discovery(target,1000,'100','100.10')
            store.record_discovery(target,1100,'102','102.10')
            later=planner.select(['BTC-USD'],catalog,capacity=8,now=1101)
            self.assertIn(target,later['watch'])
            self.assertIn(target,later['urgent_added'])
            self.assertLessEqual(len(later['watch']),8)
    def test_single_active_planner_and_no_trade_authority(self):
        app=(APP/'coincat_app.py').read_text()
        self.assertEqual(1,app.count('result[\'auto_rotation\']=auto_rotation_screen('))
        for part in ('coincat_v604_forward_windows.py','coincat_v604_adaptive_focus.py'):
            source=(APP/part).read_text()
            for forbidden in ('.submit_order(','.create_order(','.cancel_order(','.ledger.set_basis('):
                self.assertNotIn(forbidden,source)


if __name__=='__main__':unittest.main()
