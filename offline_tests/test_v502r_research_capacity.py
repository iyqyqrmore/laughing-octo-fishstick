"""Aggregate 1 GiB research quota, retention safety and unified research tests.

All files disposable; no Coinbase network/credentials and NO order submission.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import time
import unittest
from unittest.mock import patch

from coincat_live_forward_store import ForwardStore,Retention
from coincat_storage import RESEARCH_LIMIT_MIB,storage_health,financial_storage_gate,research_sqlite_bytes
from coincat_v502_relative_learning import RelativeUSDLab,evaluate_hold_switch


class ResearchCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'research_data').mkdir()

    def test_shared_1g_retention_matches_storage_gate_and_unchanged_tax_cap(self):
        self.assertEqual(RESEARCH_LIMIT_MIB,1024)
        self.assertEqual(Retention().max_mb,1024)
        samples=storage_health(self.root)
        self.assertEqual(samples['research']['limit_mb'],1024)
        self.assertEqual(samples['tax_exports']['limit_mb'],1024)
        self.assertEqual(samples['ledger']['limit_mb'],128)

    def test_all_research_sqlite_wal_files_counted_not_ledger(self):
        d=self.root/'research_data'
        (d/'CoinCat_Forward_Market.sqlite3').write_bytes(b'x'*256)
        (d/'CoinCat_Forward_Market.sqlite3-wal').write_bytes(b'y'*128)
        (d/'CoinCat_Fee_Evidence_v502.sqlite3').write_bytes(b'z'*64)
        (d/'CoinCat_Public_Relative_USD_v502.sqlite3').write_bytes(b'a'*32)
        (d/'some_image.png').write_bytes(b'i'*100)
        (self.root/'CoinCat_Live_Orders.sqlite3').write_bytes(b'LEDGER')
        self.assertEqual(research_sqlite_bytes(d),480)
        self.assertEqual(storage_health(self.root)['research']['used_mb'],round(480/1048576,3))

    def test_aggregate_over_limit_fails_closed_even_if_market_db_small(self):
        with patch('coincat_storage.research_sqlite_bytes',return_value=1024*1048576+1):
            allowed, sections=financial_storage_gate(self.root)
        self.assertFalse(allowed)
        self.assertTrue(sections['research']['over'])
        self.assertEqual(sections['research']['limit_mb'],1024)

    def test_daily_maintenance_and_weekly_compact_still_present(self):
        market=ForwardStore(self.root/'research_data'/'CoinCat_Forward_Market.sqlite3')
        stamp=1800000000
        market.record_quote('ETH-BTC',stamp-4*86400,'0.05','0.051')
        market.record_quote('ETH-BTC',stamp-40,'0.05','0.051')
        health=market.maintenance(now=stamp)
        self.assertEqual(health['limit_mb'],1024)
        with market._db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM market_quotes').fetchone()[0],1)
            keys=dict(db.execute('SELECT key,value FROM live_store_state').fetchall())
            self.assertIn('last_maintenance',keys)
            self.assertIn('last_compact',keys)

    def test_relative_old_marks_pruned_not_financial_ledger(self):
        mark=RelativeUSDLab(self.root/'research_data'/'CoinCat_Public_Relative_USD_v502.sqlite3')
        now=1800000000
        with closing(sqlite3.connect(mark.path)) as db:
            db.execute('INSERT INTO public_marks VALUES(?,?,?,?)',(now-20*86400,'BTC','50000','FEE_UNVERIFIED'))
            db.execute('INSERT INTO public_marks VALUES(?,?,?,?)',(now-2*86400,'ETH','4000','FEE_UNVERIFIED'))
            db.commit()
        ledger=self.root/'CoinCat_Live_Orders.sqlite3'
        ledger.write_bytes(b'FINANCIAL_KEEP')
        info=mark.maintenance(now=now)
        self.assertEqual(info['limit_mb'],1024)
        self.assertGreaterEqual(info['pruned'],1)
        self.assertEqual(mark.public_stats()['rows'],1)
        self.assertEqual(ledger.read_bytes(),b'FINANCIAL_KEEP')

    def test_no_predictive_claim_from_insufficient_relative_windows(self):
        evidence={'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':2}
        idea={'initial_wallet_usd_mark':'200','post_route_wallet_usd_mark':'197',
              'source_units':'1','input_units_planned':'.5'}
        self.assertEqual(evaluate_hold_switch(idea,evidence)['research_decision'],'HOLD_UNTIL_VERIFIED')
        evidence={'state':'OBSERVED_WINDOWS_READY_NOT_PREDICTIVE','n':36,
                  'mean_relative_return':'.04','p10_relative_return':'-.01'}
        self.assertEqual(evaluate_hold_switch(idea,evidence)['research_decision'],'HOLD_PREFERRED')

if __name__=='__main__':unittest.main()
