"""Isolated v50 RELEASE SMOKE tests, no Coinbase network or live trading."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coincat_v50_final_verification import _settlement_probe,_recovery_probe,final_verification_report
from coincat_state_v50 import state_status,migrate,StateError
from coincat_version import VERSION,DISPLAY
from coincat_live import LiveLedger

class V50Smoke(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(VERSION,'70.2')
        self.assertEqual(DISPLAY,'CoinCat v70.2')
    def test_readonly_two_split_fills(self):
        self.assertIn('PASS',_settlement_probe())
    def test_fake_crash_rollback(self):
        self.assertIn('PASS',_recovery_probe())
    def test_no_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(StateError):state_status(Path(tmp)/'CoinCatV60')
    def test_report_unverified_and_redacted(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            app=SimpleNamespace(broker=None,ledger=SimpleNamespace(path=Path(tmp)/'missing.sqlite3'))
            text=final_verification_report(app)
            for phrase in ('NO COINBASE ORDERS','CROSS-CRYPTO POST','BLOCKED','SYNTHETIC ONLY'):
                self.assertIn(phrase,text)
            self.assertNotIn(str(tmp),text)
    def test_copy_only_migration_retains_previous_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prior=root/'CoinCatV40';dest=root/'CoinCatV60'
            prior.mkdir()
            led=LiveLedger(prior/'CoinCat_Live_Orders.sqlite3')
            led.approve_all({'BTC':'0.005'})
            (prior/'.coincat_v40_state_ready.json').write_text(json.dumps({'format':'coincat-v40-state-v1','source':'explicit-fresh'}))
            (prior/'coinbase_key.dpapi').write_bytes(b'FAKE-DATA-NOT-A-REAL-KEY')
            before=(prior/'CoinCat_Live_Orders.sqlite3').read_bytes()
            result=migrate(prior,dest)
            self.assertGreater(result['copied_files'],0)
            self.assertEqual(state_status(dest)['path'],dest)
            self.assertEqual((prior/'CoinCat_Live_Orders.sqlite3').read_bytes(),before)
            self.assertEqual((dest/'coinbase_key.dpapi').read_bytes(),b'FAKE-DATA-NOT-A-REAL-KEY')
            self.assertFalse((dest/'.coincat_v40_state_ready.json').exists())
            with self.assertRaises(StateError):migrate(prior,dest)
            self.assertTrue((prior/'CoinCat_Live_Orders.sqlite3').exists())
    def test_explicit_auto_enroll_acceptance_token(self):
        from coincat_app import CoinCatApp
        import inspect
        self.assertIn('V50 INITIAL AUTO',inspect.getsource(CoinCatApp))

if __name__=='__main__':unittest.main()
