"""Adverse evidence, exact settlement and retained-handle recovery regressions."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from coincat_beta_store import BetaBlocked
from coincat_opportunity_policy import OpportunityConfig
from coincat_opportunity_trader import OpportunityTrader,active
from coincat_trial_clock import TARGET_NS,NS
from offline_tests import test_opportunity_trader as lifecycle_tests
from offline_tests.test_opportunity_policy import market
from offline_tests.test_resumable_trial import Clock
from offline_tests.trial_sqlite_resources import trial_sqlite_probe

class AdverseRecovery(unittest.TestCase):
    setUp=lifecycle_tests.Lifecycle.setUp
    f=lifecycle_tests.Lifecycle.f
    warm=lifecycle_tests.Lifecycle.warm
    acknowledge=lifecycle_tests.Lifecycle.acknowledge
    fill=lifecycle_tests.Lifecycle.fill
    def configured_size(self):return replace(OpportunityConfig(),size_percent={p:D(5) if p=='ETH-BTC' else D(0) for p in OpportunityConfig().size_percent})
    def test_partial_racing_cancel_settles_once_then_releases_only_remaining_hold(self):
        self.warm(self.configured_size());o=self.acknowledge();q=o['size']//D('.000004')*D('.000001')
        self.e.pause();self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING')
        self.fill(o,q);s=self.e.state();self.assertEqual(active(s)['filled'],q)
        self.assertEqual(active(s)['reserved'],o['size']-q)
        self.c.tick(3);self.e.heartbeat(persist=True);s=self.e.state()
        self.assertIsNone(active(s));self.assertEqual(s['orders'][o['reference']]['state'],'CANCELED')
        self.assertEqual(s['metrics']['fill_events'],1);self.assertEqual(s['metrics']['nonfills'],0)
        self.assertEqual(s['fees_native']['BTC'],q*o['price']*D('.005'))
        with self.assertRaises(BetaBlocked):self.fill(o,q,trade='late-after-terminal')
        self.assertEqual(self.e.state(),s)
    def test_unknown_commission_and_restart_preserve_wallet_until_bound_fee_evidence(self):
        self.warm(self.configured_size());o=self.acknowledge();q=o['size']//D('.000002')*D('.000001')
        raw=dict(trade_id='uncertain-fee',product_id=o['pair'],side=o['side'],size=q,price=o['price'],commission=None,size_in_quote=False)
        event=dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='FILL',at=self.c.wall(),receipt=raw)
        before=self.e.state();self.e.replay(event,'fee-unknown');self.e.shutdown();self.c.tick(3600)
        self.e=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(self.e.load_error);self.assertFalse(self.e.running);self.assertEqual(active(self.e.state())['unknown_kind'],'UNSETTLED_FEE')
        self.assertEqual(self.e.state()['wallet'],before['wallet']);self.assertEqual(self.e.state()['fees_native'],before['fees_native'])
        fixed=dict(raw,size=str(q),price=str(o['price']),commission=str(q*o['price']*D('.005')),fee_currency='BTC')
        resolved=dict(event,kind='FEE_EVIDENCE',at=self.c.wall(),receipt=fixed)
        wrong=dict(resolved,receipt=dict(fixed,trade_id='other'))
        with self.assertRaises(BetaBlocked):self.e.replay(wrong,'wrong-fee')
        self.e.replay(resolved,'resolved-fee');s=self.e.state();self.assertEqual(s['wallet']['ETH'],before['wallet']['ETH']-q)
        self.assertEqual(s['metrics']['fill_events'],1);self.assertEqual(s['metrics']['unknown_fill_marks'],1)
        self.e.replay(resolved,'resolved-fee');self.assertEqual(self.e.state(),s)
    def test_explicit_unknown_is_not_downgraded_to_restart_gap_or_auto_canceled(self):
        self.warm();o=self.acknowledge()
        self.e.replay(dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='UNKNOWN',at=self.c.wall()),'ambiguous')
        self.e.shutdown();self.c.tick(4000);self.e=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.e.heartbeat(persist=True);self.assertEqual(active(self.e.state())['state'],'UNKNOWN')
        self.assertEqual(active(self.e.state())['unknown_kind'],'EXPLICIT_REPLAY');self.assertFalse(self.e.running)
    def test_trade_window_gap_cannot_backfill_and_duplicate_ids_cannot_change(self):
        self.warm();o=self.acknowledge();wallet=deepcopy(self.e.state()['wallet'])
        self.c.tick(40);self.prints=[dict(id='new-'+str(i),price=o['price']+D('.00000001'),size=D(100),at=self.c.wall()-20+i*10) for i in range(3)]
        self.e.review(self.f());self.assertEqual(self.e.state()['metrics']['fill_events'],0)
        self.assertEqual(self.e.state()['metrics']['gaps'],1)
        self.prints[0]['size']=D(200);self.c.tick(1);self.e.review(self.f())
        self.assertEqual(self.e.state()['wallet'],wallet);self.assertEqual(self.e.state()['metrics']['fill_events'],0)
    def test_no_fill_provider_retains_zero_fills_despite_strict_prints_and_zero_native_fees(self):
        self.warm(replace(OpportunityConfig(),provider='NO_FILL_OBSERVATION_V1'));o=self.acknowledge()
        for i in range(5):
            self.c.tick(10);self.prints.append(dict(id='through-'+str(i),price=o['price']+D('.00000001'),size=D(100),at=self.c.wall()));self.e.review(self.f())
        self.assertEqual(self.e.state()['metrics']['fill_events'],0);self.assertEqual(self.e.state()['wallet'],self.e.state()['original'])
    def test_adverse_reversal_reports_loss_vs_same_hold_and_never_forces_liquidation(self):
        self.warm(self.configured_size());o=self.acknowledge();self.fill(o)
        after=deepcopy(self.e.state()['wallet']);self.c.tick(10);self.step=-150;self.e.review(self.f())
        s=self.e.state();self.assertLess(s['last_performance']['advantage_usd'],0);self.assertEqual(s['wallet'],after)
        self.assertEqual(s['original']['ETH'],D('.05'));self.assertGreater(s['max_drawdown'],0)
    def test_pause_and_suspend_do_not_earn_hours_or_rewrite_baseline_or_limits(self):
        self.e.review(self.f());self.c.tick(10);self.e.heartbeat(persist=True);valid=self.e.progress()['valid_seconds'];self.assertEqual(valid,10)
        self.e.pause();self.c.tick(20);self.e.heartbeat(persist=True);self.assertEqual(self.e.progress()['valid_seconds'],valid)
        saved=self.e.state();self.e.shutdown();self.c.tick(3600);self.e=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(self.e.running);self.assertEqual(self.e.progress()['valid_seconds'],valid)
        self.e.start();self.e.review(self.f());self.c.at+=3600;self.c.mono+=NS;self.e.heartbeat()
        self.assertEqual(self.e.progress()['valid_seconds'],valid)
        for key in ('original','config','trial_id','fees_native'):self.assertEqual(self.e.state()[key],saved[key])
        with self.assertRaises(BetaBlocked):self.e._change('BAD_HOLD',{},lambda s:s['original'].update(ETH=D(99)))
    def test_zero_trade_168_hour_completion_freezes_report_and_does_not_reseed_on_restart(self):
        self.e.review(self.f());self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock()
        self.c.tick(10);self.e.heartbeat(persist=True);s=self.e.state();self.assertEqual(s['mode'],'COMPLETE')
        self.assertEqual(s['metrics']['orders'],0);self.assertEqual(s['completed_report']['original'],s['original'])
        reports=list(self.path.parent.glob('opportunity-*-summary.json'));self.assertEqual(len(reports),1);report=reports[0].read_bytes()
        self.e.shutdown();self.c.tick(36000);self.e=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);self.e.heartbeat()
        self.assertEqual(self.e.state(),s);self.assertEqual(reports[0].read_bytes(),report)
        with self.assertRaises(BetaBlocked):self.e.start()
    def test_168_hours_cancels_reconciles_active_order_before_freezing_even_if_paused(self):
        self.warm();o=self.acknowledge();self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock()
        self.c.tick(10);self.e.heartbeat(persist=True);self.assertEqual(self.e.state()['mode'],'FINALIZING')
        self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING');self.e.pause()
        self.assertEqual(self.e.store.clock['phase'],'COMPLETE');self.c.tick(3);self.e.heartbeat(persist=True)
        s=self.e.state();self.assertEqual(s['mode'],'COMPLETE');self.assertIsNone(active(s));self.assertEqual(s['metrics']['nonfills'],1)
        self.assertEqual(s['wallet'],s['original']);self.assertEqual(s['orders'][o['reference']]['reserved'],0)
    def test_stop_at_last_placement_boundary_creates_no_intent(self):
        from unittest.mock import patch
        original=self.e._place
        def stopped(*args,**kwargs):self.e.stop_flag.set();return original(*args,**kwargs)
        with patch.object(self.e,'_place',side_effect=stopped):
            for i in range(61):self.step=i//3;self.e.review(self.f());self.c.tick(10)
        self.assertEqual(self.e.state()['metrics']['orders'],0)
    def test_terminal_fill_keeps_full_receipt_in_append_only_evidence_without_repeating_trade_cache(self):
        self.warm();o=self.acknowledge();self.fill(o,trade='terminal-evidence')
        event=self.e.store.events()[-1]['payload']['evidence']
        self.assertIsNone(event['active']);self.assertEqual(len(event['orders']),1)
        fill=event['orders'][0]['new_fills']['terminal-evidence']
        self.assertEqual(fill['receipt']['size'],o['size']);self.assertEqual(fill['flow']['commission'],o['size']*o['price']*D('.005'))
        self.assertEqual(event['orders'][0]['state'],'FILLED');self.assertIsNone(event['venue'])

class SQLiteResources(unittest.TestCase):
    def test_closed_after_success_rollback_corruption_and_failed_initialization(self):
        with TemporaryDirectory() as data,trial_sqlite_probe() as probe:
            c=Clock();path=Path(data)/'trial.sqlite3';e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns);e.start();e.review(market(c))
            probe.assert_released(self,path);saved=e.state()
            with self.assertRaises(BetaBlocked):e._change('BAD_ORIGINAL',{},lambda s:s['original'].update(BTC=D(99)))
            self.assertEqual(e.state(),saved);probe.assert_released(self,path)
            with closing(sqlite3.connect(path)) as db,db,closing(db.cursor()) as cur:cur.execute("UPDATE trial_clock SET digest='corrupt'")
            before=path.read_bytes();broken=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns)
            self.assertTrue(broken.load_error);self.assertEqual(path.read_bytes(),before);probe.assert_released(self,path)
            def fail(sql):
                if sql.startswith('CREATE TABLE'):raise sqlite3.OperationalError('synthetic initialization failure')
            probe.fault=fail;badpath=Path(data)/'failed.sqlite3';bad=OpportunityTrader(badpath,clock=c.wall,monotonic_ns=c.ns);bad.start()
            with self.assertRaises(sqlite3.OperationalError):bad.review(market(c))
            self.assertTrue(bad.load_error);self.assertFalse(bad.running);probe.assert_released(self,badpath)
