"""Synthetic stopped-session reporting and concurrent-file export regressions.

No network, user financial data, settings changes or order permission.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import unittest

from coincat_complete_diagnostics import (CompleteReportSession,_complete_sections,
    _diagnostic_storage_snapshot,_section,_shadow_section)
from coincat_live_forward_store import ForwardStore
from coincat_v507_shadow_arm import ShadowArmedResearch
from offline_tests.test_v703_chain_contract import make_plan,NOW


class StoppedDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.session=ShadowArmedResearch(experimental=True)
        self.session.arm(connected=True,real_arm=False,stopped=False,
            verified_balances=True,usd_coverage=True,enrolled_quantities={'USD':'100'},
            fresh_usd_rates={'USD':'1'},now=NOW-1)
        self.addCleanup(lambda:[w.close() for w in self.session.fifo_portfolios.values()])
        quote={'BTC-USD':('100','100.01',NOW)}
        self.session.observe(now=NOW,quotes=quote,usd_rates={'USD':'1','BTC':'100'},
            route_ideas=[make_plan(quantity='100')],strict_quotes=True,approved_catalog=['BTC-USD'])
        self.assertEqual(self.session.fifo_posted,1)
        self.session.disarm(now=NOW+1)
        self.app=NS(ledger=NS(path=self.root/'synthetic-ledger.sqlite3'),last_cycle={},
            experimental_shadow=self.session,shadow_pilot=NS(armed=False),
            forward=ForwardStore(self.root/'research_data'/'synthetic-market.sqlite3'))
        # Arbitrary synthetic ledger bytes prove selected report only stats it.
        self.app.ledger.path.write_bytes(b'SYNTHETIC-FINANCIAL-KEEP')

    def render(self):
        with patch('coincat_v507_shadow_arm.time.time',return_value=NOW+2):
            return _section('SHADOW ROTATION & SIMULATED ROUTES',lambda:_shadow_section(self.app,NOW+2))

    def assert_retained_wallet(self,body):
        snap=self.session.snapshot(now=NOW+2)
        value=snap['shadow_fifo_bands']['TAKER_ASK']
        self.assertIn('Experimental mode: DISARMED',body)
        self.assertIn('Experimental session previously started: True',body)
        self.assertIn('Simulated taker FIFO routes: 1',body)
        self.assertIn('Estimated modeled exchange fees USD: '+value['estimated_fees_usd'],body)
        self.assertIn('Evolving experimental wallet vs same-time frozen HOLD USD: '+value['counterfactual_portfolio_vs_hold_usd'],body)

    def test_stop_preserves_counts_wallet_fees_marks_and_manual_arm(self):
        before=self.session.snapshot(now=NOW+2);ledger=self.app.ledger.path.read_bytes()
        body,ok=self.render()
        self.assertTrue(ok);self.assert_retained_wallet(body)
        self.assertIn('PASSIVE PUBLIC FORWARD-COST OBSERVATIONS',body)
        self.assertEqual(before,self.session.snapshot(now=NOW+2))
        self.assertEqual(ledger,self.app.ledger.path.read_bytes())
        self.assertFalse(self.session.armed)

    def test_real_disappearing_wal_race_retries_and_keeps_complete_results(self):
        sidecar=self.root/'research_data'/'other-synthetic.sqlite3-wal'
        sidecar.write_bytes(b'SYNTHETIC-TRANSIENT')
        original=Path.stat;calls=[0]
        def stat(path,*args,**kwargs):
            if path==sidecar:
                calls[0]+=1
                if calls[0]==2:sidecar.unlink()
            return original(path,*args,**kwargs)
        with patch.object(Path,'stat',stat):body,ok=self.render()
        self.assertFalse(sidecar.exists());self.assertTrue(ok)
        self.assert_retained_wallet(body)
        self.assertNotIn('SECTION UNAVAILABLE',body)

    def test_persistent_storage_failure_keeps_wallet_and_flags_partial(self):
        with patch('coincat_storage.storage_health',side_effect=FileNotFoundError('/PRIVATE/PATH/key.dpapi')) as health:
            body,ok=self.render()
        self.assertEqual(health.call_count,2);self.assertFalse(ok)
        self.assert_retained_wallet(body)
        self.assertIn('DECISION & STORAGE SNAPSHOT',body)
        self.assertIn('SECTION UNAVAILABLE: FileNotFoundError',body)
        self.assertIn('coincat_complete_diagnostics.py:_diagnostic_storage_snapshot:',body)
        self.assertNotIn('/PRIVATE',body);self.assertNotIn('key.dpapi',body)

    def test_failed_learning_query_does_not_erase_stopped_wallet(self):
        self.app.forward.selection=NS(summary=Mock(side_effect=OSError('/PRIVATE/ACCOUNT')))
        body,ok=self.render()
        self.assertFalse(ok);self.assert_retained_wallet(body)
        self.assertIn('PASSIVE FORWARD-COST LEARNING',body)
        self.assertIn('SECTION UNAVAILABLE: OSError',body)
        self.assertNotIn('/PRIVATE',body)

    def test_failed_route_report_does_not_erase_snowball_learning_or_wallet(self):
        with patch('coincat_complete_diagnostics.make_shadow_report',side_effect=RuntimeError('PRIVATE-REASON')):
            body,ok=self.render()
        self.assertFalse(ok);self.assert_retained_wallet(body)
        self.assertIn('PASSIVE PUBLIC FORWARD-COST OBSERVATIONS',body)
        self.assertIn('SNOWBALL IMMEDIATE USD ADVANTAGE',body)
        self.assertNotIn('PRIVATE-REASON',body)

    def test_failed_wallet_report_does_not_invent_zero_or_lose_learning(self):
        with patch('coincat_complete_diagnostics.experimental_shadow_report',side_effect=ValueError('PRIVATE')):
            body,ok=self.render()
        self.assertFalse(ok)
        self.assertIn('SECTION UNAVAILABLE: ValueError',body)
        self.assertNotIn('Simulated taker FIFO routes: 0',body)
        self.assertIn('PASSIVE PUBLIC FORWARD-COST OBSERVATIONS',body)
        self.assertIn('SNOWBALL IMMEDIATE USD ADVANTAGE',body)

    def test_partial_composite_marks_complete_report_incomplete_and_keeps_18_sections(self):
        with patch('coincat_storage.storage_health',side_effect=PermissionError('PRIVATE')):
            title,render=next((t,f) for t,f in _complete_sections(self.app,NOW+2,0)
                if t=='SHADOW ROTATION & SIMULATED ROUTES')
            with patch('coincat_complete_diagnostics._complete_sections',return_value=((title,render),)):
                session=CompleteReportSession(self.app,now=NOW+2,mono=0)
                session.step();body=session.finish()
        self.assertEqual(len(_complete_sections(self.app,NOW+2,0)),18)
        self.assertIn('SECTION COMPLETENESS: INCOMPLETE — SHADOW ROTATION & SIMULATED ROUTES',body)
        self.assertIn('Simulated taker FIFO routes: 1',body)
        self.assertNotIn('COMPLETE (1/1)',body)
        self.assertNotIn('PRIVATE',body)

    def test_report_does_not_retry_permissions_or_change_shared_storage_gate(self):
        with patch('coincat_storage.storage_health',side_effect=PermissionError('PRIVATE')) as health:
            with self.assertRaises(PermissionError):_diagnostic_storage_snapshot(self.root)
        self.assertEqual(health.call_count,1)
        from coincat_storage import financial_storage_gate
        with patch('coincat_storage.storage_health',side_effect=FileNotFoundError('PRIVATE')):
            with self.assertRaises(FileNotFoundError):financial_storage_gate(self.root)


if __name__=='__main__':unittest.main()
