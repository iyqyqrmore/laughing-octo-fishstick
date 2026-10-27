"""Verify standalone v60 BAT gates remain offline unless separately approved."""
from pathlib import Path
import ast, unittest
from verification import run_verification as v
ROOT=Path(__file__).resolve().parents[1]

class V60Verification(unittest.TestCase):
    def test_all_ten_bat_gate_launchers_present(self):
        paths=list((ROOT/'verification').glob('VERIFY_*_V60.bat'))
        self.assertEqual(len(paths),10)
        for p in paths:
            s=p.read_text(encoding='utf-8')
            self.assertIn('run_verification.py',s)
            self.assertNotIn('submit_order(',s)
            self.assertNotIn('create_order(',s)
    def test_all_does_not_opt_in_network(self):
        self.assertNotIn('authorize-readonly-network',(ROOT/'verification/VERIFY_10_ALL_V60.bat').read_text())
        self.assertIn('READONLY GET',(ROOT/'verification/VERIFY_03_COINBASE_V60.bat').read_text())
        self.assertIn("ns.authorize_readonly_network and ns.gate!='coinbase'",(ROOT/'verification/run_verification.py').read_text())
        self.assertNotIn('coinbase',v.GROUPS)
    def test_source_only_gpu_verification(self):
        src=(ROOT/'verification/run_verification.py').read_text()
        self.assertIn('NO PyInstaller EXE',src)
        self.assertNotIn('dist\\CoinCat50',src)
    def test_live_submit_still_unconditional_block(self):
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        broker=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        method=next(n for n in broker.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(method.body[0],ast.Raise)
