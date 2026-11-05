"""Synthetic portable cut-over, retained history, backup and retirement tests."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
from types import SimpleNamespace as NS
import json
import os
import sqlite3
import subprocess
import sys
import unittest

from coincat_live import LiveLedger
from coincat_state_v50 import data_root, state_status, MARKER, LEDGER, StateError, _source_guard
from coincat_data_transfer import (
    import_private_data, verify_active, inventory, check_cleanup, RECEIPT)

ROOT=Path(__file__).resolve().parents[1]


def source_fixture(root):
    root.mkdir()
    ledger=LiveLedger(root/LEDGER)
    ledger.approve_all({'BTC':'0.005','USDC':'10'})
    (root/MARKER).write_text(json.dumps({'format':'coincat-v60-state-v1','source':'verified-existing'}))
    (root/'coinbase_key.dpapi').write_bytes(b'SYNTHETIC-ENCRYPTED-VAULT-NOT-A-KEY')
    (root/'research_data').mkdir()
    with closing(sqlite3.connect(root/'research_data'/'quotes.sqlite3')) as db:
        db.execute('PRAGMA user_version=7')
        db.execute('CREATE TABLE samples(id TEXT PRIMARY KEY, precise_value TEXT, payload BLOB)')
        db.execute('INSERT INTO samples VALUES (?,?,?)',('FAKE-001','0.000000000000000000001',b'\x00\xff'))
        db.commit()
    (root/'tax_exports').mkdir()
    (root/'tax_exports'/'synthetic.csv').write_text('id,basis\nSYNTHETIC,UNKNOWN\n')
    (root/'preferences.json').write_text('{"synthetic": true, "excluded": ["FAKE"]}')
    return root


class PortableImport(unittest.TestCase):
    def test_all_private_contents_and_source_bytes_are_preserved(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'CoinCatV70');dst=p/'CoinCat'/'private_data'
            before=inventory(src)
            original=(src/LEDGER).read_bytes()
            result=import_private_data(src,dst)
            self.assertEqual(inventory(dst),before)
            self.assertEqual(inventory(result['backup']),before)
            self.assertEqual((src/LEDGER).read_bytes(),original)
            self.assertEqual((dst/'coinbase_key.dpapi').read_bytes(),(src/'coinbase_key.dpapi').read_bytes())
            self.assertEqual(verify_active(dst)['files'],len(before))

    def test_wal_committed_rows_are_copied(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old')
            db=sqlite3.connect(src/'research_data'/'quotes.sqlite3')
            try:
                db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
                db.execute('INSERT INTO samples VALUES (?,?,?)',('FAKE-WAL','123.00000000001',b'wal'))
                db.commit()
                out=import_private_data(src,p/'new'/'private_data')
                for folder in (out['path'],out['backup']):
                    with closing(sqlite3.connect(folder/'research_data'/'quotes.sqlite3')) as copied:
                        self.assertEqual(copied.execute('SELECT COUNT(*) FROM samples').fetchone()[0],2)
                        self.assertEqual(copied.execute('PRAGMA user_version').fetchone()[0],7)
            finally:db.close()

    def test_startup_works_after_old_data_is_removed_and_app_is_renamed(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');app=p/'new'
            out=import_private_data(src,app/'private_data')
            # Remove only the test's own synthetic old tree.
            import shutil
            shutil.rmtree(src)
            app.rename(p/'CoinCat')
            target=p/'CoinCat'/'private_data'
            self.assertEqual(verify_active(target)['files'],out['files'])
            with patch.dict(os.environ,{'COINCAT_DATA_DIR':str(target)}), \
                 patch('coincat_data_transfer.import_wizard',side_effect=AssertionError('Old folder lookup')):
                from coincat_launcher import ensure_private_data
                self.assertTrue(ensure_private_data())
            self.assertTrue((p/'CoinCat'/'private_backups').is_dir())

    def test_existing_destination_and_source_nesting_refused(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            dst.mkdir(parents=True);(dst/'user.txt').write_text('PRESERVE')
            with self.assertRaises(StateError):import_private_data(src,dst)
            self.assertEqual((dst/'user.txt').read_text(),'PRESERVE')
            with self.assertRaises(StateError):import_private_data(src,src/'nested')

    def test_corrupt_research_database_blocks_publication(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            (src/'research_data'/'bad.sqlite3').write_bytes(b'SYNTHETIC-CORRUPT')
            with self.assertRaises((StateError,sqlite3.Error)):import_private_data(src,dst)
            self.assertFalse(dst.exists())
            self.assertTrue((src/LEDGER).is_file())

    def test_extensionless_database_and_journal_named_regular_file_survive(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            (src/'tax-notes-journal').write_text('SYNTHETIC notes, not a SQLite sidecar')
            with closing(sqlite3.connect(src/'extensionless_store')) as db:
                db.execute('CREATE TABLE evidence(value TEXT)')
                db.execute("INSERT INTO evidence VALUES ('SYNTHETIC')");db.commit()
            result=import_private_data(src,dst)
            self.assertEqual(inventory(src),inventory(dst))
            self.assertIn('tax-notes-journal',inventory(result['backup']))
            self.assertEqual(inventory(dst)['extensionless_store']['kind'],'sqlite-logical')

    def test_database_change_after_staging_blocks_publication(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            from coincat_data_transfer import migrate as real
            def changed(source,destination):
                result=real(source,destination)
                if Path(source)==src:
                    with closing(sqlite3.connect(src/'research_data'/'quotes.sqlite3')) as db:
                        db.execute('INSERT INTO samples VALUES (?,?,?)',('FAKE-CHANGED','2',b'new'));db.commit()
                return result
            with patch('coincat_data_transfer.migrate',side_effect=changed):
                with self.assertRaisesRegex(StateError,'differs'):import_private_data(src,dst)
            self.assertFalse(dst.exists())

    def test_missing_ledger_and_insufficient_disk_fail_closed(self):
        with TemporaryDirectory() as d:
            p=Path(d);empty=p/'empty';empty.mkdir()
            with self.assertRaises(StateError):import_private_data(empty,p/'new'/'private_data')
            src=source_fixture(p/'old')
            with patch('coincat_data_transfer.shutil.disk_usage',return_value=NS(free=1)):
                with self.assertRaisesRegex(StateError,'Insufficient'):import_private_data(src,p/'new'/'private_data')
            self.assertFalse((p/'new'/'private_data').exists())

    def test_backup_corruption_is_detected_before_publication(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            from coincat_data_transfer import migrate as real
            def corrupt(source,destination):
                result=real(source,destination)
                if Path(destination).name.startswith('import-'):
                    (Path(destination)/'preferences.json').write_text('CORRUPTED SYNTHETIC COPY')
                return result
            with patch('coincat_data_transfer.migrate',side_effect=corrupt):
                with self.assertRaisesRegex(StateError,'backup'):import_private_data(src,dst)
            self.assertFalse(dst.exists())
            self.assertEqual((src/'preferences.json').read_text(),'{"synthetic": true, "excluded": ["FAKE"]}')

    def test_failed_publication_leaves_verified_backup_and_original(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            original=Path.rename
            def rename(path,target):
                if Path(path).name=='private_data' and Path(target)==dst:
                    raise OSError('SYNTHETIC publication interruption')
                return original(path,target)
            with patch.object(Path,'rename',rename):
                with self.assertRaises(OSError):import_private_data(src,dst)
            self.assertFalse(dst.exists());self.assertTrue((src/LEDGER).exists())
            backups=list((p/'new'/'private_backups').glob('import-*'))
            self.assertEqual(len(backups),1)
            self.assertEqual(inventory(backups[0]),inventory(src))

    def test_receipt_is_metadata_and_cannot_redirect_a_path_outside_data(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            import_private_data(src,dst)
            receipt=json.loads((dst/RECEIPT).read_text())
            self.assertNotIn('SYNTHETIC-ENCRYPTED-VAULT-NOT-A-KEY',json.dumps(receipt))
            receipt['files']['../outside']={'kind':'file-sha256','sha256':'0'*64}
            (dst/RECEIPT).write_text(json.dumps(receipt))
            with self.assertRaises(StateError):verify_active(dst)

    def test_second_portable_import_does_not_depend_on_first_source(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old')
            first=import_private_data(src,p/'one'/'private_data')
            second=import_private_data(first['path'],p/'two'/'private_data')
            self.assertEqual(inventory(second['path']),inventory(src))
            self.assertEqual(verify_active(second['path'])['files'],first['files'])

    def test_symlink_and_inaccessible_tree_are_not_silently_skipped(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            try:(src/'linked').symlink_to(p,target_is_directory=True)
            except OSError:self.skipTest('Host cannot create synthetic symlinks')
            with self.assertRaises(StateError):import_private_data(src,dst)
            self.assertFalse(dst.exists())


class PortableLocks(unittest.TestCase):
    def test_current_v70_lock_is_checked_even_when_an_old_lock_also_exists(self):
        with TemporaryDirectory() as d:
            root=Path(d)
            for name in ('coincat_v60_instance.lock','coincat_v70_instance.lock'):(root/name).write_bytes(b'0')
            child=subprocess.Popen([sys.executable,'-u','-c',
                "import sys\nsys.path.insert(0,sys.argv[2])\nfrom coincat_single_instance import SingleInstance\n"
                "with SingleInstance(sys.argv[1]):\n print('ready',flush=True)\n sys.stdin.read()\n",
                str(root),str(ROOT/'app')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                with self.assertRaises(StateError):
                    with _source_guard(root):pass
            finally:
                child.communicate('',timeout=5)


class PortableCleanup(unittest.TestCase):
    def test_old_private_source_is_eligible_only_after_backup_verification(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            out=import_private_data(src,dst)
            self.assertEqual(check_cleanup(src,dst)['state'],'ELIGIBLE_IMPORTED_SOURCE')
            (out['backup']/'preferences.json').write_text('SYNTHETIC CHANGED BACKUP')
            with self.assertRaisesRegex(StateError,'backup'):check_cleanup(src,dst)
            self.assertTrue(src.exists())

    def test_reopened_old_source_changes_block_retirement(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            import_private_data(src,dst)
            (src/'preferences.json').write_text('SYNTHETIC divergent old settings')
            with self.assertRaisesRegex(StateError,'changed since import'):check_cleanup(src,dst)

    def test_active_data_backups_and_ancestors_cannot_be_retired(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            out=import_private_data(src,dst)
            for candidate in (dst,dst.parent,out['backup'],out['backup'].parent):
                with self.assertRaises(StateError):check_cleanup(candidate,dst)

    def test_old_source_release_unknown_private_files_block_cleanup(self):
        with TemporaryDirectory() as d:
            p=Path(d);src=source_fixture(p/'old');dst=p/'new'/'private_data'
            import_private_data(src,dst)
            code=p/'old-source';code.mkdir();(code/'README.md').write_text('SYNTHETIC RELEASE')
            from coincat_data_transfer import _sha
            (code/'SHA256_MANIFEST_V60.json').write_text(json.dumps({'files':{'README.md':_sha(code/'README.md')}}))
            self.assertEqual(check_cleanup(code,dst)['state'],'ELIGIBLE_OLD_SOURCE_ONLY')
            (code/'forgotten.sqlite3').write_bytes(b'SYNTHETIC PRIVATE FILE')
            with self.assertRaisesRegex(StateError,'unverified'):check_cleanup(code,dst)
            self.assertTrue((code/'forgotten.sqlite3').exists())


class PortablePaths(unittest.TestCase):
    def test_default_root_and_explicit_test_override(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual(data_root(),ROOT/'private_data')
        with TemporaryDirectory() as d,patch.dict(os.environ,{'COINCAT_DATA_DIR':d}):self.assertEqual(data_root(),Path(d))

    def test_vault_uses_shared_root_without_old_appdata(self):
        from coinbase_account import encrypted_key_path
        with TemporaryDirectory() as d,patch.dict(os.environ,{'COINCAT_DATA_DIR':d}):
            self.assertEqual(encrypted_key_path(),Path(d)/'coinbase_key.dpapi')

    def test_no_versioned_launchers_or_old_data_targets(self):
        root_bats=list(ROOT.glob('*.bat'))
        self.assertEqual(len(root_bats),4)
        for p in root_bats+list((ROOT/'tools').glob('*.bat'))+list((ROOT/'verification').glob('*.bat')):
            self.assertNotRegex(p.name,r'_V\d+')
            self.assertNotIn('%APPDATA%',p.read_text())
            self.assertNotRegex(p.read_text(),r'COINCAT_[A-Z_]+_V(?:60|70)\.bat')
        for name in ('01_START_COINCAT.bat','04_FIRST_TIME_SETUP.bat','tools/RECOVER_PRIVATE_DATA.bat','tools/CHECK_OLD_FOLDER.bat'):
            source=(ROOT/name).read_text()
            self.assertTrue('%~dp0private_data' in source or ('cd /d "%~dp0.."' in source and '%CD%\\private_data' in source))

    def test_safety_verifier_accepts_arbitrary_source_folder_name(self):
        import shutil
        with TemporaryDirectory() as d:
            root=Path(d)/'CoinCat-Any-Folder-Name'
            (root/'app').mkdir(parents=True);(root/'verification').mkdir()
            shutil.copyfile(ROOT/'verification/run_verification.py',root/'verification/run_verification.py')
            shutil.copyfile(ROOT/'app/coincat_live.py',root/'app/coincat_live.py')
            shutil.copyfile(ROOT/'app/coincat_spot_execution.py',root/'app/coincat_spot_execution.py')
            shutil.copyfile(ROOT/'app/coincat_launcher.py',root/'app/coincat_launcher.py')
            shutil.copyfile(ROOT/'app/coincat_shadow_trader.py',root/'app/coincat_shadow_trader.py')
            shutil.copyfile(ROOT/'app/coincat_order_services.py',root/'app/coincat_order_services.py')
            (root/'SHA256_MANIFEST.json').write_text('{"files": {}}')
            run=subprocess.run([sys.executable,str(root/'verification/run_verification.py'),'pilot'],
                               capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('default-ON bounded beta guard / maker-only adapter',run.stdout)
            self.assertIn('NOT VERIFIED',run.stdout)


if __name__=='__main__':unittest.main()
