"""Codex v70 source baseline: isolated private state and inviolate live block."""
import ast, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class V70CodexBaseline(unittest.TestCase):
 def test_version_and_handoff(self):
  from coincat_version import DISPLAY
  self.assertEqual(DISPLAY, 'CoinCat v70.6')
  self.assertTrue((ROOT/'AGENTS.md').is_file())
  self.assertTrue((ROOT/'docs/history/CODEX_HANDOFF_V70.md').is_file())
 def test_portable_private_root_and_explicit_copy_only(self):
  from unittest.mock import patch
  from coincat_state_v50 import data_root
  with patch.dict('os.environ',{},clear=True):
   self.assertEqual(data_root(),ROOT/'private_data')
  self.assertIn('import_wizard()', (ROOT/'app/coincat_launcher.py').read_text())
  self.assertIn("MARKER = '.coincat_v60_state_ready.json'",(ROOT/'app/coincat_state_v50.py').read_text())
 def test_snowball_label_valid_utf8_and_no_double_encoded_bullet(self):
  src=(ROOT/'app/coincat_app.py').read_text(encoding='utf8')
  self.assertIn('SNOWBALL • COST & USD ADVANTAGE',src)
  self.assertNotIn('SNOWBALL â€¢ COST & USD ADVANTAGE',src)
 def test_copy_verified_v60_state_to_v70_never_changes_source(self):
  import json
  from tempfile import TemporaryDirectory
  from coincat_live import LiveLedger
  from coincat_state_v50 import migrate,state_status
  with TemporaryDirectory() as folder:
   src=Path(folder)/'CoinCatV60';src.mkdir()
   LiveLedger(src/'CoinCat_Live_Orders.sqlite3')
   marker={'format':'coincat-v60-state-v1','source':'verified-existing'}
   (src/'.coincat_v60_state_ready.json').write_text(json.dumps(marker),encoding='utf8')
   original_db=(src/'CoinCat_Live_Orders.sqlite3').read_bytes()
   dst=Path(folder)/'CoinCatV70'
   migrate(src,dst)
   self.assertEqual(state_status(dst)['path'],dst)
   self.assertEqual((src/'CoinCat_Live_Orders.sqlite3').read_bytes(),original_db)
   self.assertEqual(json.loads((src/'.coincat_v60_state_ready.json').read_text()),marker)
   self.assertTrue((dst/'CoinCat_Live_Orders.sqlite3').is_file())
   self.assertFalse((dst/'coincat_v60_instance.lock').exists())
 def test_unconditional_broker_block(self):
  module=ast.parse((ROOT/'app/coincat_live.py').read_text())
  broker=next(x for x in module.body if isinstance(x,ast.ClassDef) and x.name=='LiveBroker')
  sub=next(x for x in broker.body if isinstance(x,ast.FunctionDef) and x.name=='submit')
  self.assertIsInstance(sub.body[0],ast.Raise)
if __name__=='__main__': unittest.main()
