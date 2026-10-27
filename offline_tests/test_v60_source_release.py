"""v60 migration, no-exe source, read-only dynamic sizing guards."""
import unittest,tempfile,json,ast
from decimal import Decimal
from pathlib import Path
from coincat_version import DISPLAY
from coincat_v60_research_sizing import available_enrolled_usd_ceiling
from coincat_state_v50 import migrate,state_status,StateError
from coincat_live import LiveLedger
from coincat_rotation_autopilot import auto_rotation_screen

ROOT=Path(__file__).resolve().parents[1]
class V60Release(unittest.TestCase):
    def test_version_launchers_and_removal(self):
        self.assertEqual(DISPLAY,'CoinCat v70.0')
        self.assertFalse((ROOT/'build_windows').exists())
        self.assertTrue((ROOT/'01_START_COINCAT_V60.bat').is_file())
        self.assertIn('CoinCat50.ico', (ROOT/'tools/CREATE_SHORTCUTS_V60.ps1').read_text())
        self.assertNotIn('coincat_network_tokens', (ROOT/'app/coincat_app.py').read_text())
    def test_live_broker_unconditionally_blocked(self):
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        broker=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in broker.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)
    def test_dynamic_sizing_ignores_legacy_manual_dollars(self):
        app=(ROOT/'app/coincat_app.py').read_text()
        self.assertIn('funding_inventory_snapshot',app)
        fragment=app[app.index('            # V60 RESEARCH ONLY'):app.index('        except Exception as exc:',app.index('            # V60 RESEARCH ONLY'))]
        self.assertNotIn('TIERS[current_stage',fragment)
        self.assertIn('research_portfolio_usd_ceiling',fragment)
        self.assertIn("Decimal('100')", (ROOT/'app/coincat_rotation_autopilot.py').read_text())
    def test_ceiling_uses_verified_enrollment_and_missing_marks_block(self):
        assets=[dict(asset='USD',remaining_qty='200',enabled=1),dict(asset='BTC',remaining_qty='5',enabled=0)]
        self.assertEqual(available_enrolled_usd_ceiling(assets,{'USD':'150','BTC':'5'}, {}, [],now=1000),Decimal('150'))
        self.assertEqual(available_enrolled_usd_ceiling([dict(asset='BTC',remaining_qty='1',enabled=1)],{'BTC':'1'}, {}, [],now=1000),0)
    def test_copy_existing_v50_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path(td)/'CoinCatV50';old.mkdir()
            ledger=LiveLedger(old/'CoinCat_Live_Orders.sqlite3')
            ledger.approve_all({'BTC':'0.005'})
            (old/'.coincat_v50_state_ready.json').write_text(json.dumps({'format':'coincat-v50-state-v1','source':'verified-existing'}))
            new=Path(td)/'CoinCatV60'
            result=migrate(old,new)
            self.assertEqual(state_status(new)['path'],new)
            self.assertTrue((old/'CoinCat_Live_Orders.sqlite3').exists())
            self.assertFalse((new/'.coincat_v50_state_ready.json').exists())
            with self.assertRaises(StateError):migrate(old,new)
    def test_static_profit_module_in_diagnostics(self):
        src=(ROOT/'app/coincat_complete_diagnostics.py').read_text()
        self.assertIn('from coincat_v506_profit_sensitivity import report as profit_sensitivity_report',src)
        self.assertNotIn("__import__('coincat_v506_profit_sensitivity')",src)

class V60SizingBehavior(unittest.TestCase):
    def test_bounded_multi_size_research_includes_100_dollar_idea_without_orders(self):
        from decimal import Decimal
        from coincat_rotation_autopilot import auto_rotation_screen
        now=1800000000
        result=auto_rotation_screen(
            buy_signals=[{'action':'BUY','pair':'BTC-USD','momentum_pct':'1.5'}],
            holdings=[{'asset':'USD','remaining_qty':'200','enabled':1}],
            verified_balances={'USD':'200'},balance_age_s=10,
            catalog=['BTC-USD'],quotes={'BTC-USD':('49990','50000',now)},
            product_rules={'BTC-USD':{'base_increment':'0.00000001','base_min_size':'0.00001','quote_min_size':'1'}},
            usd_per_order_cap=Decimal('200'),now=now,
            fee_rates_by_pair={'BTC-USD':Decimal('0.009')})
        self.assertEqual(result['state'],'SHADOW ONLY')
        self.assertGreaterEqual(result['size_candidates_tested'],4)
        caps={str(x['research_size_cap_usd']) for x in result['ideas']}
        self.assertIn(Decimal('100'),{Decimal(x) for x in caps})
        self.assertTrue(all(x['sends_live_orders'] is False for x in result['ideas']))
        self.assertTrue(all(x['research_decision']!='SWITCH_WORTH_RESEARCH' for x in result['ideas']))
    def test_resume_and_data_gap_declared(self):
        source=(ROOT/'app/coincat_app.py').read_text()
        report=(ROOT/'app/coincat_complete_diagnostics.py').read_text()
        self.assertIn('RESUMED AFTER OBSERVATION GAP',source)
        self.assertIn('skipped quotes are NOT reconstructed',report)
