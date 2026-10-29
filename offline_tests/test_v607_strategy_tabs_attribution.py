"""v60.7 original strategies, cross-tab pipeline, forward-label integrity and no-POST."""
import ast
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from coincat_live_forward_store import ForwardStore
from coincat_v607_strategy_research import analyze_pair,StrategyResearch,report,public_summary
from coincat_version import DISPLAY

ROOT=Path(__file__).resolve().parents[1]

def quotes(values, *, start=1799998740, step=180):
    return [(start+i*step,Decimal(str(v)),Decimal(str(v))*Decimal('1.0002')) for i,v in enumerate(values)]

class StrategyRelease(unittest.TestCase):
    def test_signal_patterns_independent_and_past_only(self):
        now=1800000000
        q=quotes([100,100.05,100.1,100.15,100.2,100.3,100.4,100.7])
        r=analyze_pair('AAA-USD',q,now=now)
        self.assertIn('MOMENTUM_BASELINE',{x['strategy'] for x in r['candidates']})
        self.assertIn('BREAKOUT',{x['strategy'] for x in r['candidates']})
        self.assertTrue(all(x['action']=='EXPLORE_ONLY' and not x['sends_orders'] and not x['oos_validated'] for x in r['candidates']))
        q=quotes([100,100.1,100.2,100.35,100.38,100.15,100.1,100])
        r=analyze_pair('BBB-USD',q,now=now)
        self.assertIn('RANGE_REVERSION',{x['strategy'] for x in r['candidates']})
        self.assertFalse(any(x['action']=='BUY' for x in r['candidates']))
    def test_stale_and_future_quotes_rejected(self):
        a=quotes([100,100.1,100.3,100.4,100.5,100.6,100.7,101])
        self.assertEqual(analyze_pair('AAA-USD',a,now=1800010000)['candidates'],[])
        self.assertEqual(analyze_pair('AAA-USD',[(1800009000,'1','1')]+a,now=1800000000)['last_quote_age_s'],1800000000-a[-1][0])
    def test_real_future_marks_and_missing_offline(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForwardStore(Path(td)/'market.sqlite3')
            t=1800000000
            a=quotes([100,100.05,100.1,100.15,100.2,100.3,100.4,101],start=t-1260,step=180)
            for ts,b,ask in a:store.record_quote('AAA-USD',ts,b,ask)
            lab=StrategyResearch(store)
            s=lab.scan(['AAA-USD'],now=t,fee_rate='.009')
            self.assertGreaterEqual(s['total_candidates'],1)
            self.assertFalse(s['may_authorize_orders'])
            self.assertTrue(any(x['PENDING'] for x in s['future_outcomes'].values()))
            # A mark inside target window counts; late post-gap snapshots do NOT.
            store.record_quote('AAA-USD',t+3600,'105','105.1')
            t2=lab.scan([],now=t+3601,fee_rate='.009')
            self.assertGreaterEqual(sum(x['OBSERVED'] for x in t2['future_outcomes'].values()),1)
            self.assertGreaterEqual(sum(x['positive_after_assumed_cost'] for x in t2['future_outcomes'].values()),1)
            # Two independent patterns have no reference to enrolled balances.
            self.assertNotIn('balances',report(t2).lower())
    def test_missed_gap_not_backfilled(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForwardStore(Path(td)/'market.sqlite3')
            t=1800000000
            for ts,b,a in quotes([100,100.05,100.1,100.2,100.3,100.4,100.5,101],start=t-1260):
                store.record_quote('AAA-USD',ts,b,a)
            lab=StrategyResearch(store);lab.scan(['AAA-USD'],now=t,fee_rate='.009')
            store.record_quote('AAA-USD',t+3600+1201,'200','201')
            result=lab.scan([],now=t+3600+1202,fee_rate='.009')
            self.assertEqual(sum(v['OBSERVED'] for v in result['future_outcomes'].values()),0)
            self.assertGreater(sum(v['MISSED_FUTURE_MARK'] for v in result['future_outcomes'].values()),0)
    def test_shared_all_four_tabs_and_one_planner(self):
        src=(ROOT/'app/coincat_app.py').read_text()
        self.assertEqual(src.count('textvariable=self.strategy_pipeline_status'),4)
        self.assertEqual(src.count('auto_rotation_screen('),1)
        self.assertIn('result[\'strategy_research\']=self.strategy_lab.scan',src)
        self.assertIn("exploratory['candidates']=list(by_asset.values())[:rank_capacity]",src)
        self.assertNotIn("result['signals'].extend",src)
        self.assertIn("v608_status_text(payload.get('strategy_research')",src)
        report_src=(ROOT/'app/coincat_complete_diagnostics.py').read_text()
        self.assertIn('strategy_research_report(',report_src)
        self.assertEqual(DISPLAY,'CoinCat v90.0')
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        live=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in live.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)
    def test_attribution_policy_is_not_false_code_claim(self):
        notes=(ROOT/'THIRD_PARTY_ATTRIBUTION_AND_RISK.md').read_text()
        self.assertIn('No source code from those four projects',notes)
        self.assertIn('Apache-2.0',notes)
        self.assertIn('GPL-3.0',notes)
        self.assertIn('MIT',notes)
        self.assertIn('session-level',notes)

if __name__=='__main__':unittest.main()
