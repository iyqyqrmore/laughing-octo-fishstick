"""Real SQLite lifecycle faults; retain objects/tracebacks through deletion."""
from contextlib import closing
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from coincat_beta_store import BetaBlocked,pack
from coincat_shadow_trader import ShadowTrader,validate
from coincat_trial_store import TrialStore
from offline_tests import test_resumable_trial as fixtures
from offline_tests.trial_sqlite_resources import trial_sqlite_probe


class TrialSQLiteLifecycle(unittest.TestCase):
    def make(self,path):
        clock=fixtures.Clock();engine=ShadowTrader(path,clock=clock.wall,monotonic_ns=clock.ns)
        engine.start(fixtures.account(clock),fixtures.PortfolioConfig());return engine.store
    def mutate(self,path,sql,parameters=()):
        with closing(sqlite3.connect(path)) as db,db,closing(db.cursor()) as cursor:cursor.execute(sql,parameters)
    def assert_release_and_remove(self,probe,path):
        probe.assert_released(self,path);path.unlink()
        self.assertFalse(path.exists());probe.assert_closed(self)
    def test_success_create_load_commit_read_and_checkpoint_release_all_handles(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';store=self.make(path);original=store.state()
            probe.assert_closed(self);store.change('HANDLE_PROBE','once',{},lambda s:s.update(reason='LIFECYCLE_PROBE'))
            probe.assert_closed(self);store.flush_clock();probe.assert_closed(self)
            self.assertTrue(store.events());probe.assert_closed(self)
            loaded=TrialStore(path,validate=validate);self.assertEqual(loaded.state()['original'],original['original'])
            self.assertEqual(loaded.state()['config'],original['config'])
            self.assert_release_and_remove(probe,path)
            if sys.platform=='win32':self.assertEqual(probe.native_checks,1)
    def test_duplicate_and_conflicting_event_returns_release_handles(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';store=self.make(path)
            store.change('EVENT','stable',{},lambda s:s.update(reason='UNCHANGED_ON_DUPLICATE'))
            self.assertEqual(store.change('EVENT','stable',{},lambda s:self.fail('duplicate action ran'))['state'],'DUPLICATE_IGNORED')
            with self.assertRaises(BetaBlocked):store.change('EVENT','stable',{'conflict':True},lambda s:None)
            self.assert_release_and_remove(probe,path)
    def test_action_and_evidence_failure_roll_back_and_close_with_traceback_held(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';store=self.make(path);saved=store.state();errors=[]
            def fail(s):raise RuntimeError('SYNTHETIC_CALLBACK_FAILURE')
            for action,evidence in ((fail,None),(lambda s:s.update(reason='MUST_ROLL_BACK'),fail)):
                try:store.change('FAILURE','failure-'+str(len(errors)),{},action,evidence=evidence)
                except RuntimeError as error:errors.append(error)
                else:self.fail('Expected callback failure')
                self.assertIsNotNone(errors[-1].__traceback__);probe.assert_closed(self)
                self.assertEqual(store.state(),saved);self.assertEqual(TrialStore(path,validate=validate).state(),saved)
            self.assert_release_and_remove(probe,path)
    def test_stale_writer_and_corrupt_checkpoint_write_rejections_close(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';store=self.make(path);stale=TrialStore(path,validate=validate)
            store.change('ADVANCE','advance',{},lambda s:s.update(reason='LATEST'))
            with self.assertRaises(BetaBlocked):stale.flush_clock()
            with self.assertRaises(BetaBlocked):stale.change('STALE','stale',{},lambda s:None)
            self.mutate(path,"UPDATE trial_clock SET digest='synthetic-corruption'");before=path.read_bytes()
            with self.assertRaises(BetaBlocked):store.flush_clock()
            self.assertEqual(path.read_bytes(),before);self.assert_release_and_remove(probe,path)
    def test_corrupt_file_missing_table_digest_and_identity_load_failures_close(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            for kind in ('invalid-file','missing-table','bad-digest','identity-conflict'):
                with self.subTest(kind=kind):
                    path=Path(directory)/(kind+'.sqlite3');store=self.make(path)
                    if kind=='invalid-file':path.write_bytes(b'SYNTHETIC_INVALID_SQLITE_FILE')
                    elif kind=='missing-table':self.mutate(path,'DROP TABLE trial_clock')
                    elif kind=='bad-digest':self.mutate(path,"UPDATE trial_clock SET digest='bad'")
                    else:
                        clock=deepcopy(store.clock);clock['trial_id']='synthetic-other-trial';raw=pack(clock)
                        self.mutate(path,'UPDATE trial_clock SET payload=?,digest=?',(raw,hashlib.sha256(raw.encode()).hexdigest()))
                    before=path.read_bytes()
                    with self.assertRaises((BetaBlocked,sqlite3.DatabaseError)):TrialStore(path,validate=validate)
                    self.assertEqual(path.read_bytes(),before);self.assert_release_and_remove(probe,path)
    def test_wrong_application_and_schema_version_failures_close_before_body(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            for pragma in ('application_id','user_version'):
                with self.subTest(pragma=pragma):
                    path=Path(directory)/(pragma+'.sqlite3');self.make(path);self.mutate(path,'PRAGMA '+pragma+'=1')
                    before=path.read_bytes()
                    with self.assertRaisesRegex(BetaBlocked,'WRONG_TRIAL_DATABASE_OR_VERSION'):TrialStore(path,validate=validate)
                    self.assertEqual(path.read_bytes(),before);self.assert_release_and_remove(probe,path)
    def test_partial_initialization_fault_closes_and_preserves_failed_file(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            seed=Path(directory)/'seed.sqlite3';initial=self.make(seed).state();path=Path(directory)/'trial.sqlite3'
            def fault(sql):
                if sql.startswith('CREATE TABLE trial_clock'):raise sqlite3.OperationalError('SYNTHETIC_SCHEMA_CREATION_FAILURE')
            probe.fault=fault
            with self.assertRaises(sqlite3.OperationalError):TrialStore(path,initial=initial,validate=validate)
            probe.fault=None;self.assertTrue(path.exists());before=path.read_bytes();probe.assert_released(self,path)
            with self.assertRaises(sqlite3.DatabaseError):TrialStore(path,validate=validate)
            self.assertEqual(path.read_bytes(),before)
            self.assert_release_and_remove(probe,path);self.assert_release_and_remove(probe,seed)
    def test_metadata_sql_and_baseexception_faults_close_cursor_and_connection(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';self.make(path);before=path.read_bytes();errors=[]
            for failure in (sqlite3.OperationalError('SYNTHETIC_METADATA_FAILURE'),KeyboardInterrupt('SYNTHETIC_INTERRUPT')):
                def fault(sql):
                    if sql=='PRAGMA user_version':raise failure
                probe.fault=fault
                try:TrialStore(path,validate=validate)
                except BaseException as error:errors.append(error)
                else:self.fail('Expected metadata fault')
                probe.fault=None;self.assertIs(errors[-1],failure);probe.assert_closed(self)
                self.assertEqual(path.read_bytes(),before)
            self.assert_release_and_remove(probe,path)
    def test_non_ok_integrity_result_closes_without_rewriting_database(self):
        import coincat_trial_store as module
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';self.make(path);before=path.read_bytes();original=module._one
            def result(db,sql,parameters=()):
                row=original(db,sql,parameters)
                return ('SYNTHETIC_INTEGRITY_FAILURE',) if sql=='PRAGMA quick_check(1)' else row
            with patch.object(module,'_one',side_effect=result):
                with self.assertRaisesRegex(BetaBlocked,'TRIAL_INTEGRITY_REVIEW_REQUIRED'):TrialStore(path,validate=validate)
            self.assertEqual(path.read_bytes(),before);self.assert_release_and_remove(probe,path)
    def test_active_cursor_fetch_and_commit_failures_close_with_tracebacks_retained(self):
        with trial_sqlite_probe() as probe,TemporaryDirectory() as directory:
            path=Path(directory)/'trial.sqlite3';store=self.make(path);saved=store.state();errors=[]
            def fetch_fault(sql):
                if sql=='PRAGMA application_id':raise sqlite3.DatabaseError('SYNTHETIC_FETCH_FAILURE')
            probe.fetch_fault=fetch_fault
            try:TrialStore(path,validate=validate)
            except sqlite3.DatabaseError as error:errors.append(error)
            else:self.fail('Expected active-cursor fetch failure')
            probe.fetch_fault=None;probe.assert_closed(self)
            def commit_fault():raise sqlite3.OperationalError('SYNTHETIC_COMMIT_FAILURE')
            probe.commit_fault=commit_fault
            try:store.change('FAIL_COMMIT','commit-failure',{},lambda s:s.update(reason='MUST_ROLL_BACK'))
            except sqlite3.OperationalError as error:errors.append(error)
            else:self.fail('Expected commit failure')
            probe.commit_fault=None
            self.assertTrue(all(e.__traceback__ is not None for e in errors));probe.assert_closed(self)
            self.assertEqual(store.state(),saved);self.assertEqual(TrialStore(path,validate=validate).state(),saved)
            self.assert_release_and_remove(probe,path)
