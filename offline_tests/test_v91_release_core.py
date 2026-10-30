"""Source integrity and retained production boundaries for the simplified build."""
import ast,hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from coincat_live import LiveLedger,LiveBroker,LiveBlocked
from coincat_live_forward_store import ForwardStore,Retention
from coincat_full_balance import rank_full_balances
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
        for name in ('coincat_app.py','coincat_scanner.py','coincat_full_balance.py','coincat_passive_lab.py'):
            tree=ast.parse((ROOT/'app'/name).read_text())
            names={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertFalse(names & {'submit','create_order','cancel_orders','preview_order','market_order_buy','market_order_sell'},name)

    def test_all_shipped_source_hashes_and_python_syntax(self):
        manifest=json.loads((ROOT/'SHA256_MANIFEST.json').read_text())
        self.assertEqual(manifest['build'],'91.0-full-balance-immediate-read-only')
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
