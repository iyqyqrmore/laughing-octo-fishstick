"""Release regression: compile only CoinCat-delivered source, not user environment packages.

Users install third-party dependencies beneath .venv; some packages deliberately ship
Python 3.12+ syntax fixtures that cannot compile on the CoinCat Python 3.11 host.
The release manifest is authoritative for which source is part of this distribution.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def shipped_python_sources(root=ROOT):
    manifest = json.loads((root / 'SHA256_MANIFEST_V60.json').read_text(encoding='utf-8'))
    file_names = manifest['files']
    assert isinstance(file_names, dict) and file_names, 'Empty or invalid release manifest'
    return [root / name for name in sorted(file_names)
            if Path(name).suffix == '.py']


class Python311Hotfix(unittest.TestCase):
    def test_catalog_refresh_message_is_not_nested_same_quote_fstring(self):
        source = (ROOT / 'app' / 'coincat_app.py').read_text(encoding='utf-8')
        self.assertIn('one_order_count = len(one_order_catalog(', source)
        self.assertIn('no approvals or orders altered', source)
        self.assertIn('eligible one-order spot pairs', source)
        self.assertNotIn("f'{len(one_order_catalog(self.catalog,getattr(self.broker,", source)

    def test_all_delivered_python_sources_compile_on_current_interpreter(self):
        sources = shipped_python_sources()
        self.assertIn(ROOT / 'app' / 'coincat_app.py', sources)
        self.assertIn(ROOT / 'offline_tests' / 'test_v60101_python311_hotfix.py', sources)
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(source=str(path.relative_to(ROOT))):
                self.assertTrue(path.is_file())
                compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)

    def test_installed_venv_is_not_release_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'app' / 'x.py'
            app.parent.mkdir()
            app.write_text('x = 1\n', encoding='utf-8')
            dependency = root / '.venv' / 'Lib' / 'site-packages' / 'torch' / 'py312_intrinsics.py'
            dependency.parent.mkdir(parents=True)
            dependency.write_text('def f[T](a: int): return a\n', encoding='utf-8')
            (root / 'SHA256_MANIFEST_V60.json').write_text(
                json.dumps({'files': {'app/x.py': 'fixture-sha'}}), encoding='utf-8')
            sources = shipped_python_sources(root)
            self.assertEqual(sources, [app])
            for path in sources:
                compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)


if __name__ == '__main__':
    unittest.main()
