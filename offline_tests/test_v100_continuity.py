"""Stable ETH hypotheses, bounded read recovery and honest last-good freshness."""
from copy import deepcopy
from contextlib import closing
from decimal import Decimal as D
from tempfile import TemporaryDirectory
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

import requests
from coincat_continuity import eth_funding,freshness,quote_reason
from coincat_eth_maker import MakerConfig,MakerStudy
from coincat_recovery import Recovery,ReadFailure,failure,retry_after,BACKOFF
from coincat_scanner import Scanner
from coincat_simple_diagnostics import make_report
from coincat_v701_transport import QuoteErrors
from coincat_working_allocation import AllocationRow
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_v100_eth_growth import prepare,run_growth,modeled,GrowthClient
from offline_tests.test_native_receipts import NOW


def http_error(status,after=None):
    response=requests.Response();response.status_code=status
    if after is not None:response.headers['Retry-After']=str(after)
    return requests.HTTPError('SECRET_TOKEN PRIVATE_ACCOUNT_ID /private/key.json',response=response)


class ResearchKeys(unittest.TestCase):
    def test_hundreds_of_unrelated_balances_drafts_exclusions_preserve_frozen_setup(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);first=run_growth(s,c);initial=first['rows'][0]['hypothesis']
            for step in range(1,21):
                s.balances.update({f'X{i}':D(i+step) for i in range(200)})
                draft=[AllocationRow('ETH',D(2))]+[AllocationRow(f'X{i}',D(i+step)) for i in range(200)]
                # Change unrelated exclusions as well as exact native quantities.
                with patch.object(s.ledger,'assets',return_value=[dict(asset=f'X{i}',enabled=0) for i in range(step)]):
                    r=s.scan_growth(MakerConfig(('ADA',),D('.1')),now=NOW+step,
                        collect=fixtures.collector(c,at=NOW+step),allocation_draft=tuple(draft))
                self.assertEqual(r['study_counts']['setups'],1)
                self.assertEqual(r['study_counts']['invalidated'],0)
                self.assertEqual(r['rows'][0]['hypothesis']['entry_at'],initial['entry_at'])
                self.assertEqual(r['rows'][0]['hypothesis']['expiry_at'],initial['expiry_at'])
                self.assertFalse(r['live_order_permission'])

    def test_rule_statistics_order_and_numeric_spelling_do_not_change_identity(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);run_growth(s,c)
            s.rules['ADA-ETH']=dict(reversed(list(s.rules['ADA-ETH'].items())))
            s.rules['ADA-ETH'].update(price='999',volume_24h='987654321',price_percentage_change_24h='7',base_increment='.0100')
            result=run_growth(s,c)
            self.assertEqual(result['study_counts']['setups'],1)
            self.assertEqual(result['study_counts']['invalidated'],0)

    def test_critical_rule_and_control_changes_have_explicit_invalidation_reasons(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);run_growth(s,c)
            s.rules['ADA-ETH']['base_increment']='.02'
            result=run_growth(s,c)
            self.assertEqual(result['study_continuity']['reset_reasons'],{'SELECTED_PRODUCT_RULES_CHANGED':1})
            changed=MakerConfig(('ADA',),D('.1'),target_pct=D('.5'))
            result=s.scan_growth(changed,now=NOW,collect=fixtures.collector(c),allocation_draft=(AllocationRow('ETH',D(2)),))
            self.assertEqual(result['study_continuity']['reset_reasons']['RESEARCH_CONFIGURATION_CHANGED'],1)

    def test_eth_funding_change_rejects_applied_plan_before_new_quote_requests(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);run_growth(s,c)
            key=eth_funding(balances=s.balances,balances_at=NOW,now=NOW,draft=(AllocationRow('ETH',D(2)),))['key']
            s.balances['ETH']=D('1.9');collect=Mock()
            result=s.scan_growth(MakerConfig(('ADA',),D('.1')),now=NOW,collect=collect,
                allocation_draft=(AllocationRow('ETH',D(2)),),applied_eth_key=key)
            collect.assert_not_called();self.assertEqual(result['state'],'PAUSED_NEEDS_ATTENTION')
            self.assertEqual(result['study_continuity']['reset_reasons'],{'ETH_FUNDING_CHANGED_REAPPLY_REQUIRED':1})
            self.assertEqual(s.sequence,1);self.assertEqual(s.maker_study.active,{})

    def test_selected_exclusion_or_permission_loss_closes_only_relevant_hypothesis(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);run_growth(s,c)
            with patch.object(s.ledger,'assets',return_value=[dict(asset='ADA',enabled=0)]):result=run_growth(s,c)
            self.assertEqual(result['rows'],[])
            self.assertEqual(result['study_continuity']['reset_reasons'],{'SELECTED_MARKET_EXCLUDED':1})
            run_growth(s,c);s.rules['ADA-ETH']['view_only']=True;result=run_growth(s,c)
            self.assertEqual(result['rows'],[])
            self.assertEqual(result['study_continuity']['reset_reasons']['SELECTED_MARKET_REMOVED_OR_INELIGIBLE'],1)

    def test_two_markets_invalidate_individually_on_selected_rule_change(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder)
            s.rules['SOL-ETH']=dict(s.rules['ADA-ETH'],product_id='SOL-ETH');s.catalog.append('SOL-ETH');c.q['SOL-ETH']=c.q['ADA-ETH']
            config=MakerConfig(('ADA','SOL'),D('.1'));draft=(AllocationRow('ETH',D(2)),)
            s.scan_growth(config,now=NOW,collect=fixtures.collector(c),allocation_draft=draft)
            s.rules['SOL-ETH']['base_increment']='.02'
            result=s.scan_growth(config,now=NOW+1,collect=fixtures.collector(c,at=NOW+1),allocation_draft=draft)
            self.assertEqual(result['study_counts']['setups'],3)
            self.assertEqual(s.maker_study.active['ADA-ETH']['entry_at'],NOW)
            self.assertEqual(s.maker_study.active['SOL-ETH']['entry_at'],NOW+1)

    def test_whole_account_reconciliation_contract_remains_separate(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);s.balances['OTHER']=D(1)
            result=run_growth(s,c,allocation_draft=(AllocationRow('ETH',D(2)),AllocationRow('OTHER',D(3))))
            self.assertEqual(result['working_allocation']['state'],'INVALID_DRAFT')
            self.assertFalse(result['working_allocation']['reconciled'])
            self.assertEqual(result['rows'][0]['observation_state'],'SETUP_ACTIVE_OBSERVABLE')
            self.assertFalse(result['live_order_permission'])


class QuoteGaps(unittest.TestCase):
    def test_specific_quote_and_transport_reasons_do_not_guess_missing_causes(self):
        cases=[(None,None,'QUOTE_NOT_RETURNED'),(None,'ConnectionError','CONNECTION_ERROR'),
            (None,'ReadTimeout','READ_TIMEOUT'),(None,'HTTP_429_RETRY_AFTER','GET_DEFERRED'),
            (None,'HTTP_503','HTTP_503'),(None,'UNRECOGNIZED','QUOTE_NOT_RETURNED'),
            ((D(1),D('1.01'),NOW),None,'QUOTE_WIDE'),((D(1),D(1),NOW-31),None,'QUOTE_STALE'),
            ((D(1),D(1),NOW+1),None,'QUOTE_FUTURE'),((D('NaN'),D(1),NOW),None,'QUOTE_INVALID')]
        for raw,code,reason in cases:self.assertEqual(quote_reason(raw,NOW,code),reason)

    def test_multiple_gap_readings_keep_original_setup_and_skip_first_recovery_touch(self):
        study=MakerStudy();first=modeled();study.observe([first],key='same',now=NOW)
        original=deepcopy(study.active['ADA-ETH']);entry=original['entry_price']
        for offset,raw in ((5,None),(10,(D('.0002'),D('.0003'),NOW+10)),(15,(D('.0002'),D('.0002001'),NOW-31))):
            row=modeled(raw_quote=raw,now=NOW+offset);study.observe([row],key='same',now=NOW+offset)
            self.assertEqual(row['observation_state'],'SETUP_ACTIVE_UNPRICED')
            self.assertFalse(row['current_estimate_available']);self.assertIsNone(row['benchmark'])
            self.assertEqual(row['hypothesis']['entry_at'],original['entry_at'])
            self.assertEqual(row['hypothesis']['expiry_at'],original['expiry_at'])
        self.assertEqual(study.counts['setups'],1);self.assertEqual(study.counts['unpriced_episodes'],1)
        recovered=modeled(raw_quote=(entry-D('.00000001'),entry,NOW+20),now=NOW+20)
        study.observe([recovered],key='same',now=NOW+20)
        self.assertIsNone(recovered['hypothesis']['entry_touched_at'])
        self.assertEqual(study.counts['resumed_episodes'],1)
        continuous=modeled(raw_quote=(entry-D('.00000001'),entry,NOW+25),now=NOW+25)
        study.observe([continuous],key='same',now=NOW+25)
        self.assertEqual(continuous['hypothesis']['entry_touched_at'],NOW+25)
        self.assertEqual(continuous['fill_state'],'PARTIAL_OR_UNCERTAIN_FILL')

    def test_expiry_during_gap_is_not_extended_and_does_not_claim_a_fill(self):
        study=MakerStudy();row=modeled(config=MakerConfig(('ADA',),D('.1'),expiry_hours=D(1)))
        study.observe([row],key='a',now=NOW)
        missing=modeled(raw_quote=None,now=NOW+100);study.observe([missing],key='a',now=NOW+100)
        expired=modeled(raw_quote=None,now=NOW+3600);study.observe([expired],key='a',now=NOW+3600)
        self.assertEqual(expired['observation_state'],'SETUP_EXPIRED');self.assertEqual(study.active,{})
        self.assertEqual(study.counts['expired'],1);self.assertEqual(study.counts['setups'],1)
        self.assertIsNone(expired['actual_profit_eth']);self.assertIsNone(expired['hypothesis']['entry_touched_at'])

    def test_fee_gap_pauses_and_verified_fee_change_is_reason_coded(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);first=run_growth(s,c)
            with patch.object(s.fees,'latest_tier',return_value={'fresh':False,'maker':None,'taker':None}):
                missing=run_growth(s,c)
            self.assertEqual(missing['rows'][0]['observation_state'],'SETUP_ACTIVE_UNPRICED')
            self.assertFalse(missing['rows'][0]['current_estimate_available'])
            self.assertEqual(missing['rows'][0]['hypothesis']['entry_at'],first['rows'][0]['hypothesis']['entry_at'])
            s.fees.capture_tier({'fee_tier':{'maker_fee_rate':'.006','taker_fee_rate':'.009'}},now=NOW)
            changed=run_growth(s,c)
            self.assertEqual(changed['study_continuity']['reset_reasons'],{'ACCOUNT_FEE_RATE_CHANGED':1})
            self.assertEqual(changed['study_counts']['fee_changes'],1)

    def test_bounded_histories_count_dropped_events_and_not_repeated_polls(self):
        study=MakerStudy();study.observe([modeled()],key='a',now=NOW)
        for i in range(1,151):
            bad=modeled(raw_quote=None,now=NOW+i*2);study.observe([bad],key='a',now=NOW+i*2)
            study.observe([modeled(raw_quote=None,now=NOW+i*2)],key='a',now=NOW+i*2)
            good=modeled(raw_quote=(D('.0002'),D('.0002001'),NOW+i*2+1),now=NOW+i*2+1)
            study.observe([good],key='a',now=NOW+i*2+1)
        self.assertEqual(study.counts['unpriced_episodes'],150)
        self.assertEqual(study.counts['setups'],1);self.assertEqual(len(study.history),128)
        self.assertGreater(study.history_dropped,0)
        self.assertNotIn('scenario',str(study.diagnostics()))


class RecoveryPolicy(unittest.TestCase):
    def test_five_retries_monotonic_backoff_no_early_attempt_and_then_attention(self):
        clock=[0.0];r=Recovery(lambda:clock[0]);r.start();detail=failure(requests.ConnectionError(),'BALANCES')
        for i,delay in enumerate(BACKOFF):
            r.failed(detail,now=NOW);self.assertEqual(r.state,'RETRYING')
            self.assertEqual(r.due_at-clock[0],delay);self.assertFalse(r.begin_retry())
            clock[0]+=delay;self.assertTrue(r.begin_retry());self.assertFalse(r.begin_retry())
            self.assertEqual(r.attempt,i+1)
        r.failed(detail,now=NOW);self.assertEqual(r.state,'PAUSED_NEEDS_ATTENTION')
        self.assertIsNone(r.due_at);self.assertEqual(r.retry_attempts,5);self.assertEqual(r.interruptions,1)

    def test_retry_after_and_authentication_fatal_classification_are_sanitized(self):
        detail=failure(http_error(429,120),'CATALOG');r=Recovery(lambda:0);r.start();r.failed(detail,now=NOW)
        self.assertEqual(r.due_at,120)
        self.assertNotIn('SECRET',str(r.diagnostics()));self.assertNotIn('/private',str(r.diagnostics()))
        for error in (http_error(401),http_error(403),requests.exceptions.SSLError('SECRET'),
                      ValueError('SECRET'),sqlite3.DatabaseError('SECRET')):
            r=Recovery();r.start();r.failed(failure(error,'PERMISSIONS'),now=NOW)
            self.assertEqual(r.state,'PAUSED_NEEDS_ATTENTION');self.assertIsNone(r.due_at)
        self.assertEqual(retry_after('Mon, 02 Nov 2026 15:03:38 GMT',wall=1793631818),0)
        self.assertEqual(retry_after('not-a-date'),0)

    def test_stop_and_success_close_outage_without_automatic_restart(self):
        r=Recovery(lambda:0);r.start();r.failed(failure(requests.Timeout(),'PUBLIC_QUOTE'),now=NOW)
        r.stop();self.assertEqual(r.state,'STOPPED');self.assertFalse(r.begin_retry())
        r.start();r.successful(NOW+1)
        self.assertEqual(r.recovered_periods,1);self.assertEqual(r.last_successful_scan_at,NOW+1)
        self.assertEqual(r.attempt,0)


class StagedReads(unittest.TestCase):
    def scanner(self,folder):
        ledger,_,old=fixtures.setup(folder);client=GrowthClient()
        return ledger,client,Scanner(ledger,client,old.fees,old.market_store)

    def test_permissions_balances_catalog_and_fee_failures_are_attributed_and_staged(self):
        for method,stage in (('get_api_key_permissions','PERMISSIONS'),('get_accounts','BALANCES'),
                             ('get_products','CATALOG'),('get_transaction_summary','FEE_TIER')):
            with self.subTest(stage=stage),TemporaryDirectory() as folder:
                ledger,c,s=self.scanner(folder);before=fixtures.ledger_dump(ledger)
                with patch.object(c,method,side_effect=requests.ConnectionError('SECRET_ACCOUNT_KEY')):
                    with self.assertRaises(ReadFailure) as error:s.refresh(now=NOW)
                self.assertEqual(error.exception.detail['stage'],stage);self.assertTrue(error.exception.detail['transient'])
                self.assertIsNone(s.account_at);self.assertIsNone(s.last_successful_account_refresh_at)
                self.assertEqual(s.balances,{})
                self.assertEqual(before,fixtures.ledger_dump(ledger));self.assertNotIn('SECRET',str(error.exception))
                if stage=='FEE_TIER':self.assertGreaterEqual(error.exception.detail['retry_after_s'],600)

    def test_fee_failure_preserves_existing_provider_retry_interval(self):
        with TemporaryDirectory() as folder:
            _,c,s=self.scanner(folder)
            with patch.object(c,'get_transaction_summary',side_effect=requests.Timeout()) as method:
                with self.assertRaises(ReadFailure):s.refresh(now=NOW)
                self.assertEqual(method.call_count,1)
                self.assertFalse(s.fees.due(now=NOW+599));self.assertTrue(s.fees.due(now=NOW+600))

    def test_fee_retry_cannot_masquerade_as_success_while_provider_backoff_is_pending(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder)
            with patch.object(c,'get_transaction_summary',side_effect=requests.Timeout()) as method:
                with self.assertRaises(ReadFailure):s.refresh(now=NOW+3601)
                with self.assertRaises(ReadFailure) as deferred:s.refresh(now=NOW+3602)
                self.assertEqual(deferred.exception.detail['category'],'FEE_REFRESH_DEFERRED')
                self.assertEqual(method.call_count,1)

    def test_public_timeout_and_connection_failure_do_not_publish_successful_scan(self):
        for code in ('ConnectionError','ReadTimeout','HTTP_503','HTTP_429_RETRY_AFTER','PREVIOUS_GETS_IN_FLIGHT'):
            with self.subTest(code=code),TemporaryDirectory() as folder:
                _,c,s=prepare(folder);previous=run_growth(s,c)
                errors=QuoteErrors({code:1});errors.by_product={'ADA-ETH':code}
                with self.assertRaises(ReadFailure) as error:
                    run_growth(s,c,collect=lambda *a,**k:({},errors,1))
                self.assertEqual(error.exception.detail['stage'],'PUBLIC_QUOTE');self.assertTrue(error.exception.detail['transient'])
                self.assertIs(s.last_result,previous);self.assertEqual(s.sequence,1)

    def test_partial_quote_denial_pauses_instead_of_hiding_authentication_error(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);errors=QuoteErrors({'HTTP_403':1});errors.by_product={'ADA-ETH':'HTTP_403'}
            with self.assertRaises(ReadFailure) as error:
                run_growth(s,c,collect=lambda *a,**k:fixtures.collector(c)(*a,**k)[:1]+(errors,1))
            self.assertEqual(error.exception.detail['status'],403);self.assertFalse(error.exception.detail['transient'])

    def test_local_quote_store_failure_has_stage_and_keeps_observer_uncommitted(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder)
            with patch.object(s.market_store,'record_quotes',side_effect=sqlite3.DatabaseError('PRIVATE_PATH')):
                with self.assertRaises(ReadFailure) as error:run_growth(s,c)
            self.assertEqual(error.exception.detail['stage'],'LOCAL_PUBLIC_QUOTE_STORE')
            self.assertFalse(error.exception.detail['transient']);self.assertEqual(s.sequence,0)
            self.assertEqual(s.maker_study.active,{})

    def test_cancelled_auth_read_does_not_commit_account_or_later_requests(self):
        with TemporaryDirectory() as folder:
            _,c,s=self.scanner(folder);cancel=threading.Event()
            def permissions():cancel.set();return {'can_view':True,'can_trade':True,'can_transfer':False}
            with patch.object(c,'get_api_key_permissions',side_effect=permissions),patch.object(c,'get_accounts') as accounts:
                self.assertEqual(s.refresh(now=NOW,cancel=cancel)['state'],'CANCELLED')
            accounts.assert_not_called();self.assertIsNone(s.account_at);self.assertEqual(s.balances,{})

    def test_cancel_during_quote_store_rolls_back_and_commits_no_hypothesis(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);cancel=threading.Event();original=s.market_store.record_quotes
            def cancel_before(rows,**kw):cancel.set();return original(rows,**kw)
            with patch.object(s.market_store,'record_quotes',side_effect=cancel_before):
                result=run_growth(s,c,cancel=cancel)
            self.assertEqual(result['state'],'CANCELLED');self.assertEqual(s.sequence,0)
            with closing(sqlite3.connect(s.market_store.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM market_quotes').fetchone()[0],0)

    def test_cancellation_after_sql_insert_rolls_back_the_public_transaction(self):
        from contextlib import contextmanager
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);cancel=threading.Event();original=s.market_store._db
            class Wrapped:
                def __init__(self,db):self.db=db
                @property
                def total_changes(self):return self.db.total_changes
                def executemany(self,*args):self.db.executemany(*args);cancel.set()
                def rollback(self):self.db.rollback()
            @contextmanager
            def stop_in_transaction():
                with original() as db:yield Wrapped(db)
            with patch.object(s.market_store,'_db',side_effect=stop_in_transaction):
                result=run_growth(s,c,cancel=cancel)
            self.assertEqual(result['state'],'CANCELLED');self.assertEqual(s.maker_study.active,{})
            with closing(sqlite3.connect(s.market_store.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM market_quotes').fetchone()[0],0)


class FreshExport(unittest.TestCase):
    def test_six_hour_old_export_cannot_claim_current_fee_quote_or_connection_freshness(self):
        with TemporaryDirectory() as folder:
            ledger,c,s=prepare(folder);result=run_growth(s,c);original=deepcopy(result)
            app=SimpleNamespace(scanner=s,last_result=result,ledger=ledger,connected=True,running=False,
                                busy=False,last_error='ConnectionError',fees=s.fees)
            view=freshness(result,NOW+21600)
            self.assertEqual(view['display_state'],'STALE_LAST_OBSERVATION')
            self.assertTrue(view['fee_fresh_at_last_good_scan']);self.assertFalse(view['fee_valid_at_export'])
            self.assertEqual(view['products'][0]['quote_age_s_at_export'],21600)
            self.assertEqual(view['products'][0]['waiting_s_at_export'],21600)
            self.assertEqual(view['products'][0]['original_expiry_at'],result['rows'][0]['hypothesis']['expiry_at'])
            report=make_report(app,now=NOW+21600)
            for text in ("'connected': False","'fee_valid_at_export': False",'STALE_LAST_OBSERVATION',
                         'account_tier_at_last_good_scan','last_good_scan_age_s','COMPLETE (8/8)'):
                self.assertIn(text,report)
            self.assertEqual(result,original)

    def test_gap_histories_and_funding_identities_are_redacted(self):
        with TemporaryDirectory() as folder:
            ledger,c,s=prepare(folder);result=run_growth(s,c)
            sentinel='9876543.210987654321'
            s.maker_study.identities['ADA-ETH']['funding']=sentinel
            s.pause_observation('CONNECTION_ERROR',now=NOW)
            app=SimpleNamespace(scanner=s,last_result=result,ledger=ledger,connected=False,running=True,
                busy=False,last_error='ConnectionError',fees=s.fees,recovery=Recovery())
            report=make_report(app,now=NOW+1)
            self.assertNotIn(sentinel,report);self.assertNotIn(str(ledger.path),report)
            self.assertNotIn('input_quantity',report);self.assertIn('CONNECTION_ERROR',report)


class ContinuityGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def prepare(self):
        self.timer=[0.0];self.app.recovery.clock=lambda:self.timer[0]
        clock=patch('coincat_app.time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        _,c,s=prepare(self.temp.name);self.app.scanner=s;self.app.connected=True
        self.app.allocation_editor.clock=lambda:NOW;self.app._render_wallet()
        self.app.companions[0].set('ADA');self.app.mixer.controls['amount_eth'].set(D('.1'))
        self.app._apply_plan();result=run_growth(s,c);self.app.last_result=result;self.app._render(result)
        self.app.running=True;self.app.cancel=threading.Event();self.app.recovery.start()
        return c,s

    def settle(self):
        deadline=time.monotonic()+3
        while self.app.busy and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertFalse(self.app.busy)

    def test_transient_retries_one_job_then_recovers_same_setup_without_gap_touch(self):
        c,s=self.prepare();entry=s.maker_study.active['ADA-ETH']['entry_at']
        self.app._handle_failure('scan',failure(requests.ConnectionError(),'BALANCES'))
        self.assertEqual(self.app.recovery.state,'RETRYING');self.assertFalse(self.app.connected)
        with patch('coincat_scanner.SCOUT.collect',side_effect=fixtures.collector(c)):
            self.app._retry();self.assertFalse(self.app.busy)  # Monotonic delay not elapsed.
            self.timer[0]=10;self.app._retry();self.settle()
        self.assertEqual(self.app.recovery.state,'RUNNING');self.assertEqual(self.app.recovery.recovered_periods,1)
        self.assertEqual(s.maker_study.active['ADA-ETH']['entry_at'],entry)
        self.assertEqual(s.sequence,2);self.assertTrue(self.app.connected)

    def test_five_failed_retries_pause_and_stop_cancels_future_requests(self):
        c,s=self.prepare();self.app._handle_failure('scan',failure(requests.ConnectionError(),'PERMISSIONS'))
        with patch.object(c,'get_api_key_permissions',side_effect=requests.ConnectionError()) as reads:
            for attempt in range(5):
                self.timer[0]=self.app.recovery.due_at;self.app._retry();self.settle()
            self.assertEqual(reads.call_count,5)
        self.assertEqual(self.app.recovery.state,'PAUSED_NEEDS_ATTENTION');self.assertFalse(self.app.running)
        self.assertNotIn('retry',self.app._after);self.assertEqual(s.sequence,1)
        self.app._stop();self.app._retry();self.assertEqual(self.app.recovery.state,'STOPPED')

    def test_authentication_failure_requires_manual_attention_without_retry_timer(self):
        self.prepare();self.app._handle_failure('scan',failure(http_error(401),'PERMISSIONS'))
        self.assertEqual(self.app.recovery.state,'PAUSED_NEEDS_ATTENTION')
        self.assertNotIn('retry',self.app._after);self.assertFalse(self.app.running);self.assertFalse(self.app.connected)

    def test_initial_connection_retry_does_not_start_research_automatically(self):
        self.prepare();self.app.running=False
        self.app._handle_failure('connect',failure(requests.ConnectionError(),'CATALOG'))
        self.timer[0]=10;self.app._retry();self.settle()
        self.assertEqual(self.app.recovery.state,'STOPPED');self.assertFalse(self.app.running)
        self.assertEqual(self.app.recovery.connection_recoveries,1)
        self.assertEqual(self.app.recovery.interruptions,0)

    def test_close_during_account_read_rejects_late_result_and_later_requests(self):
        c,s=self.prepare();started=threading.Event();release=threading.Event();before=s.account_at
        original=c.get_accounts
        def delayed(**kwargs):
            started.set()
            if not release.wait(2):raise AssertionError('Test did not release delayed read')
            return original(**kwargs)
        with patch.object(c,'get_accounts',side_effect=delayed),patch.object(c,'get_products') as catalog:
            self.app._scan(force_refresh=True);self.assertTrue(started.wait(1))
            self.app._close();release.set()
            kind,generation,result,error=self.app.jobs.get(timeout=2)
        self.assertIsNone(error);self.assertEqual(result['state'],'CANCELLED')
        catalog.assert_not_called();self.assertEqual(s.account_at,before);self.assertEqual(s.sequence,1)

    def test_stop_reapply_and_stale_queued_errors_cannot_restart_or_publish(self):
        _,s=self.prepare();self.app._handle_failure('scan',failure(requests.Timeout(),'PUBLIC_QUOTE'))
        previous=self.app.last_result;generation=self.app.generation
        self.app._stop();self.assertNotIn('retry',self.app._after)
        self.app.jobs.put(('scan',generation,{},failure(requests.ConnectionError(),'BALANCES')))
        self.app._poll();self.app._retry()
        self.assertIs(self.app.last_result,previous);self.assertFalse(self.app.busy)
        self.assertEqual(self.app.recovery.state,'STOPPED');self.assertEqual(s.sequence,1)

    def test_unrelated_allocation_edit_keeps_applied_eth_plan_and_relevant_edit_revokes(self):
        _,s=self.prepare();s.balances['OTHER']=D(2);self.app._render_wallet()
        previous=self.app.last_result;generation=self.app.generation;config=self.app.applied_config
        editor=self.app.allocation_editor;editor.show_all.set(True)
        editor.tree.selection_set('OTHER');editor._select()
        editor.fields['working'].set('1');editor.apply_selected()
        self.assertEqual(self.app.generation,generation);self.assertIs(self.app.last_result,previous)
        self.assertEqual(self.app.applied_config,config)
        editor.tree.selection_set('ETH');editor._select();editor.fields['protected'].set('.1')
        self.assertIsNone(self.app.applied_config);self.assertGreater(self.app.generation,generation)
        self.assertFalse(self.app.running)

    def test_balance_visibility_toggle_preserves_running_plan_funding_and_setup(self):
        client,s=self.prepare();s.balances['OTHER']=D('0.0000000097614163');self.app._render_wallet()
        editor=self.app.allocation_editor;self.root.update()
        self.assertFalse(editor.tree.exists('OTHER'))
        config=self.app.applied_config;funding=self.app.applied_eth_key;generation=self.app.generation
        result=self.app.last_result;setup=deepcopy(s.maker_study.active);reads=list(client.calls)
        before=fixtures.ledger_dump(self.app.ledger)
        for expected in (True,False):
            editor.show_all_button.invoke();self.root.update()
            self.assertEqual(editor.tree.exists('OTHER'),expected)
            self.assertIs(self.app.applied_config,config);self.assertEqual(self.app.applied_eth_key,funding)
            self.assertEqual(self.app.generation,generation);self.assertIs(self.app.last_result,result)
            self.assertTrue(self.app.running);self.assertEqual(self.app.recovery.state,'RUNNING')
            self.assertEqual(s.maker_study.active,setup);self.assertEqual(client.calls,reads)
        self.assertEqual(before,fixtures.ledger_dump(self.app.ledger))

    def test_stale_badge_fee_overlay_and_rows_do_not_mutate_last_good(self):
        self.prepare();original=deepcopy(self.app.last_result)
        with patch('coincat_app.time.time',return_value=NOW+21600):self.app._update_freshness()
        self.assertIn('STALE_LAST_OBSERVATION',self.app.observation_text.get())
        self.assertIn('STALE / UNVERIFIED NOW',self.app.evidence_text.get());self.assertFalse(self.app.connected)
        row=self.app.growth_tree.item('ADA-ETH')['values']
        self.assertIn('STALE_LAST_OBSERVATION',row)
        self.assertEqual(self.app.last_result,original)
