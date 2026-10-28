"""Synthetic scheduling/quote regressions. No Coinbase calls or financial data."""
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import queue
import time
import unittest
from pathlib import Path

from coincat_app import CoinCatApp
from coincat_v6018_fast_path import select_fast_books,fast_candidates,fundable_alerts
from coincat_v701_transport import collect_background,ScoutCollector,QuoteSnapshot
from coincat_v705_worker import worker_state
from offline_tests import test_v703_chain_contract as fixtures
from offline_tests import test_v701_urgent_quotes as urgent_fixtures


def snapshot(pair,stamp=1800000000):
    return QuoteSnapshot(pair,D(1),D('1.0001'),stamp,stamp,1)


class ActualBroadCycle(unittest.TestCase):
    def test_real_broad_cycle_uses_bounded_quotes_and_records_current_phases(self):
        import tkinter as tk
        with TemporaryDirectory() as folder,patch('coincat_app.ROOT',Path(folder)), \
                patch('coincat_v701_transport.BACKGROUND',ScoutCollector()):
            top=tk.Tk();app=CoinCatApp(top)
            try:
                app.catalog=['BTC-USD'];app.catalog_at=time.time()
                app.ledger.approve_one('USD','10');app.current_balances={'USD':'10'}
                app._last_portfolio_sync_monotonic=time.monotonic()
                app.broker=NS(armed=False,ledger=app.ledger,client=NS(),per_order_max='10',
                    catalog_product_rules=fixtures.rules(app.catalog),
                    reconcile=lambda:{'state':'NO_PENDING'},disarm=Mock(),
                    submit=Mock(side_effect=AssertionError('NO REAL ORDER')))
                app.stream.set_pairs=Mock();app._last_depth_probe_at=time.monotonic()
                app._service_fast_checkpoint=Mock(return_value=False)
                with patch('coincat_app.fetch_snapshot',side_effect=lambda p,**kw:snapshot(p,time.time())):
                    result=app._cycle(allow_orders=False)
                self.assertEqual(result['quotes'],1)
                self.assertEqual(result['scan_network']['deep']['requested'],1)
                self.assertIn('QUOTE_FETCH',result['scan_phase_timings_s'])
                self.assertIn('ROTATION_PLANNER',result['scan_phase_timings_s'])
                self.assertEqual(app._scan_phase['name'],'COMPLETE')
                self.assertGreater(app._service_fast_checkpoint.call_count,5)
                app.broker.submit.assert_not_called()
            finally:app._close()


class WorkerTiming(unittest.TestCase):
    def app(self):
        app=CoinCatApp.__new__(CoinCatApp)
        app.worker_busy=True;app._scan_processing=False
        app._scan_started_at=800;app._last_scan_at=950
        app._worker_operation='fast Snowball research';app._worker_started_at=998
        app._fast_observed_at=1999;app._scan_phase={'name':'COMPLETE','started_at':950}
        app.lab_heartbeat=NS(set=Mock());app.lab_activity=NS(set=Mock())
        app.status=NS(set=Mock());app.broker=NS(armed=False,disarm=Mock())
        return app

    def test_old_scan_timer_cannot_warn_for_new_urgent_job(self):
        app=self.app()
        with patch('coincat_app.time.monotonic',return_value=1000),patch('coincat_app.time.time',return_value=2000):
            app._refresh_research_heartbeat()
        state=worker_state(app,mono=1000,wall=2000)
        self.assertFalse(state['scan_active']);self.assertFalse(state['slow_scan'])
        self.assertEqual(state['elapsed_s'],2)
        app.lab_activity.set.assert_not_called();app.broker.disarm.assert_not_called()
        self.assertIn('fast Snowball research active 2s',app.lab_heartbeat.set.call_args.args[0])

    def test_genuinely_slow_scan_identifies_phase_without_guessing_connectivity(self):
        app=self.app();app._scan_processing=True
        app._worker_operation='market scan';app._worker_started_at=800
        app._scan_phase={'name':'ROTATION_PLANNER','started_at':997}
        with patch('coincat_app.time.monotonic',return_value=1000),patch('coincat_app.time.time',return_value=2000):
            app._refresh_research_heartbeat()
        message=app.lab_activity.set.call_args.args[0]
        self.assertIn('ROTATION_PLANNER 3s',message)
        self.assertIn('last completed urgent decision 1s ago',message)
        self.assertNotIn('check connectivity',message)
        # When that job finishes, its timeout warning must not stick to the next.
        app._scan_processing=False;app._worker_operation='portfolio sync';app._worker_started_at=999
        with patch('coincat_app.time.monotonic',return_value=1000),patch('coincat_app.time.time',return_value=2000):
            app._refresh_research_heartbeat()
        self.assertFalse(app._scan_timeout_warning_active)
        self.assertIn('portfolio sync active 1s',app.lab_activity.set.call_args.args[0])

    def test_actual_async_job_keeps_single_worker_and_clears_timing(self):
        app=self.app();app.worker_busy=False;app.jobs=queue.Queue()
        entered=Event();release=Event()
        def task():
            entered.set();release.wait(1);return {'kind':'synthetic'}
        try:
            self.assertTrue(app._async(task,operation='fast Snowball research'))
            self.assertTrue(entered.wait(1))
            self.assertFalse(app._async(lambda:None,operation='market scan'))
            self.assertEqual(app._worker_operation,'fast Snowball research')
            self.assertFalse(worker_state(app,mono=time.monotonic(),wall=time.time())['slow_scan'])
        finally:release.set()
        self.assertEqual(app.jobs.get(timeout=1),('ok',{'kind':'synthetic'}))
        deadline=time.monotonic()+1
        while app.worker_busy and time.monotonic()<deadline:time.sleep(.001)
        self.assertFalse(app.worker_busy);self.assertIsNone(app._worker_operation)
        self.assertEqual(app._worker_started_at,0)

    def test_phase_timing_is_current_and_checkpoints_between_stages(self):
        app=self.app();app.jobs=queue.Queue();app._service_fast_checkpoint=Mock(return_value=False)
        with patch('coincat_app.time.monotonic',side_effect=[100,103,108]):
            app._scan_stage('RECONCILIATION',checkpoint=False)
            app._scan_stage('QUOTE_FETCH')
            app._scan_stage('COMPLETE',checkpoint=False)
        self.assertEqual(app._scan_phase_timings,{'RECONCILIATION':3,'QUOTE_FETCH':5})
        app._service_fast_checkpoint.assert_called_once()


class BoundedBackgroundQuotes(unittest.TestCase):
    def test_budget_defers_then_rotates_without_dropping_tail_pairs(self):
        clock=[0.0];seen=[]
        class Collector:
            def collect(self,pairs,**kw):
                self.assertion=len(pairs)<=16
                clock[0]+=kw['seconds'];seen.extend(pairs)
                return {p:snapshot(p) for p in pairs},{},kw['seconds']*1000
        collector=Collector();pairs=[f'C{i:02}-USD' for i in range(64)]
        first,stats=collect_background(pairs,seconds=12,collector=collector,clock=lambda:clock[0])
        self.assertEqual(stats['requested'],48);self.assertEqual(stats['unrequested'],16)
        self.assertEqual(len(first),48);self.assertEqual(stats['elapsed_s'],12)
        collect_background(pairs,cursor=stats['next_cursor'],seconds=12,collector=collector,clock=lambda:clock[0])
        self.assertEqual(set(seen),set(pairs));self.assertTrue(collector.assertion)

    def test_urgent_checkpoint_time_counts_against_background_budget(self):
        clock=[0.0];collector=NS(collect=Mock())
        def urgent():clock[0]+=5
        books,stats=collect_background(['BTC-USD'],seconds=5,checkpoint=urgent,
            collector=collector,clock=lambda:clock[0])
        self.assertEqual(books,{})
        self.assertEqual(stats['unrequested'],1);self.assertEqual(stats['requested'],0)
        collector.collect.assert_not_called()

    def test_stalled_background_get_cannot_block_urgent_collector_or_publish_late_quote(self):
        background=ScoutCollector();urgent=ScoutCollector()
        release=Event();finished=Event()
        def slow(pair,**kw):
            try:release.wait(1);return snapshot(pair)
            finally:finished.set()
        try:
            books,stats=collect_background(['BTC-USD'],seconds=.01,collector=background,fetch=slow)
            self.assertEqual(books,{})
            self.assertEqual(stats['errors'],{'SCOUT_DEADLINE':1})
            books,stats=collect_background(['SOL-USD'],seconds=.01,collector=background,fetch=slow)
            self.assertEqual(stats['requested'],0)
            self.assertIn('PREVIOUS_GETS_IN_FLIGHT',stats['errors'])
            books,errors,_=urgent.collect(['ETH-USD'],seconds=.1,fetch=lambda p,**kw:snapshot(p))
            self.assertEqual(set(books),{'ETH-USD'});self.assertEqual(errors,{})
        finally:release.set();self.assertTrue(finished.wait(1))


class FairSchedulingAndCandidates(unittest.TestCase):
    def test_due_broad_scan_eventually_gets_time_without_manual_button(self):
        app=urgent_fixtures.UrgentScheduling.app(self)
        app.worker_busy=False;app._scan_processing=False;app._next_scan_at=900
        app._last_portfolio_sync_monotonic=1000;app._broad_wait_since=969
        app.portfolio_sync_secs=180;app._history_requested=app._history_in_progress=False
        app._auto_history_checked=1000;app._gpu_schedule=NS(next_due=2000,active=False)
        app._scan_epoch=0;app.loop_secs=180
        app.lab_activity=NS(set=Mock());app.lab_progress=NS(start=Mock())
        app.root=NS(after=lambda *a:1);app._scheduled={}
        app._async=Mock(side_effect=lambda *a,**kw:setattr(app,'worker_busy',True) or True)
        with patch('coincat_app.time.monotonic',return_value=1000):
            app._tick_impl()
            self.assertEqual(app._async.call_args.kwargs['operation'],'market scan')
            self.assertTrue(app._service_fast_checkpoint())
        self.assertEqual(app._broad_wait_since,0)

    def test_slow_urgent_completion_leaves_background_room_to_progress(self):
        app=urgent_fixtures.UrgentScheduling.app(self);clock=[1000.0]
        app._last_portfolio_sync_monotonic=1000
        def fast():clock[0]+=6;return {'kind':'fast_snowball'}
        app._fast_cycle=Mock(side_effect=fast)
        with patch('coincat_app.time.monotonic',side_effect=lambda:clock[0]):
            self.assertTrue(app._service_fast_checkpoint())
            self.assertEqual(app._fast_next_at,1011)
            self.assertFalse(app._service_fast_checkpoint())
            clock[0]=1011;self.assertTrue(app._service_fast_checkpoint())

    def test_liquid_alerts_then_rotating_slot_prevent_three_product_monopoly(self):
        catalog=[f'C{i:02}-USD' for i in range(6)]
        wide={p:(D(1),D('1.1'),1000) for p in catalog[:3]}
        first=select_fast_books(catalog,catalog,['USD'],quotes=wide,now=1000)
        self.assertEqual({p for a,p in first['targets']},set(catalog[3:]))
        reached=set()
        for cursor in range(4):
            plan=select_fast_books(catalog,catalog,['USD'],now=1000,target_cursor=cursor)
            reached.update(p for a,p in plan['targets'])
        self.assertEqual(reached,set(catalog))

    def test_another_quote_can_discover_a_directly_fundable_coin_without_bridge(self):
        catalog=['ALT-USD','ALT-BTC','BTC-USD']
        stream={'rows':[{'pair':'ALT-USD','change_30s_pct':2.4}]}
        self.assertEqual(fundable_alerts(['ALT-USD'],catalog,['BTC'],stream),['ALT-USD'])
        self.assertEqual(fundable_alerts(['ALT-USD'],['ALT-USD','BTC-USD'],['BTC'],stream),[])

    def test_actual_funded_book_can_qualify_when_discovery_book_is_wide_or_absent(self):
        for quotes in ({'ALT-BTC':('1','1.0001',1000)},
                       {'ALT-BTC':('1','1.0001',1000),'ALT-USD':('1','1.1',1000)}):
            ideas,rejected=fast_candidates([('ALT','ALT-USD')],quotes,
                {'rows':[{'pair':'ALT-USD','change_30s_pct':2.4}]},now=1000,
                target_routes={'ALT':['ALT-BTC']})
            self.assertEqual(rejected,0);self.assertEqual(ideas[0]['verified_funding_pair'],'ALT-BTC')
        ideas,rejected=fast_candidates([('ALT','ALT-USD')],{}, {},now=1000,
            target_routes={'ALT':['ALT-BTC']})
        self.assertEqual(ideas,[]);self.assertEqual(rejected,1)

    def test_real_urgent_pipeline_models_only_liquid_actual_leg_from_wide_discovery(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=fixtures.SyntheticWholeChain.fixture(self,folder)
            app.experimental_shadow.disarm()
            app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
                usd_coverage=True,enrolled_quantities={'BTC':'.1'},fresh_usd_rates={'BTC':'500'},now=fixtures.NOW-1)
            app._experimental_model_balances={'BTC':'.1'}
            app.current_balances={'BTC':'.1'};rows[0].update(asset='BTC',remaining_qty='.1')
            app.catalog=['ALT-USD','ALT-BTC','BTC-USD'];app.broker.catalog_product_rules=fixtures.rules(app.catalog)
            app.broker.ledger=NS(pending=lambda:[])
            app.shutdown=False;app._connection_requested=app._connection_in_progress=False
            app._fill_sync_faulted=False;app._fast_next_at=0
            app.stream_research=NS(rank_for_rest_scout=lambda catalog,**kw:['ALT-USD'] if 'ALT-USD' in catalog else [],
                snapshot=lambda **kw:{'rows':[{'pair':'ALT-USD','last_trade':5,'age_ms':0,'change_30s_pct':2.4}]})
            prices={'ALT-USD':(D(5),D(6)),'ALT-BTC':(D('.01'),D('.010001')),'BTC-USD':(D(500),D('500.01'))}
            fetch=Mock(side_effect=lambda pair,**kw:QuoteSnapshot(pair,*prices[pair],clock[0],clock[0],1))
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                self.assertTrue(app._fast_due())
                payload=app._fast_cycle()
                self.assertEqual(payload['state'],'RESEARCHED',payload.get('reason'))
                self.assertEqual(app._apply_fast_experimental(payload),1)
            step=payload['plan']['ideas'][0]['shadow_fifo_steps']
            self.assertEqual(len(step),1);self.assertEqual(step[0]['pair'],'ALT-BTC')
            self.assertGreater(app.experimental_shadow.model_balances()['ALT'],0)
            self.assertTrue(app.experimental_shadow.fifo_portfolios['TAKER_ASK'].quantity_parity())
            app.broker.submit.assert_not_called()


if __name__=='__main__':unittest.main()
