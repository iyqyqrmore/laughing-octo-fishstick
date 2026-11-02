"""Redaction, bounded recording and read-only helper protocol; no HTTP network."""
from copy import deepcopy
import argparse
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coincat_monitor import (MonitorPublisher,capture,encode,read_snapshot,status,validate,
    MAX_SNAPSHOT,HISTORY_FILES)
from coincat_monitor_server import MonitorHandler,access_token,tailscale_name
from coincat_recovery import Recovery
from coincat_simple_diagnostics import make_report
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_native_receipts import NOW
from offline_tests.test_v95_eth_growth import prepare,run_growth

SECRET='PRIVATE_NATIVE_QUANTITY_9876543.210987654321'


def app_fixture():
    result=dict(scan=7,at=NOW,fee_evidence=dict(fresh=True,captured_at=NOW,maker=SECRET),
        rows=[dict(market=dict(pair='ADA-ETH'),quote_observed_at=NOW,
            observation_state='SETUP_ACTIVE_OBSERVABLE',blockers=['QUOTE_WIDE',SECRET],
            hypothesis=dict(entry_at=NOW-60,expiry_at=NOW+3600,scenario=dict(receipts=SECRET),amount_eth=SECRET))],
        study_counts=dict(setups=1,private_amount=SECRET),private_path=SECRET)
    recovery=Recovery();recovery.start()
    return SimpleNamespace(last_result=result,scanner=SimpleNamespace(account_at=NOW,balances=SECRET),
        recovery=recovery,companions=[SimpleNamespace(get=lambda:'ADA')],running=True,busy=False,
        connected=True,last_error=None,applied_config=SimpleNamespace(amount_eth=SECRET),credentials=SECRET)


def snapshot(*,at=NOW,sequence=1,lifecycle='OPEN'):
    return capture(app_fixture(),session='a'*32,sequence=sequence,manifest_sha256='b'*64,
        now=at,lifecycle=lifecycle)


def wait_for(condition):
    deadline=time.monotonic()+3
    while not condition() and time.monotonic()<deadline:time.sleep(.005)
    if not condition():raise AssertionError('Monitor worker did not settle')


class MonitorProjection(unittest.TestCase):
    def test_capture_omits_native_values_credentials_paths_and_uncontrolled_errors(self):
        value=snapshot();raw=encode(value).decode()
        self.assertNotIn(SECRET,raw);self.assertNotIn('amount_eth',raw);self.assertNotIn('receipts',raw)
        self.assertEqual(value['products'][0]['reasons'],['QUOTE_WIDE','UNKNOWN'])
        self.assertEqual(value['observations']['setups'],1)
        self.assertEqual(value['companions'],['ADA']);self.assertEqual(value['manifest_sha256'],'b'*64)
        app=app_fixture();app.recovery.last_failure=dict(stage=SECRET,category=SECRET,error_class=SECRET,status=SECRET)
        value=capture(app,session='a'*32,sequence=2,now=NOW)
        self.assertEqual(value['health']['last_failure'],dict(stage='UNKNOWN',category='UNKNOWN',error_class='UNKNOWN',status=None))

    def test_reader_rejects_extra_fields_at_every_level(self):
        for keys in ((),('health',),('observations',),('products',0)):
            with self.subTest(keys=keys),TemporaryDirectory() as folder:
                value=snapshot();obj=value
                for key in keys:obj=obj[key]
                obj['native_balance']=SECRET
                (Path(folder)/'latest.json').write_text(json.dumps(value))
                result=status(folder,now=NOW)
                self.assertEqual(result['state'],'INVALID_SNAPSHOT');self.assertIsNone(result['snapshot'])
                self.assertNotIn(SECRET,str(result))

    def test_reader_rejects_malformed_duplicate_nonfinite_and_oversized_payloads(self):
        raw=encode(snapshot()).decode()
        candidates=['{bad json',raw.replace('"sequence":1','"sequence":1,"sequence":2'),
            raw.replace('"sequence":1','"sequence":true'),raw.replace('"captured_at":'+str(NOW),'"captured_at":NaN'),
            ' '*MAX_SNAPSHOT+'x']
        with TemporaryDirectory() as folder:
            path=Path(folder)/'latest.json'
            for candidate in candidates:
                path.write_text(candidate)
                self.assertEqual(status(folder,now=NOW)['state'],'INVALID_SNAPSHOT')

    def test_export_time_freshness_does_not_trust_old_heartbeat_or_fee_flags(self):
        with TemporaryDirectory() as folder:
            (Path(folder)/'latest.json').write_bytes(encode(snapshot()))
            fresh=status(folder,now=NOW+5)
            self.assertEqual(fresh['state'],'APP_REPORTING');self.assertTrue(fresh['ages']['fee_valid_now'])
            self.assertTrue(fresh['ages']['products'][0]['quote_within_age_limit'])
            stale=status(folder,now=NOW+21600)
            self.assertEqual(stale['state'],'APP_NOT_REPORTING');self.assertEqual(stale['ages']['last_good_scan_s'],21600)
            self.assertFalse(stale['ages']['fee_valid_now']);self.assertFalse(stale['ages']['authenticated_fresh'])
            self.assertFalse(stale['ages']['products'][0]['quote_within_age_limit'])
            self.assertTrue(stale['ages']['products'][0]['expired'])
            self.assertEqual(stale['ages']['products'][0]['current_setup_state'],'SETUP_EXPIRED')
            paused=status(folder,now=NOW+31)
            self.assertEqual(paused['ages']['products'][0]['current_setup_state'],'SETUP_ACTIVE_UNPRICED')
            self.assertEqual(paused['served_at'],NOW+31)
            future=status(folder,now=NOW-1)
            self.assertEqual(future['state'],'APP_NOT_REPORTING');self.assertFalse(future['ages']['fee_valid_now'])

    def test_explicit_close_and_disable_are_distinct_from_missing_heartbeat(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(status(folder)['state'],'WAITING_FOR_APP')
            for lifecycle,expected in [('CLOSED','APP_CLOSED'),('DISABLED','MONITOR_DISABLED')]:
                (Path(folder)/'latest.json').write_bytes(encode(snapshot(lifecycle=lifecycle)))
                value=status(folder,now=NOW)
                self.assertEqual(value['state'],expected);self.assertFalse(value['ages']['fee_valid_now'])


class MonitorRecording(unittest.TestCase):
    def test_no_files_until_opt_in_and_final_disabled_snapshot_is_flushed(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)/'monitor';writer=MonitorPublisher(root)
            self.assertFalse(writer.publish(snapshot()));self.assertFalse(root.exists())
            self.assertTrue(writer.start());self.addCleanup(writer.stop)
            writer.publish(snapshot());wait_for(lambda:writer.last_written_at==NOW)
            self.assertEqual(read_snapshot(root)['sequence'],1)
            writer.stop(snapshot(at=NOW+1,sequence=2,lifecycle='DISABLED'))
            self.assertFalse(writer.thread.is_alive());self.assertFalse(writer.enabled)
            self.assertEqual(read_snapshot(root)['lifecycle'],'DISABLED')
            self.assertFalse(list(root.glob('*.tmp')))

    def test_one_writer_coalesces_queued_samples_and_writes_final_close(self):
        with TemporaryDirectory() as folder:
            writer=MonitorPublisher(folder);started=threading.Event();release=threading.Event()
            original=writer._write
            def delayed(*args,**kwargs):
                started.set()
                if not release.wait(2):raise AssertionError('Test did not release monitor writer')
                return original(*args,**kwargs)
            with patch.object(writer,'_write',side_effect=delayed):
                writer.start();self.addCleanup(writer.stop)
                writer.publish(snapshot());self.assertTrue(started.wait(1))
                for i in range(2,20):writer.publish(snapshot(at=NOW+i,sequence=i))
                self.assertLessEqual(writer.queue.qsize(),1);self.assertFalse(writer.start())
                release.set();writer.stop(snapshot(at=NOW+20,sequence=20,lifecycle='CLOSED'))
            self.assertFalse(writer.thread.is_alive())
            latest=read_snapshot(folder)
            self.assertEqual(latest['sequence'],20);self.assertEqual(latest['lifecycle'],'CLOSED')

    def test_disk_failure_is_sanitized_and_does_not_leave_worker_running(self):
        with TemporaryDirectory() as folder:
            writer=MonitorPublisher(folder)
            with patch.object(writer,'_write',side_effect=PermissionError(SECRET)):
                writer.start();self.addCleanup(writer.stop);writer.publish(snapshot())
                wait_for(lambda:writer.error is not None)
                self.assertEqual(writer.diagnostics()['error'],'MONITOR_WRITE_FAILED')
                self.assertNotIn(SECRET,str(writer.diagnostics()));writer.stop()
            self.assertFalse(writer.thread.is_alive())

    def test_brief_windows_sharing_lock_is_retried_without_losing_latest_snapshot(self):
        with TemporaryDirectory() as folder:
            writer=MonitorPublisher(folder);writer.session='a'*32
            from coincat_monitor import os
            original=os.replace;calls=[]
            def replace(source,destination):
                calls.append(destination)
                if len(calls)<3:raise PermissionError('Synthetic sharing lock')
                return original(source,destination)
            value=snapshot()
            with patch('coincat_monitor.os.replace',side_effect=replace):writer._write(value,encode(value))
            self.assertEqual(read_snapshot(folder)['sequence'],1);self.assertEqual(len(calls),3)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_history_rotation_is_bounded_and_never_touches_unrelated_files(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);sentinel=root/'owner_records.txt';sentinel.write_text(SECRET)
            cap=len(encode(snapshot()))*2+100;writer=MonitorPublisher(root,history_bytes=cap);writer.session='a'*32
            for i in range(1,30):
                value=snapshot(at=NOW+i,sequence=i);writer._write(value,encode(value),history=True)
            files=list(root.glob('snapshots*.jsonl'))
            self.assertEqual(len(files),HISTORY_FILES);self.assertLessEqual(sum(p.stat().st_size for p in files),cap*HISTORY_FILES)
            for path in files:
                for line in path.read_text().splitlines():validate(json.loads(line))
            self.assertEqual(sentinel.read_text(),SECRET);self.assertEqual(read_snapshot(root)['sequence'],29)


class MonitorProtocol(unittest.TestCase):
    def request(self,folder,method='GET',path='/api/status',*,token=True,host='127.0.0.1:8765',origin=None):
        handler=MonitorHandler.__new__(MonitorHandler)
        handler.server=SimpleNamespace(directory=Path(folder),token='a'*43,hosts={'127.0.0.1:8765','office.example.ts.net:8443'},
            origins={'http://127.0.0.1:8765','https://office.example.ts.net:8443'})
        headers=[method+' '+path+' HTTP/1.1','Host: '+host]
        if token:headers.append('Authorization: Bearer '+'a'*43)
        if origin is not None:headers.append('Origin: '+origin)
        handler.rfile=BytesIO(('\r\n'.join(headers)+'\r\n\r\n').encode('ascii'))
        handler.wfile=BytesIO();handler.client_address=('127.0.0.1',12345);handler.close_connection=True
        handler.handle_one_request()
        head,body=handler.wfile.getvalue().split(b'\r\n\r\n',1)
        return int(head.split()[1]),head.decode(),body.decode()

    def test_read_token_persists_separately_and_never_enters_status(self):
        with TemporaryDirectory() as folder:
            first=access_token(folder);self.assertEqual(access_token(folder),first)
            self.assertEqual(len(first),43);self.assertNotIn(first,json.dumps(status(folder)))
            self.assertEqual((Path(folder)/'monitor_read_token.key').read_text().strip(),first)

    def test_authentication_origin_and_host_are_required_without_cors(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(self.request(folder,token=False)[0],401)
            self.assertEqual(self.request(folder,origin='https://untrusted.example')[0],403)
            self.assertEqual(self.request(folder,host='untrusted.example')[0],403)
            code,head,body=self.request(folder,host='office.example.ts.net:8443',origin='https://office.example.ts.net:8443')
            self.assertEqual(code,200);self.assertIn('no-store',head);self.assertNotIn('Access-Control-Allow-Origin',head)
            self.assertNotIn('a'*43,body);self.assertEqual(json.loads(body)['state'],'WAITING_FOR_APP')

    def test_get_returns_validated_redacted_data_and_mutations_and_file_paths_are_rejected(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'latest.json';path.write_bytes(encode(snapshot()));before=path.read_bytes()
            code,_,body=self.request(folder)
            self.assertEqual(code,200);self.assertNotIn(SECRET,body)
            for method in ('POST','PUT','PATCH','DELETE','OPTIONS','HEAD'):
                self.assertEqual(self.request(folder,method=method)[0],405)
            for route in ('/api/status?token=bad','/../private_data','/monitor_read_token.key','/apply','/stop','/update'):
                self.assertEqual(self.request(folder,path=route)[0],404)
            self.assertEqual(path.read_bytes(),before)
            value=snapshot();value['credentials']=SECRET;path.write_text(json.dumps(value))
            code,_,body=self.request(folder)
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['state'],'INVALID_SNAPSHOT')
            self.assertNotIn(SECRET,body)

    def test_tailnet_name_requires_full_dns_name_and_has_no_command_or_url_injection(self):
        self.assertEqual(tailscale_name('OFFICE.EXAMPLE.ts.net.'),'office.example.ts.net')
        for raw in ('https://office.example.ts.net','office.example.ts.net:8443','127.0.0.1','*.ts.net','office..ts.net','x.ts.net/stop','x.ts.net;command'):
            with self.subTest(raw=raw),self.assertRaises(argparse.ArgumentTypeError):tailscale_name(raw)


class MonitorGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def test_opt_in_does_not_change_research_and_stop_is_observed_without_stopping_helper(self):
        app=self.app;app.monitor.directory=Path(self.temp.name)/'support_monitor'
        _,client,scanner=prepare(self.temp.name);app.scanner=scanner;app.connected=True
        app.allocation_editor.clock=lambda:NOW;app._render_wallet();app.companions[0].set('ADA')
        app.mixer.controls['amount_eth'].set('.1');app._apply_plan()
        app.last_result=run_growth(scanner,client);app.running=True;app.recovery.start()
        before=fixtures.ledger_dump(app.ledger);config=app.applied_config;generation=app.generation
        setup=deepcopy(scanner.maker_study.active);reads=list(client.calls)
        self.assertFalse(app.monitor.enabled);self.assertFalse(app.monitor.directory.exists())
        app.monitor_enabled.set(True);app._monitor_changed()
        wait_for(lambda:app.monitor.last_written_at is not None)
        self.assertIs(app.applied_config,config);self.assertEqual(app.generation,generation);self.assertTrue(app.running)
        self.assertEqual(scanner.maker_study.active,setup);self.assertEqual(client.calls,reads)
        app._stop();app._monitor_tick()
        wait_for(lambda:not read_snapshot(app.monitor.directory)['health']['running'])
        self.assertTrue(app.monitor.enabled);self.assertEqual(read_snapshot(app.monitor.directory)['health']['connection_state'],'STOPPED')
        self.assertIn('local_monitor',make_report(app,now=NOW));self.assertNotIn(str(app.monitor.directory),make_report(app,now=NOW))
        app.monitor_enabled.set(False);app._monitor_changed()
        self.assertFalse(app.monitor.thread.is_alive());self.assertNotIn('monitor',app._after)
        self.assertEqual(read_snapshot(app.monitor.directory)['lifecycle'],'DISABLED')
        self.assertEqual(before,fixtures.ledger_dump(app.ledger));self.assertEqual(client.calls,reads)

    def test_close_flushes_closed_heartbeat_and_cancels_monitor_timer(self):
        app=self.app;app.monitor.directory=Path(self.temp.name)/'support_monitor'
        app.monitor_enabled.set(True);app._monitor_changed()
        app._close()
        self.assertFalse(app.monitor.thread.is_alive());self.assertFalse(app._after)
        self.assertEqual(read_snapshot(app.monitor.directory)['lifecycle'],'CLOSED')

    def test_bad_monitor_sample_cannot_block_research_controls_or_clean_close(self):
        app=self.app;app.monitor.directory=Path(self.temp.name)/'support_monitor'
        with patch.object(app.monitor,'sample',side_effect=RuntimeError(SECRET)):
            app.monitor_enabled.set(True);app._monitor_changed()
            self.assertIn('Research unchanged',app.monitor_text.get());self.assertNotIn(SECRET,app.monitor_text.get())
            app._stop();app._close()
        self.assertFalse(app.monitor.thread.is_alive())
