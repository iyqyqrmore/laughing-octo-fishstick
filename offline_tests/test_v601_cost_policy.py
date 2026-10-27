"""v60.1: new USD performance start must never replace historical tax acquisition."""
import unittest
import tempfile
import sqlite3
from pathlib import Path
from decimal import Decimal
from coincat_live import LiveLedger, LiveBlocked, sql
from coincat_inventory_lots import seed_opening,sale_basis
from coincat_v601_baseline import capture,latest,hold_mark,BaselineBlocked
from coincat_rotation_autopilot import auto_rotation_screen

class TestV601CostPolicy(unittest.TestCase):
    def test_capture_append_only_leaves_manual_history_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.sqlite3'
            ledger=LiveLedger(path)
            ledger.approve_one('AAA', '20')
            with sql(path) as conn:
                conn.execute("UPDATE enrollment SET basis_unit_quote='20',basis_source='USER_REPORTED_ORIGINAL' WHERE asset='AAA'")
                seed_opening(conn,'AAA')
                conn.execute("UPDATE inventory_lots SET performance_unit_quote='0.5',tax_unit_quote='20' WHERE lot_id='opening:AAA'")
            with self.assertRaises(LiveBlocked): ledger.set_basis('AAA',Decimal('0.50'))
            # An invented tax price cannot be used as a performance entry.
            with sql(path) as conn:
                conn.execute("UPDATE inventory_lots SET performance_unit_quote=NULL WHERE lot_id='opening:AAA'")
                with self.assertRaisesRegex(ValueError,'Unpriced personal lot'):
                    sale_basis(conn,'AAA',Decimal('1'),'USD')
                conn.execute("UPDATE inventory_lots SET performance_unit_quote='0.5' WHERE lot_id='opening:AAA'")
            with sql(path) as conn:
                with self.assertRaises(BaselineBlocked):
                    capture(conn,enrollments=ledger.assets(),available={'AAA':'19'},usd_rates={'AAA':'0.5'},now=1792972800)
                self.assertIsNone(latest(conn))
            with sql(path) as conn:
                result=capture(conn,enrollments=ledger.assets(),available={'AAA':'20'},usd_rates={'AAA':'0.5'},now=1792972800)
                self.assertEqual(result['total_usd'],'10.0')
                self.assertEqual(hold_mark(conn,{'AAA':'0.6'}),Decimal('12.0'))
                self.assertEqual(conn.execute("SELECT basis_unit_quote FROM enrollment WHERE asset='AAA'").fetchone()[0],'20')
                # Prior manually entered opening cost MUST NEVER count as proven tax basis.
                sample=sale_basis(conn,'AAA',Decimal('1'),'USD')
                self.assertIsNone(sample['tax_basis'])
                result2=capture(conn,enrollments=ledger.assets(),available={'AAA':'20'},usd_rates={'AAA':'0.75'},now=1792973000)
                self.assertNotEqual(result['id'],result2['id'])
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM v601_performance_periods').fetchone()[0],2)
                self.assertEqual(conn.execute("SELECT basis_unit_quote FROM enrollment WHERE asset='AAA'").fetchone()[0],'20')
    def test_funding_readonly_works_without_buy_signal(self):
        o=auto_rotation_screen(buy_signals=[],
            holdings=[{'asset':'USD','remaining_qty':'200','enabled':1}],
            verified_balances={'USD':'200'},balance_age_s=25,
            catalog=['BTC-USD'],quotes={'BTC-USD':('49990','50000',1900000000)},
            product_rules={},fee_rates_by_pair={},
            usd_per_order_cap=Decimal('200'),now=1900000000)
        self.assertEqual(o['state'],'WAIT')
        self.assertEqual(o['funding_size_observations']['state'],'OBSERVATIONS ONLY')
        self.assertGreater(o['funding_size_observations']['size_scenarios'],0)
        self.assertGreaterEqual(o['funding_size_observations']['at_least_100_usd'],1)
        self.assertEqual(o['route_attempts'],0)
        self.assertFalse(o['ideas'])
    def test_static_not_live_and_no_user_edit_button(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app/coincat_app.py').read_text()
        self.assertNotIn("text='Set original purchase cost'",app)
        self.assertIn('Start NEW portfolio performance period',app)
        self.assertIn('diagnostic_export_progress',app)
        self.assertNotIn('self.diagnostics_led=tk.Canvas',app)
        self.assertTrue((root/'app/coincat_v601_silent.py').is_file())
        self.assertIn('pythonw.exe',(root/'tools/CREATE_SHORTCUTS_V60.ps1').read_text())
        self.assertIn('POST remains BLOCKED', (root/'START_HERE_V60.md').read_text())
