"""Read-only real-schema research-store checks on DISPOSABLE SQLite fixtures."""
from __future__ import annotations
import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from coincat_v603_research_audit import audit,report
from coincat_live_forward_store import ForwardStore
from coincat_v502_relative_learning import RelativeUSDLab
from coincat_v502_fee_learning import FeeLearning

class ResearchDataflowAudit(unittest.TestCase):
    def test_one_canonical_quote_db_with_distinct_persistent_derived_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/'research_data';folder.mkdir()
            f=ForwardStore(folder/'CoinCat_Forward_Market.sqlite3')
            # Real schema idempotence: one row for same pair and source timestamp.
            self.assertTrue(f.record_quote('BTC-USD',1700000000,'49900','50000'))
            self.assertFalse(f.record_quote('BTC-USD',1700000000,'49900','50000'))
            with f._db() as conn:
                conn.execute('CREATE TABLE directional_trials (pair TEXT, observed_at INTEGER, UNIQUE(pair,observed_at))')
            RelativeUSDLab(folder/'CoinCat_Public_Relative_USD_v502.sqlite3')
            FeeLearning(folder/'CoinCat_Fee_Evidence_v502.sqlite3')
            private=root/'CoinCat_Live_Orders.sqlite3'
            # sqlite3.Connection.__exit__ commits but does NOT close the file.
            # Windows holds the file locked until close(), so use closing().
            with closing(sqlite3.connect(private)) as conn:
                conn.execute('CREATE TABLE forward_signals (pair TEXT, at_utc INTEGER, UNIQUE(pair,at_utc))')
                conn.commit()
            files=[f.path,folder/'CoinCat_Public_Relative_USD_v502.sqlite3',
                   folder/'CoinCat_Fee_Evidence_v502.sqlite3',private]
            before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
            checks=audit(root)
            self.assertEqual(checks['status'],'PASS',checks)
            self.assertEqual(checks['stores']['market']['tables']['market_quotes']['rows'],1)
            self.assertEqual(checks['stores']['market']['tables']['market_quotes']['duplicate_keys'],False)
            self.assertIn('NO Coinbase GET/POST',report(root))
            self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in files])
    def test_missing_stores_are_not_interpreted_as_empty_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks=audit(tmp)
            self.assertEqual(checks['status'],'REVIEW')
            self.assertTrue(any('MISSING' in x for x in checks['issues']))
            self.assertNotIn('STORE market: SQLITE CHECK PASS',report(tmp))
    def test_bad_unique_data_reported_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'research_data'/'CoinCat_Forward_Market.sqlite3'
            path.parent.mkdir()
            # Close before TemporaryDirectory cleanup to prevent WinError 32.
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE market_quotes (pair TEXT, at_utc INTEGER)')
                conn.execute("INSERT INTO market_quotes VALUES ('BTC-USD', 100)")
                conn.execute("INSERT INTO market_quotes VALUES ('BTC-USD', 100)")
                conn.commit()
            r=audit(tmp)
            self.assertTrue(any('DUPLICATE_KEYS' in item for item in r['issues']))
            self.assertEqual(r['stores']['market']['tables']['market_quotes']['rows'],2)
    def test_single_active_route_planner_and_no_old_observer(self):
        src=(Path(__file__).resolve().parents[1]/'app'/'coincat_app.py').read_text()
        self.assertEqual(src.count('auto_rotation_screen('),1)
        self.assertNotIn('observe_funding_sizes(',src)
        self.assertEqual(src.count('rank_observed_markets('),1)
        diag=(Path(__file__).resolve().parents[1]/'app'/'coincat_complete_diagnostics.py').read_text()
        self.assertIn('AI LAB RESEARCH DATABASE AND SINGLE-PLANNER AUDIT',diag)
        self.assertNotIn("('V50.5 ALL-PAIR AI LAB / GPU / AUTOTRADER / P&L COMMUNICATION'",diag)

if __name__=='__main__':unittest.main()
