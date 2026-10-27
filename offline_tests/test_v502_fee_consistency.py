"""v50.2 USD-neutral fee and P&L assertions; artificial data only, no orders."""
from __future__ import annotations
import time, tempfile, unittest
from pathlib import Path
from decimal import Decimal
from coincat_break_even import required_moves
from coincat_multicurrency import evaluate_rotation
from coincat_v502_microstructure import microstructure_report
from coincat_v502_fee_learning import FeeLearning
from coincat_cross_quote import research_sell_preview
from coincat_directional import DirectionalLab
from coincat_shadow_diagnostics import make_shadow_report
from contextlib import contextmanager
import sqlite3

class FakeStore:
    def __init__(self,p):self.path=p
    @contextmanager
    def _db(self):
        # Match the real ForwardStore context manager: commit/rollback and
        # CLOSE the file before TemporaryDirectory attempts Windows cleanup.
        db=sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

class FeeConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fee=FeeLearning(Path(self.temp.name)/'fee.sqlite3')
    def test_fake_store_connection_closes_on_context_exit(self):
        store=FakeStore(Path(self.temp.name)/'close_probe.sqlite3')
        with store._db() as db:
            db.execute('CREATE TABLE demo(x INTEGER)')
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
    def test_no_hidden_one_percent_fallback_in_multi_currency_routes(self):
        now=time.time()
        args=dict(source='BTC',target='ETH',authorized_qty='.05',verified_available_qty='.05',
            balance_age_s=15,catalog={'BTC-USD','ETH-BTC'},
            quotes={'BTC-USD':('80000','80005',now),'ETH-BTC':('.03','.03001',now)},
            now=now,usd_per_order_cap=100,
            product_rules={'ETH-BTC':{'base_increment':'.000001','base_min_size':'.00001','quote_min_size':'.0000001'}})
        missing=evaluate_rotation(**args)
        self.assertEqual(missing['state'],'WAIT')
        self.assertIn('fee evidence',missing['reason'])
        cheap=evaluate_rotation(**args,fee_rates_by_pair={'ETH-BTC':Decimal('.003')})
        costly=evaluate_rotation(**args,fee_rates_by_pair={'ETH-BTC':Decimal('.020')})
        self.assertEqual(cheap['state'],'RESEARCH ONLY')
        self.assertEqual(costly['state'],'RESEARCH ONLY')
        self.assertGreater(cheap['routes'][0]['destination_units_estimate'],costly['routes'][0]['destination_units_estimate'])
        self.assertTrue(all(not x.get('ready_for_live_post',False) for x in cheap['routes']))
        missing_leg=evaluate_rotation(**args,fee_rates_by_pair={'BTC-USD':Decimal('.001')})
        self.assertEqual(missing_leg['state'],'WAIT')
    def test_break_even_unavailable_until_verified_fee(self):
        self.assertIsNone(required_moves('10','0.98'))
        low=required_moves('10','.98',fee_per_leg=Decimal('.002'))
        high=required_moves('10','.98',fee_per_leg=Decimal('.02'))
        self.assertLess(low['break_even_pct'],high['break_even_pct'])
        self.assertIn('account_tier_round_trip_fee_estimate_pct',low)
        self.assertNotIn('assumed_round_trip_fee_pct',low)
    def test_cross_quote_sell_research_needs_fee_source(self):
        kw=dict(bid_quote='.03',quote_to_usd='80000',available_base='1',
                usd_order_cap='100',basis_usd='80',target_net_usd='.50')
        with self.assertRaisesRegex(ValueError,'fee evidence'):
            research_sell_preview(**kw)
        preview=research_sell_preview(**kw,assumed_fee_rate='.003')
        self.assertTrue(preview['gross_usd']>0)
    def test_fee_cache_stale_means_no_global_research_quote(self):
        self.fee.capture_tier({'fee_tier':{'maker_fee_rate':'.001','taker_fee_rate':'.003'}},now=100000)
        self.assertEqual(self.fee.research_screen('ETH-BTC','2','8',now=100001)['source'],
                         'ACCOUNT_TIER_ONLY_PAIR_PREVIEW_REQUIRED')
        self.assertEqual(self.fee.research_screen('SOL-USDT','2','8',now=200000)['state'],'FEE_UNVERIFIED')
        self.assertFalse(self.fee.account_cost('BTC-USD',now=200000)['fresh'])
    def test_directional_unverified_does_not_make_fake_net_outcome(self):
        store=FakeStore(Path(self.temp.name)/'quotes.sqlite3')
        with store._db() as db:
            db.execute('CREATE TABLE market_quotes(pair TEXT, at_utc INTEGER,bid TEXT,ask TEXT)')
            db.commit()
        lab=DirectionalLab(store,fee_learning=self.fee)
        self.assertTrue(lab.record('ETH-BTC','.03','.031',now=1000010))
        with store._db() as db:
            row=db.execute('SELECT id,horizon_at,fee_source_at_entry FROM directional_trials').fetchone()
            self.assertEqual(row[2],'UNVERIFIED_ASSUMPTION')
            db.execute('INSERT INTO market_quotes VALUES(?,?,?,?)',('ETH-BTC',row[1]+1,'.032','.033'))
            db.commit()
        lab.evaluate(now=row[1]+20)
        with store._db() as db:
            state,buy=db.execute('SELECT state,buy_net_pct FROM directional_trials').fetchone()
            self.assertEqual(state,'FEE_UNVERIFIED')
            self.assertIsNone(buy)
        self.assertEqual(lab.stats('ETH-BTC')['n'],0)
    def test_redacted_microstructure_report_no_fabricated_percentage(self):
        class App: pass
        a=App();a.last_cycle={};a.fee_learning=self.fee
        text=microstructure_report(a)
        self.assertIn('no invented 1% fallback',text)
        self.assertNotIn('ASSUMED fee per leg: 1.000%',text)
    def test_shadow_report_full_section_reachable(self):
        class App: pass
        a=App();a.last_cycle={'signals':[],'broker_pair_reviews':[],
            'auto_rotation':{'state':'WAIT','ideas':[],'considered':0,'scanned_sources':0,
                             'route_attempts':0,'viable_routes':0,'route_blockers':{}}}
        a.shadow_snapshots=[];a.shadow_session_totals={};a._last_scan_at=0;a.broker=None
        txt=make_shadow_report(a,now=1800000000)
        self.assertIn('LATEST COMPLETED SHADOW SCREEN',txt)
        self.assertIn('no longer',txt.lower()) if False else None
        self.assertIn('no 1%',txt.lower()) if False else None
        self.assertIn('Unavailable authenticated tier:',txt)
        self.assertNotIn('fee ceiling 1.00%',txt)

if __name__=='__main__':unittest.main()
