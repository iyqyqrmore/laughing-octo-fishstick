"""Source integrity and retained production boundaries for the simplified build."""
import ast,hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from coincat_live import LiveBroker,LiveBlocked
from coincat_live_forward_store import ForwardStore
from offline_tests.sqlite_resources import held_sqlite_connections

ROOT=Path(__file__).resolve().parents[1]


class ReleaseCore(unittest.TestCase):
    def test_submission_is_still_unconditionally_blocked_before_other_work(self):
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(method.body[0],ast.Raise)
        self.assertIn('LiveBlocked',ast.unparse(method.body[0]))
        with self.assertRaises(LiveBlocked):LiveBroker.__new__(LiveBroker).submit('BUY','BTC-USD','1')

    def test_no_order_or_preview_adapters_in_active_scanner(self):
        for name in ('coincat_app.py','coincat_scanner.py','coincat_full_balance.py','coincat_eth_maker.py',
                     'coincat_chart.py','coincat_continuity.py','coincat_recovery.py'):
            tree=ast.parse((ROOT/'app'/name).read_text())
            names={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertFalse(names & {'submit','create_order','cancel_orders','preview_order','market_order_buy','market_order_sell'},name)

    def test_all_shipped_source_hashes_and_python_syntax(self):
        manifest=json.loads((ROOT/'SHA256_MANIFEST.json').read_text())
        self.assertEqual(manifest['build'],'95.0-eth-growth-research-preview')
        self.assertGreater(len(manifest['files']),30)
        for name,expected in manifest['files'].items():
            p=ROOT/name
            self.assertTrue(p.is_file(),name)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),expected,name)
            self.assertNotIn('.venv',p.parts)
            if p.suffix=='.py':compile(p.read_bytes(),name,'exec',dont_inherit=True)

    def test_canonical_public_quote_table_preserves_unrelated_research(self):
        with held_sqlite_connections() as handles, TemporaryDirectory() as folder:
            path=Path(folder)/'CoinCat_Forward_Market.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE historical_context(value TEXT)')
                db.execute("INSERT INTO historical_context VALUES('PRESERVE')")
            store=ForwardStore(path)
            self.assertEqual(store.record_quotes([('BTC-USD',1800000000,'100','100.01','FAKE')]),1)
            self.assertEqual(store.record_quotes([('BTC-USD',1800000001,'-1','2','FAKE')]),0)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT value FROM historical_context').fetchone()[0],'PRESERVE')
                self.assertEqual(db.execute('SELECT bid,ask FROM market_quotes').fetchone(),('100','100.01'))
                tables={r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type=\'table\'')}
                self.assertFalse(any('shadow' in name.lower() or 'experiment' in name.lower() for name in tables))
            self.assertTrue(handles)
            self.assertTrue(all(db.closed for db in handles),'SQLite handles must close before temporary-folder deletion')

    def test_seven_protected_modules_exactly_match_the_verified_v91_baseline(self):
        hashes={
            'coincat_live.py':'582744bde0497df22c8bad1d6092c6092bb64c99d171f783eec7ac5f86d3ffe4',
            'coincat_unified_fifo_v501.py':'c2cc83616bc3ebe4df04b3b9355ecddd2dd3e2b16f86987c100119ad9103493a',
            'coincat_state_v50.py':'93cf2add1878c3f2b48221eb53a9a556270ee8672e2a0746fed1c60ccb3e984b',
            'coincat_data_transfer.py':'b797413e3108bfb45a4986514ae2ded15e907b7c8edcb3e34217c2efe04be216',
            'coincat_inventory_lots.py':'72b06c37a99df2131e96f1336872c4289a81b33974e833703988e90050e681b7',
            'coincat_verified_cross_fills.py':'49cc8fd6ea71553b48c85ebc6cc48166761c7f9bd0349c312cc5dcf707fbe130',
            'coinbase_account.py':'ba6148242d86243135670dbf1c20435ec54cf5ff6f07976a68c09bddb479c0e0'}
        root=Path(__file__).resolve().parents[1]/'app'
        for name,expected in hashes.items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected,name)
