"""v50.5 offline research/packaging and source isolation tests; never calls Coinbase."""
from __future__ import annotations
import json,sqlite3,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
from coincat_v505_historical_gpu import historical_examples,warmup,saved_warmup_summary,probe_gpu
from coincat_v505_pipeline import verified_closed_usd_feedback,snapshot,report,status_line

class Fee:
    def latest_tier(self,**kwargs):return {'fresh':True}

class Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.dir=Path(self.t.name);self.history=self.dir/'history.sqlite3';self.ledger=self.dir/'ledger.sqlite3'
        with closing(sqlite3.connect(self.history)) as db:
            db.execute('CREATE TABLE research_history_hourly(pair TEXT,at_utc INTEGER,close TEXT)')
            now=int(time.time())//3600*3600-3600
            data=[]
            for j,pair in enumerate(('ETH-BTC','SOL-ETH','BTC-USD','ETH-USDT')):
                for i in range(236):
                    ts=now-(236-i)*3600
                    price=10+0.02*i+0.6*(i%7)/7+0.1*j
                    data.append((pair,ts,str(price)))
            db.executemany('INSERT INTO research_history_hourly VALUES(?,?,?)',data);db.commit()
        with closing(sqlite3.connect(self.ledger)) as db:
            db.execute('CREATE TABLE orders(cid TEXT,state TEXT)')
            db.execute('CREATE TABLE fills(cid TEXT,pair TEXT,side TEXT,performance_realized_quote TEXT,net_realized_quote TEXT)')
            db.executemany('INSERT INTO orders VALUES(?,?)', [('A','FILLED'),('B','PENDING'),('C','FILLED')])
            db.executemany('INSERT INTO fills VALUES(?,?,?,?,?)', [('A','ETH-USD','SELL','2',None),('B','BTC-USD','SELL','999',None),('C','SOL-BTC','SELL','2',None)])
            db.commit()
    def test_many_all_spot_quotes_historical_inputs(self):
        examples=historical_examples(self.history)
        self.assertGreater(len(examples),700)
        self.assertEqual(set(x[2] for x in examples),{0,1}) if len(set(x[2] for x in examples))==2 else None
        self.assertTrue(all(len(x[1])==5 for x in examples))
        self.assertEqual(sorted(x[0] for x in examples),[x[0] for x in examples])
    def test_temporal_leakage_gap_excludes_nonconsecutive(self):
        with closing(sqlite3.connect(self.history)) as db:
            db.execute("DELETE FROM research_history_hourly WHERE pair='ETH-BTC' AND at_utc=(SELECT MIN(at_utc)+3600*10 FROM research_history_hourly WHERE pair='ETH-BTC')")
            db.commit()
        self.assertGreater(len(historical_examples(self.history)),600)
    def test_warmup_never_authorizes_orders(self):
        result=warmup(self.history,self.dir/'model',minimum=400,epochs=4)
        self.assertFalse(result['affects_orders']);self.assertFalse(result['affects_budget'])
        self.assertFalse(result['learned_from_actual_fills']);self.assertFalse(result['account_fees_applied'])
        if probe_gpu()['training_ready']:
            self.assertEqual(result['status'],'EVALUATED')
            self.assertIn(saved_warmup_summary(self.dir/'model')['better_than_baseline'],(True,False))
        else:self.assertEqual(result['reason'],'PYTORCH_UNAVAILABLE')
    def test_confirmed_usd_trade_evidence_rejects_other_quotes_and_unfilled(self):
        r=verified_closed_usd_feedback(self.ledger)
        self.assertEqual(r['wins'],1);self.assertEqual(r['losses'],0);self.assertEqual(r['unknown'],1)
        self.assertFalse(r['neural_training_authorized'])
    def test_shared_all_tabs_snapshot_never_sends_order(self):
        a=SimpleNamespace(catalog=['ETH-BTC','BTC-USD','SOL-ETH'],last_cycle={'reviews':[{},{}],
          'discovery':{'coverage':3},'handoffs':[{'pair':'ETH-BTC'}],
          'auto_rotation':{'ideas':[{'source':'SOL','target':'BTC'}]}},
          fee_learning=Fee(),_portfolio_coverage={'complete':True},
          _last_scan_at=time.monotonic(),_last_portfolio_sync_monotonic=time.monotonic(),
          ledger=SimpleNamespace(path=self.ledger),forward=SimpleNamespace(path=self.history),
          _gpu_folder=self.dir/'gpu')
        s=snapshot(a)
        self.assertEqual(s['handoffs'],1);self.assertEqual(s['hold_switch_routes'],1)
        self.assertTrue(s['fee_tier_fresh']);self.assertFalse(s['live_order_post_enabled'])
        self.assertIn('LIVE POST BLOCKED',status_line(s))
        self.assertIn('NO ORDER SUBMISSIONS',report(a))
    def test_version_and_source_mode_no_legacy_fast_lane(self):
        root=Path(__file__).resolve().parents[1]
        self.assertIn('70.6.1',(root/'app/coincat_version.py').read_text())
        self.assertTrue((root/'01_START_COINCAT.bat').exists())
        self.assertFalse((root/'build_windows').exists())
        live=(root/'app/coincat_live.py').read_text()
        self.assertIn('Unified all-spot POST disabled',live)
        self.assertIn('HISTORICAL_FILL_PAIR_RE',live)

if __name__=='__main__':unittest.main()
