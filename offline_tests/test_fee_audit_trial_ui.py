from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest
from unittest.mock import patch,MagicMock
from coincat_fee_audit import audit_day,day_bounds,statement_day,collect_day
from coincat_beta_store import BetaBlocked
from coincat_tray import TrayController,WindowsTray
from offline_tests import test_spot_manual as fixtures
from offline_tests.test_resumable_trial import Clock,account,frame

class HistoricalAudit(unittest.TestCase):
    def evidence(self):
        record,statement=fixtures.StatementCorroboration().evidence();stamp=record['fills'][0]['trade_time']
        statement.update(day=stamp[:10],zone='UTC',unresolved=[],other_day_activity=0)
        return record,statement
    def test_exact_csv_match_does_not_invent_api_currency_or_liquidity(self):
        record,statement=self.evidence();r=audit_day([record],statement)
        self.assertEqual(r['matched'],1);self.assertEqual(r['api_fee_currency_confirmed'],0)
        self.assertEqual(r['rows'][0]['csv_derived_fee_percent'],.5);self.assertEqual(r['liquidity_confirmed'],1)
        self.assertEqual(r['coverage'],'PARTIAL_EVIDENCE');self.assertFalse(r['future_fee_authority'])
        self.assertIsNone(r['rows'][0]['api_after_fees_matches'])
        record['order']['total_value_after_fees']='.0001505833'
        self.assertTrue(audit_day([record],statement)['rows'][0]['api_after_fees_matches'])
    def test_reported_nonquote_currency_conflict_incomplete_duplicate_and_missing_remain_partial(self):
        for mode in ('currency','incomplete','duplicate','missing','commission','afterfees'):
            record,statement=self.evidence()
            if mode=='currency':record['fills'][0]['fee_currency']='ETH'
            if mode=='incomplete':record['complete']=False
            if mode=='duplicate':statement['reports']*=2
            if mode=='commission':record['fills'][0]['commission']='.0000001'
            if mode=='afterfees':record['order']['total_value_after_fees']='.1'
            report=audit_day([] if mode=='missing' else [record],statement,api_coverage='HISTORY_EXHAUSTED_AS_REPORTED')
            with self.subTest(mode=mode):self.assertEqual(report['matched'],0);self.assertEqual(report['coverage'],'PARTIAL_EVIDENCE')
    def test_dst_day_boundaries_and_day_filter_do_not_include_other_statement_trades(self):
        start,end=day_bounds('2026-11-01');self.assertEqual(end-start,25*3600)
        start,end=day_bounds('2026-03-08');self.assertEqual(end-start,23*3600)
        with TemporaryDirectory() as d:
            p=Path(d)/'synthetic.csv'
            with p.open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['ID','Timestamp','Transaction Type','Asset','Quantity Transacted','Notes'])
                writer.writerow(['synthetic','2026-11-04 16:08:08 UTC','Advanced Trade Sell','ETH','-.005','Sold 0.005 ETH for 0.0001505833 BTC on ETH-BTC at 0.030268 BTC/ETH'])
                writer.writerow(['other','2026-10-04 16:08:08 UTC','Advanced Trade Sell','ETH','-.005','unsupported outside scope'])
            report=statement_day(p,'2026-11-04');self.assertEqual(len(report['reports']),1);self.assertEqual(report['unresolved'],[])
    def test_local_get_only_sweep_includes_old_gtc_creation_and_requires_exhaustion(self):
        record,statement=self.evidence();clock=Clock();scope=record['order']['retail_portfolio_id']
        record['order']['created_time']='2026-01-01T00:00:00Z'
        class Fake:
            def get_api_key_permissions(self):return dict(can_view=True,portfolio_uuid=scope)
            def get_fills(self,**kwargs):return dict(fills=deepcopy(record['fills']),has_next=False,cursor='')
            def get_order(self,**kwargs):return dict(order=deepcopy(record['order']))
            def list_orders(self,**kwargs):raise AssertionError('Creation-filter list not required')
            def get_accounts(self,**kwargs):raise AssertionError('Account balances not required')
        r=collect_day(Fake(),statement['day'],'UTC',clock=clock.wall,monotonic=clock.monotonic)
        self.assertTrue(r['complete']);self.assertEqual(len(r['records']),1)
        self.assertEqual(audit_day(r['records'],statement,api_coverage=r['coverage'])['matched'],1)
        fake=Fake();fake.get_fills=lambda **kw:dict(fills=record['fills'],has_next=True,cursor='same')
        self.assertFalse(collect_day(fake,statement['day'],'UTC',clock=clock.wall,monotonic=clock.monotonic)['complete'])

class TrayPolicy(unittest.TestCase):
    def test_hide_keeps_monitoring_pause_separate_exit_explicit(self):
        root=MagicMock();pause=MagicMock();close=MagicMock();backend=MagicMock()
        tray=TrayController(root,status=lambda:('RUNNING','6 h / 168','USD UNKNOWN'),toggle=pause,open_trial=MagicMock(),exit_safely=close,shutdown=MagicMock(),backend=backend)
        self.assertTrue(tray.hide());root.withdraw.assert_called_once();pause.assert_not_called();close.assert_not_called()
        tray.menu()[4][1]();pause.assert_called_once();tray.menu()[-1][1]();close.assert_called_once()
        tray.open();root.deiconify.assert_called_once();tray.close();backend.close.assert_called_once()
    def test_native_shutdown_query_always_allows_and_does_not_wait_network(self):
        native=WindowsTray.__new__(WindowsTray);native.root=MagicMock();native.shutdown=MagicMock()
        self.assertEqual(native.dispatch(0,0x11,1,0),1);native.shutdown.assert_not_called()
        self.assertEqual(native.dispatch(0,0x16,1,0),0);native.root.after.assert_called_once_with(0,native.shutdown)
