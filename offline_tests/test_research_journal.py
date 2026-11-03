"""Persistent prospective experiments: exact restart, unknowns, gaps and no orders."""
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest

from coincat_research_journal import (ResearchJournal,JournalError,register_from_eth,
    public_status,validate_public)
from coincat_adaptive_eth import ResearchFunds,Frame
from coincat_monitor import capture,encode,validate
from coincat_simple_diagnostics import make_report
from offline_tests.test_adaptive_eth import frame,inputs,assume,ETH_BTC,BTC_SOL
from offline_tests.test_native_receipts import NOW
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_v100_eth_growth import prepare,run_growth


class JournalPersistence(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'research.sqlite3'
        self.journal=ResearchJournal(self.path,clock=lambda:NOW)

    def register(self,reference='case',fill_state='SIMULATED_ASSUMPTION',journal=None):
        funds=ResearchFunds(D(1));assume(funds,'seed',ETH_BTC)
        return (journal or self.journal).register(reference,funds=funds,leg=BTC_SOL,quantity=D(1),
            frame=frame(),horizon_s=60,signal_id='MANUAL_OUTPERFORMANCE',
            fill_state=fill_state,slippage_bps=D(0))

    def test_frozen_registration_and_exact_decimals_survive_restart(self):
        registered=self.register();external=self.journal.case('case')
        external['latest']['signal']['id']='MUTATED'
        reopened=ResearchJournal(self.path,clock=lambda:NOW+30)
        restored=reopened.case('case')
        self.assertEqual(restored['registration'],registered['registration'])
        self.assertEqual(restored['latest']['signal']['id'],'MANUAL_OUTPERFORMANCE')
        self.assertIsInstance(restored['latest']['hold']['BTC'],D)
        self.assertIsInstance(restored['latest']['frame'],Frame)
        self.assertEqual(restored['registration']['simulated_event_count'],1)
        self.assertEqual([e['kind'] for e in reopened.events('case')],['REGISTERED'])

    def test_retroactive_registration_and_duplicate_rewrite_are_rejected(self):
        self.register();original=self.journal.case('case')['registration']
        with self.assertRaisesRegex(JournalError,'ALREADY_REGISTERED'):self.register()
        backdated=ResearchJournal(Path(self.temp.name)/'later.sqlite3',clock=lambda:NOW+61)
        with self.assertRaisesRegex(JournalError,'PROSPECTIVE'):self.register(journal=backdated)
        self.assertEqual(self.journal.case('case')['registration'],original)
        self.assertEqual(backdated.summary()['registered'],0)

    def test_losing_horizon_is_final_and_never_replaced_by_later_favorable_quotes(self):
        self.register();f=frame(at=NOW+60,changes={'SOL-ETH':(D('.4'),D('.4'),NOW+60)})
        summary=self.journal.observe(f)
        self.assertEqual(summary['adverse'],1);self.assertEqual(summary['underwater_cases'],1)
        before=self.journal.case('case')
        self.assertEqual(before['latest']['outcome']['relative_eth'],D('-.6'))
        self.journal.observe(frame(at=NOW+61,changes={'SOL-ETH':(D(10),D(10),NOW+61)}))
        self.assertEqual(self.journal.case('case'),before)
        self.assertEqual(summary['edge'],'NO_DEMONSTRATED_EDGE')

    def test_restart_after_horizon_records_missed_comparison_and_gap(self):
        registered=self.register()
        reopened=ResearchJournal(self.path,clock=lambda:NOW+100)
        summary=reopened.observe(frame(at=NOW+100))
        self.assertEqual(summary['missed_horizons'],1);self.assertEqual(summary['unknown'],1)
        case=reopened.case('case')
        self.assertEqual(case['latest']['horizon_at'],registered['latest']['horizon_at'])
        self.assertEqual(case['latest']['state'],'MISSED_HORIZON')
        self.assertEqual(case['gap_episodes'],1)
        self.assertIn('OBSERVATION_GAP',[e['kind'] for e in reopened.events('case')])

    def test_no_fill_partial_unknown_and_missing_horizon_remain_separate(self):
        for i,fill in enumerate(('NO_FILL','PARTIAL_OR_UNCERTAIN_FILL','UNVERIFIED')):
            self.register(str(i),fill)
        self.journal.observe(frame(at=NOW+60))
        no_fill=self.journal.case('0')['latest']['outcome']
        self.assertEqual(no_fill['relative_eth'],D(0));self.assertIsNone(no_fill['rotation_eth'])
        for ref in ('1','2'):
            case=self.journal.case(ref)['latest'];self.assertEqual(case['state'],'UNKNOWN_AT_HORIZON')
            self.assertIsNone(case['outcome']['relative_eth'])
        self.assertEqual(self.journal.summary()['no_fill'],1)
        self.assertEqual(self.journal.summary()['unknown'],2)

    def test_current_bbo_only_evidence_cannot_be_upgraded_to_profit(self):
        self.register();self.journal.observe(frame(at=NOW+20,evidence=False))
        self.assertEqual(self.journal.summary()['unpriced_open_cases'],1)
        self.assertEqual(self.journal.summary()['underwater_cases'],0)
        self.journal.observe(frame(at=NOW+60,evidence=False))
        case=self.journal.case('case')['latest']
        self.assertEqual(case['state'],'UNKNOWN_AT_HORIZON')
        self.assertIn('DEPTH_UNVERIFIED',case['outcome']['reasons'])
        self.assertIn('FEE_CURRENCY_UNVERIFIED',case['outcome']['reasons'])
        self.assertIsNone(case['outcome']['relative_eth'])
        self.assertIsNone(case['outcome']['actual_profit_eth'])

    def test_cancellation_before_commit_rolls_back_state_and_events(self):
        self.register();before=self.journal.case('case');events=self.journal.events('case')
        class CancelAtCommit:
            def __init__(self):self.calls=0
            def is_set(self):self.calls+=1;return self.calls>=3
        result=self.journal.observe(frame(at=NOW+60),cancel=CancelAtCommit())
        self.assertEqual(result['state'],'CANCELLED')
        self.assertEqual(self.journal.case('case'),before);self.assertEqual(self.journal.events('case'),events)

    def test_duplicate_and_backward_observations_are_idempotent(self):
        self.register();f=frame(at=NOW+20)
        self.journal.observe(f);before=self.journal.case('case');events=self.journal.events('case')
        self.journal.observe(f);self.journal.observe(frame(at=NOW+10))
        self.assertEqual(self.journal.case('case'),before);self.assertEqual(self.journal.events('case'),events)

    def test_detail_cap_is_explicit_and_terminal_result_is_still_recorded(self):
        self.register()
        with patch('coincat_research_journal.MAX_DETAILS',1):
            self.journal.observe(frame(at=NOW+10,evidence=False))
            self.journal.observe(frame(at=NOW+20))
            self.journal.observe(frame(at=NOW+60))
        case=self.journal.case('case');events=self.journal.events('case')
        self.assertTrue(case['detail_truncated'])
        self.assertIn('DETAIL_HISTORY_LIMIT_REACHED',[e['kind'] for e in events])
        self.assertEqual(events[-1]['kind'],'CONDITIONAL_OUTCOME')
        self.assertEqual(self.journal.summary()['truncated_cases'],1)

    def test_case_and_storage_bounds_preserve_existing_records(self):
        with patch('coincat_research_journal.MAX_ACTIVE',1):
            self.register()
            with self.assertRaisesRegex(JournalError,'ACTIVE_LIMIT'):self.register('second')
        before=self.journal.case('case')
        capped=ResearchJournal(self.path,clock=lambda:NOW,max_bytes=1)
        with self.assertRaisesRegex(JournalError,'STORAGE_LIMIT'):capped.observe(frame(at=NOW+60))
        self.assertEqual(self.journal.case('case'),before)

    def test_unrelated_existing_database_is_refused_without_mutation(self):
        financial=Path(self.temp.name)/'financial.sqlite3'
        with closing(sqlite3.connect(financial)) as db, db:db.execute('CREATE TABLE lots(id TEXT)')
        before=financial.read_bytes()
        with self.assertRaisesRegex(JournalError,'WRONG_RESEARCH_JOURNAL_FILE'):ResearchJournal(financial)
        self.assertEqual(financial.read_bytes(),before)

    def test_corrupt_payload_and_private_values_never_enter_public_projection(self):
        self.register()
        safe=public_status(dict(self.journal.summary(),signal_id='PRIVATE_SIGNAL',inventory='PRIVATE_BALANCE'))
        self.assertNotIn('PRIVATE',str(safe));validate_public(safe)
        with self.assertRaises(JournalError):validate_public(dict(safe,inventory='PRIVATE_BALANCE'))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE experiments SET latest='not-json-private-path'")
        with self.assertRaisesRegex(JournalError,'INVALID_JOURNAL_RECORD'):self.journal.summary()

    def test_manual_source_assumption_is_explicit_and_never_uses_account_inventory(self):
        kwargs=dict(frame=frame(),initial_eth=D(1),source='BTC',target='SOL',horizon_s=60,
                    signal_id='EXPLICIT_WHAT_IF',fill_state='UNVERIFIED')
        with self.assertRaisesRegex(JournalError,'EXPLICIT_CONDITIONAL_ASSUMPTION'):
            register_from_eth(self.journal,'case',explicit_assumption=False,**kwargs)
        case=register_from_eth(self.journal,'case',explicit_assumption=True,**kwargs)
        self.assertEqual(case['registration']['simulated_event_count'],1)
        self.assertGreater(case['registration']['supplied_simulated_inventory']['BTC'],0)
        self.assertEqual(case['latest']['fill_state'],'UNVERIFIED')
        self.assertEqual(self.journal.summary()['paper_trades'],0)


    def test_verified_copy_keeps_journal_and_financial_bytes_intact(self):
        from coincat_v80_first_run import initialize_fresh,CONFIRMATION
        from coincat_data_transfer import import_private_data,inventory
        source=Path(self.temp.name)/'source'/'private_data'
        initialize_fresh(source,confirmation=CONFIRMATION)
        relative='research_data/CoinCat_Prospective_Experiments.sqlite3'
        journal=ResearchJournal(source/relative,clock=lambda:NOW)
        self.register(journal=journal)
        ledger=source/'CoinCat_Live_Orders.sqlite3';before=ledger.read_bytes()
        destination=Path(self.temp.name)/'new_install'/'private_data'
        import_private_data(source,destination)
        restored=ResearchJournal(destination/relative,clock=lambda:NOW)
        self.assertEqual(restored.case('case'),journal.case('case'))
        self.assertIn(relative,inventory(destination))
        self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual((destination/'CoinCat_Live_Orders.sqlite3').read_bytes(),before)


class JournalGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def ready(self):
        app=self.app;_,client,scanner=prepare(self.temp.name)
        app.scanner=scanner;app.connected=True;app.allocation_editor.clock=lambda:NOW
        app._render_wallet();app.companions[0].set('ADA');app.mixer.controls['amount_eth'].set(D('.1'));app._apply_plan()
        app.last_result=run_growth(scanner,client);app.running=True;app.busy=False
        app.recovery.start()
        app.journal=ResearchJournal(Path(self.temp.name)/'prospective.sqlite3',clock=lambda:NOW)
        return app,client,scanner

    def test_manual_dialog_defaults_do_not_register_and_close_cleanly(self):
        from coincat_experiment_dialog import ExperimentDialog
        app,_,_=self.ready();dialog=ExperimentDialog(app);self.root.update()
        self.assertEqual(dialog.values['initial_eth'].get(),'');self.assertEqual(dialog.values['horizon_hours'].get(),'')
        self.assertEqual(dialog.values['fill_state'].get(),'UNVERIFIED');self.assertFalse(dialog.ack.get())
        self.assertEqual(app.journal.summary()['registered'],0)
        dialog.register();self.assertTrue(dialog.error.get());self.assertEqual(app.journal.summary()['registered'],0)
        dialog.window.destroy()

    def test_registration_uses_fresh_applied_working_slice_without_financial_writes(self):
        app,client,scanner=self.ready();before=fixtures.ledger_dump(app.ledger);reads=list(client.calls)
        with patch('coincat_app.time.time',return_value=NOW):
            case=app._register_experiment(source='ETH',target='ADA',initial_eth=D('.1'),horizon_s=3600,
                signal_id='MANUAL_ETH_ADA',fill_state='UNVERIFIED',explicit_assumption=True)
        self.assertEqual(case['latest']['signal']['id'],'MANUAL_ETH_ADA')
        self.assertEqual(app.journal.summary()['registered'],1);self.assertIs(scanner.journal,app.journal)
        self.assertEqual(fixtures.ledger_dump(app.ledger),before);self.assertEqual(client.calls,reads)
        report=make_report(app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report);self.assertIn('prospective_journal',report)
        self.assertNotIn('MANUAL_ETH_ADA',report)
        snap=capture(app,session='a'*32,sequence=1,now=NOW);validate(snap)
        self.assertEqual(snap['prospective_journal']['registered'],1)
        self.assertNotIn('MANUAL_ETH_ADA',encode(snap).decode())
        with self.assertRaises(ValueError):
            snap['prospective_journal']['account_quantity']='PRIVATE';validate(snap)

    def test_stop_and_stale_funding_prevent_registration(self):
        app,_,_=self.ready();kwargs=dict(source='ETH',target='ADA',initial_eth=D('.1'),horizon_s=60,
            signal_id='MANUAL',fill_state='UNVERIFIED',explicit_assumption=True)
        app._stop()
        with self.assertRaises(ValueError):app._register_experiment(**kwargs)
        app.running=True
        with patch('coincat_app.time.time',return_value=NOW+121),self.assertRaises(ValueError):app._register_experiment(**kwargs)
        self.assertEqual(app.journal.summary()['registered'],0)

    def test_scanner_observes_only_explicit_cases_without_extra_client_calls(self):
        app,client,scanner=self.ready();scanner.journal=app.journal
        before=fixtures.ledger_dump(app.ledger);reads=list(client.calls)
        result=run_growth(scanner,client)
        self.assertEqual(result['prospective_journal']['registered'],0)
        self.assertEqual(client.calls,reads);self.assertEqual(fixtures.ledger_dump(app.ledger),before)
        app._stop();stopped=run_growth(scanner,client,cancel=app.cancel)
        self.assertEqual(stopped['state'],'CANCELLED');self.assertEqual(app.journal.summary()['registered'],0)

    def test_journal_failure_is_sanitized_and_does_not_disable_existing_observation(self):
        app,client,scanner=self.ready();scanner.journal=app.journal
        with patch.object(app.journal,'observe',side_effect=sqlite3.OperationalError('PRIVATE_PATH_OR_ACCOUNT')):
            result=run_growth(scanner,client)
        self.assertEqual(result['state'],'RESEARCH_ONLY')
        self.assertEqual(result['prospective_journal']['state'],'UNAVAILABLE')
        self.assertNotIn('PRIVATE_PATH',str(result['prospective_journal']))

    def test_local_case_view_works_stopped_and_keeps_signal_names_out_of_exports(self):
        app,_,_=self.ready()
        with patch('coincat_app.time.time',return_value=NOW):
            app._register_experiment(source='ETH',target='ADA',initial_eth=D('.1'),horizon_s=60,
                signal_id='LOCAL_PRIVATE_SIGNAL',fill_state='UNVERIFIED',explicit_assumption=True)
        app._stop();window=app._view_experiments();self.root.update()
        self.assertTrue(window.winfo_exists())
        cases=app.journal.list_cases();self.assertEqual(cases[0]['signal'],'LOCAL_PRIVATE_SIGNAL')
        self.assertEqual(cases[0]['state'],'WAITING')
        self.assertNotIn('LOCAL_PRIVATE_SIGNAL',make_report(app,now=NOW))
        window.destroy()

    def test_existing_scan_matures_an_explicit_case_without_inventing_fill_evidence(self):
        app,client,scanner=self.ready()
        with patch('coincat_app.time.time',return_value=NOW):
            app._register_experiment(source='ETH',target='ADA',initial_eth=D('.1'),horizon_s=60,
                signal_id='PROSPECTIVE_PIPELINE',fill_state='SIMULATED_ASSUMPTION',explicit_assumption=True)
        result=run_growth(scanner,client,now=NOW+60,collect=fixtures.collector(client,at=NOW+60))
        self.assertEqual(result['prospective_journal']['registered'],1)
        self.assertEqual(result['prospective_journal']['waiting'],0)
        self.assertEqual(result['prospective_journal']['unknown'],1)
        cases=app.journal.list_cases();self.assertEqual(cases[0]['state'],'UNKNOWN_AT_HORIZON')
        self.assertIn('DEPTH_UNVERIFIED',cases[0]['reasons'])
        self.assertIsNone(cases[0]['relative_eth'])
        self.assertEqual(result['orders_submitted'],0)

    def test_startup_restores_journal_summary_to_ui_export_and_monitor_before_scanning(self):
        import tkinter as tk
        from coincat_app import CoinCatApp
        app=self.app;journal=app.journal;journal.clock=lambda:NOW
        funds=ResearchFunds(D(1));assume(funds,'seed',ETH_BTC)
        journal.register('saved',funds=funds,leg=BTC_SOL,quantity=D(1),frame=frame(),
            horizon_s=60,signal_id='PRIVATE_STARTUP_SIGNAL',fill_state='SIMULATED_ASSUMPTION',slippage_bps=D(0))
        journal.observe(frame(at=NOW+60,evidence=False));before=journal.case('saved')
        app._close();self.root.tk.call('update','idletasks')
        root=tk.Tk();restarted=CoinCatApp(root)
        try:
            self.assertIsNone(restarted.last_result);self.assertFalse(restarted.running)
            self.assertIn('Registered 1',restarted.journal_text.get())
            self.assertNotIn('Journal empty',restarted.journal_text.get())
            self.assertEqual(restarted.journal.case('saved'),before)
            with patch.object(restarted.journal,'summary',side_effect=AssertionError('NO_PERIODIC_JOURNAL_READ')):
                restarted._update_freshness()
                snap=capture(restarted,session='a'*32,sequence=1,now=NOW+61)
                report=make_report(restarted,now=NOW+61)
            self.assertEqual(snap['prospective_journal']['registered'],1)
            self.assertEqual(snap['prospective_journal']['unknown'],1)
            self.assertFalse(snap['health']['running'])
            self.assertIn("'registered': 1",report)
            self.assertNotIn('PRIVATE_STARTUP_SIGNAL',report)
            self.assertNotIn('PRIVATE_STARTUP_SIGNAL',encode(snap).decode())
        finally:
            restarted._close();root.tk.call('update','idletasks')

    def test_manual_local_view_refreshes_main_summary_without_a_scan(self):
        app=self.app;app.journal.clock=lambda:NOW
        funds=ResearchFunds(D(1));assume(funds,'seed',ETH_BTC)
        app.journal.register('saved',funds=funds,leg=BTC_SOL,quantity=D(1),frame=frame(),
            horizon_s=60,signal_id='PRIVATE_VIEW_SIGNAL',fill_state='UNVERIFIED',slippage_bps=D(0))
        window=app._view_experiments()
        try:
            self.root.update()
            self.assertIn('Registered 1',app.journal_text.get())
            self.assertIsNone(app.last_result);self.assertFalse(app.running)
            self.assertEqual(capture(app,session='a'*32,sequence=1,now=NOW)['prospective_journal']['registered'],1)
        finally:window.destroy()

    def test_summary_read_failure_is_unavailable_and_does_not_report_an_empty_journal(self):
        app=self.app
        with patch.object(app.journal,'summary',side_effect=sqlite3.OperationalError('PRIVATE_DATABASE_PATH')):
            app._refresh_journal_status();app._update_freshness()
        self.assertIn('Journal unavailable',app.journal_text.get())
        self.assertNotIn('Journal empty',app.journal_text.get())
        snap=capture(app,session='a'*32,sequence=1,now=NOW)
        self.assertEqual(snap['prospective_journal']['state'],'UNAVAILABLE')
        self.assertNotIn('PRIVATE_DATABASE_PATH',make_report(app,now=NOW))
        self.assertNotIn('PRIVATE_DATABASE_PATH',encode(snap).decode())

    def test_committed_registration_is_not_reported_as_failed_when_summary_read_fails(self):
        app,_,_=self.ready()
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app.journal,'summary',
                side_effect=sqlite3.OperationalError('PRIVATE_DATABASE_PATH')):
            result=app._register_experiment(source='ETH',target='ADA',initial_eth=D('.1'),horizon_s=60,
                signal_id='COMMITTED_CASE',fill_state='UNVERIFIED',explicit_assumption=True)
        self.assertEqual(result['latest']['signal']['id'],'COMMITTED_CASE')
        self.assertEqual(app.journal.summary()['registered'],1)
        self.assertIn('Journal unavailable',app.journal_text.get())
        app._refresh_journal_status()
        self.assertIn('Registered 1',app.journal_text.get())
