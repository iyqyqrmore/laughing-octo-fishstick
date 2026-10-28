"""Synthetic v70.1 regressions: no network, credentials, or real orders."""
from decimal import Decimal as D
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import queue
import time
import unittest

from coincat_app import CoinCatApp
from coincat_v6018_fast_path import select_fast_books, fast_funnel
from coincat_v701_quotes import newest_books, mark_coverage, required_shadow_assets
from coincat_v701_transport import (
    GetBudget, QuoteDeferred, QuoteSnapshot, ScoutCollector, fetch_snapshot)
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio


class QuoteSelection(unittest.TestCase):
    def test_newest_valid_wins_independent_of_source_order(self):
        old={'BTC-USD':('90','90.01',850)}
        new={'BTC-USD':('100','100.01',999)}
        for sources in ((old,new),(new,old)):
            self.assertEqual(newest_books(*sources,now=1000,max_age=180)['BTC-USD'][2],999)
        app=NS(forward=NS(recent_bid_ask=lambda **kw:new),_portfolio_quotes=old)
        with patch('coincat_app.time.time',return_value=1000):
            self.assertEqual(CoinCatApp._shadow_valuation_books(app)['BTC-USD'][2],999)

    def test_invalid_newer_does_not_displace_valid_quote_and_expiry_is_enforced(self):
        good={'BTC-USD':('100','100.01',999)}
        for raw in [('NaN','101',1000),('102','101',1000),('100','101',1000),
                    ('100','100.01',1001),('100','100.01',float('nan')),None]:
            self.assertEqual(newest_books(good,{'BTC-USD':raw},now=1000)['BTC-USD'][2],999)
        self.assertFalse(newest_books({'BTC-USD':('100','100.01',900)},now=1000,max_age=30))

    def test_zero_and_negative_budget_make_no_requests(self):
        for limit in (0,-1):
            p=select_fast_books(['SOL-USD'],['SOL-USD'],['USD'],limit=limit)
            self.assertEqual(p['books'],[])
            self.assertEqual(p['targets'],[])

    def test_complete_hold_marks_take_priority_over_redundant_routes(self):
        funding=[f'C{i:02}' for i in range(10)]
        catalog=['SOL-USD']+[f'SOL-{a}' for a in funding]+[f'{a}-USD' for a in funding]
        plan=select_fast_books(['SOL-USD'],catalog,funding,now=1000)
        self.assertTrue(all(f'{a}-USD' in plan['books'] for a in funding))
        self.assertIn('SOL-C00',plan['books'])
        self.assertIn('SOL-USD',plan['books'])
        self.assertLessEqual(len(plan['books']),16)

    def test_exhausted_budget_refreshes_in_stages_without_fake_targets(self):
        assets=[f'C{i:02}' for i in range(20)]
        catalog=[f'{a}-USD' for a in assets]+['SOL-USD']
        first=select_fast_books(['SOL-USD'],catalog,['USD'],required_assets=assets,now=1000)
        self.assertEqual(len(first['books']),16)
        self.assertTrue(first['mark_refresh_deferred'])
        self.assertEqual(first['targets'],[])
        cache={p:('1','1.001',1000) for p in first['books']}
        second=select_fast_books(['SOL-USD'],catalog,['USD'],required_assets=assets,quotes=cache,now=1005)
        self.assertEqual(len(second['books']),5)
        self.assertEqual(second['targets'],[('SOL','SOL-USD')])

    def test_sold_hold_and_fee_asset_dependencies_survive_without_sqlite_worker_access(self):
        wallet=NS(start={'BTC':'1'},balances=Mock(side_effect=AssertionError('GUI SQLite only')))
        session=NS(armed=True,fifo_portfolios={'TAKER_ASK':wallet})
        assets=required_shadow_assets(session,funding=['ETH','USDC'])
        self.assertEqual(assets,['BTC','ETH','USDC'])
        wallet.balances.assert_not_called()

    def test_stablecoin_bridge_has_real_usd_mark_and_never_assumes_peg(self):
        catalog=['SOL-USDC','USDC-USD']
        p=select_fast_books(['SOL-USDC'],catalog,['USDC'],now=1000)
        self.assertEqual(set(p['books']),set(catalog))
        c=mark_coverage(['SOL'],{'SOL-USDC':('10','10.01',1000),
                                 'USDC-USD':('.90','.901',1000)},now=1000)
        self.assertTrue(c['complete'])
        self.assertEqual(D(c['rates']['SOL']),D('9'))
        self.assertFalse(mark_coverage(['SOL'],{'SOL-USDC':('10','10.01',1000)},now=1000)['complete'])

    def test_skew_stale_missing_and_future_marks_fail_closed(self):
        for stamp in (980,900,1001):
            books={'BTC-USD':('100','100.01',stamp),'ETH-USD':('10','10.01',1000)}
            self.assertFalse(mark_coverage(['BTC','ETH'],books,now=1000)['complete'])
        self.assertFalse(mark_coverage(['GHOST'],{},now=1000)['complete'])

    def test_funnel_does_not_call_successful_http_responses_fresh(self):
        self.assertEqual(fast_funnel(fetched=10,fresh=3)['fresh_books'],3)
        self.assertEqual(fast_funnel(fetched=10)['fresh_books'],0)


class SyntheticSequentialWallet(unittest.TestCase):
    def test_multiple_conversions_require_original_and_acquired_assets(self):
        marks={'BTC':'50000','ETH':'2000','USD':'1'}
        w=ShadowFIFOPortfolio({'BTC':'1'},marks)
        try:
            steps=[dict(pair='BTC-USD',side='SELL',gross_base_quantity=D('.01'),
                        input_quantity=D('.01'),output_quantity=D('495'),fee_rate_used=D('.01')),
                   dict(pair='ETH-USD',side='BUY',gross_base_quantity=D('.2'),
                        input_quantity=D('401.6'),output_quantity=D('.2'),fee_rate_used=D('.004'))]
            for i,step in enumerate(steps):
                w.post_hypothetical_route(session_id=f'SHADOW-V701-{i}',steps=[step],
                                         usd_rates=marks,at_utc=1770000000+i)
            self.assertEqual(w.mark_vs_hold(marks)['delta_usd'],D('-6.6'))
            self.assertTrue(w.quantity_parity())
            self.assertEqual(w.mark_problems({'BTC':'50000','USD':'1'}),{'ETH':'MISSING_USD_MARK'})
            self.assertEqual(w.mark_problems(dict(marks,ETH='NaN')),{'ETH':'INVALID_USD_MARK'})
            with self.assertRaises(KeyError):w.mark_vs_hold({'BTC':'50000','USD':'1'})
            # Counter values must not establish parity after actual corruption.
            w.db.execute("UPDATE unified_v501_wallets SET qty='2' WHERE asset='BTC'")
            self.assertFalse(w.quantity_parity())
        finally:w.close()

    def test_queued_plan_is_rejected_if_urgent_conversion_changed_wallet(self):
        app=CoinCatApp.__new__(CoinCatApp)
        session=NS(model_balances=lambda:{'ETH':D('1')})
        self.assertEqual(app._current_shadow_ideas({'model':{'BTC':'1'}},session,'model',[{}]),())
        self.assertEqual(app._current_shadow_ideas({'model':{'ETH':'1.00'}},session,'model',[{}]),[{}])

    def test_incomplete_or_asynchronous_marks_cannot_mature_wallet_outcomes(self):
        app=CoinCatApp.__new__(CoinCatApp)
        session=NS(model_balances=lambda:{'ETH':D('1')},
                   fifo_portfolios={'TAKER_ASK':NS(start={'BTC':'1'})})
        books={'BTC-USD':('100','100.01',980),'ETH-USD':('10','10.01',1000)}
        rates,complete=app._shadow_mark_rates(session,books,1000)
        self.assertFalse(complete)
        self.assertEqual(rates,{})
        self.assertEqual(session.mark_problems['_snapshot'],'UNSYNCHRONIZED_USD_PATHS')


class SyntheticTransport(unittest.TestCase):
    def response(self,status=200,headers=None):
        return NS(status_code=status,headers=headers or {},raise_for_status=lambda:None,
                  json=lambda:{'best_bid':'100','best_ask':'100.01'})

    def test_snapshot_uses_request_start_not_receipt_and_preserves_unknown_exchange_time(self):
        clock=[100.0]
        def get(*args,**kwargs):clock[0]+=1;return self.response()
        with patch('coincat_v701_transport.time.monotonic',side_effect=lambda:clock[0]), \
             patch('coincat_v701_transport.time.time',side_effect=lambda:clock[0]):
            snap=fetch_snapshot('BTC-USD',get=get,budget=GetBudget(interval=0,clock=lambda:clock[0]))
        self.assertEqual(snap.observed_at,100)
        self.assertEqual(snap.received_at,101)
        self.assertEqual(snap.request_ms,1000)
        self.assertIsNone(snap.exchange_timestamp)

    def test_429_defers_following_get_without_retry(self):
        clock=lambda:100
        budget=GetBudget(clock=clock)
        get=Mock(return_value=self.response(429,{'Retry-After':'30'}))
        with self.assertRaisesRegex(QuoteDeferred,'HTTP_429'):
            fetch_snapshot('BTC-USD',deadline=time.monotonic()+1,get=get,budget=budget)
        self.assertEqual(budget.blocked_until,130)
        with self.assertRaisesRegex(QuoteDeferred,'RATE_BUDGET'):
            budget.acquire(110)
        self.assertEqual(get.call_count,1)

    def test_http_date_retry_after_and_invalid_value(self):
        budget=GetBudget(clock=lambda:100)
        budget.postpone('Thu, 01 Jan 1970 00:01:00 GMT',wall=lambda:0)
        self.assertEqual(budget.blocked_until,160)
        budget.postpone('not a date')
        self.assertEqual(budget.blocked_until,160)

    def test_slow_get_and_clock_jump_are_not_recorded_as_new_prices(self):
        for delay,wall_jump in ((3.5,0),(1,20)):
            clock=[100.0]
            def get(*args,**kwargs):clock[0]+=delay;return self.response()
            with patch('coincat_v701_transport.time.monotonic',side_effect=lambda:clock[0]), \
                 patch('coincat_v701_transport.time.time',side_effect=lambda:clock[0]+(wall_jump if clock[0]>100 else 0)):
                with self.assertRaises(QuoteDeferred):
                    fetch_snapshot('BTC-USD',get=get,budget=GetBudget(interval=0,clock=lambda:clock[0]))

    def test_collection_deadline_does_not_accumulate_batches_or_accept_late_result(self):
        collector=ScoutCollector();release=Event();finished=Event()
        def fetch(pair,**kw):
            try:
                release.wait(1)
                return QuoteSnapshot(pair,D(1),D(1),100,100,1)
            finally:finished.set()
        try:
            snapshots,errors,_=collector.collect(['BTC-USD'],fetch=fetch,seconds=.01)
            self.assertEqual(snapshots,{})
            self.assertEqual(errors,{'SCOUT_DEADLINE':1})
            snapshots,errors,_=collector.collect(['ETH-USD'],fetch=fetch,seconds=.01)
            self.assertIn('PREVIOUS_GETS_IN_FLIGHT',errors)
        finally:
            release.set();self.assertTrue(finished.wait(1))


class UrgentScheduling(unittest.TestCase):
    def app(self):
        app=CoinCatApp.__new__(CoinCatApp)
        app.shutdown=False;app.broker=NS(ledger=NS(pending=lambda:[]))
        app.catalog=['SOL-USD'];app._last_portfolio_sync_monotonic=time.monotonic()
        app._fast_next_at=0;app._fast_interval_s=5
        app._connection_requested=app._connection_in_progress=False
        app._fill_sync_faulted=False
        app.stream_research=NS(rank_for_rest_scout=lambda *args,**kw:['SOL-USD'])
        app.jobs=queue.Queue();app._fast_cycle=Mock(return_value={'kind':'fast_snowball'})
        return app

    def test_urgent_checkpoint_runs_during_background_scan_or_history(self):
        app=self.app();app.worker_busy=True;app._history_in_progress=True
        self.assertTrue(app._service_fast_checkpoint())
        self.assertEqual(app.jobs.get()[1],{'kind':'fast_snowball'})
        app._fast_cycle.assert_called_once()
        self.assertFalse(app._service_fast_checkpoint())

    def test_pending_fills_stale_account_or_fault_precede_urgency(self):
        for blocker in ('fills','stale','fault'):
            app=self.app()
            if blocker=='fills':app.broker.ledger.pending=lambda:[1]
            if blocker=='stale':app._last_portfolio_sync_monotonic-=121
            if blocker=='fault':app._fill_sync_faulted=True
            self.assertFalse(app._service_fast_checkpoint())
            app._fast_cycle.assert_not_called()

    def test_idle_urgency_precedes_due_full_scan_history_and_gpu(self):
        app=self.app()
        app.worker_busy=False;app._scan_processing=False;app._next_scan_at=0
        app.portfolio_sync_secs=180;app._history_requested=app._history_in_progress=False
        app._auto_history_checked=0;app._gpu_schedule=NS(next_due=0,active=False)
        def start(*args,**kwargs):app.worker_busy=True;return True
        app._async=Mock(side_effect=start)
        app._start_history=Mock();app._launch_gpu_research=Mock()
        app.root=NS(after=lambda *args:1);app._scheduled={}
        app._tick_impl()
        app._async.assert_called_once_with(app._fast_cycle,operation='fast Snowball research')
        app._start_history.assert_not_called();app._launch_gpu_research.assert_not_called()


class SyntheticFastIntegration(unittest.TestCase):
    def app(self):
        app=CoinCatApp.__new__(CoinCatApp)
        app.broker=NS(catalog_product_rules={p:{'base_increment':'.00000001',
            'base_min_size':'.00000001','quote_min_size':'.01'} for p in ['SOL-USDC','SOL-BTC']})
        app.catalog=['SOL-USDC','SOL-BTC','SOL-USD','BTC-USD','USDC-USD']
        app._last_portfolio_sync_monotonic=time.monotonic()
        app.current_balances={'USDC':'100','BTC':'.01'}
        app.external_mismatches=[]
        app.ledger=NS(assets=lambda:[{'asset':a,'remaining_qty':q,'enabled':1}
                                    for a,q in app.current_balances.items()])
        app.fee_learning=NS(latest_tier=lambda:{'fresh':True,'taker':D('.009')})
        app.stream_research=NS(rank_for_rest_scout=lambda *a,**kw:['SOL-USDC'],
            snapshot=lambda **kw:{'rows':[{'pair':'SOL-USDC','last_trade':10,
                                          'age_ms':20,'change_30s_pct':2.4}]})
        app._fast_candidate_signature=None;app._fast_candidate_signature_at=0
        app.experimental_shadow=NS(armed=False);app.shadow_pilot=NS(armed=False)
        app.relative_lab=NS(paired_outcomes=lambda *a,**kw:{'status':'NOT_VERIFIED'})
        app.switch_minimum_usd=D('.10')
        books={}
        app.forward=NS(record_quote=lambda p,ts,b,a,**kw:books.update({p:(b,a,ts)}))
        app._shadow_valuation_books=lambda:books.copy()
        return app

    def snapshot(self,pair,**kw):
        prices={'SOL-USDC':('9.98','10.00'),'SOL-USD':('9.98','10.00'),
                'USDC-USD':('.999','1.001'),'BTC-USD':('50000','50001'),
                'SOL-BTC':('.0001996','.0002')}
        return QuoteSnapshot(pair,*map(D,prices[pair]),time.time(),time.time(),1)

    def test_missing_mandatory_mark_does_not_cool_down_recovery(self):
        app=self.app()
        def broken(pair,**kw):
            if pair in ('USDC-USD','SOL-USD'):raise QuoteDeferred('SYNTHETIC_TIMEOUT')
            return self.snapshot(pair)
        with patch('coincat_app.fetch_snapshot',side_effect=broken):
            first=app._fast_cycle()
        self.assertEqual(first['state'],'WAIT')
        self.assertIsNone(app._fast_candidate_signature)
        with patch('coincat_app.fetch_snapshot',side_effect=self.snapshot):
            recovered=app._fast_cycle()
        self.assertEqual(recovered['state'],'RESEARCHED')

    def test_failed_alternative_does_not_block_complete_fundable_route(self):
        app=self.app()
        def broken_alternative(pair,**kw):
            if pair=='SOL-BTC':raise QuoteDeferred('SYNTHETIC_TIMEOUT')
            return self.snapshot(pair)
        with patch('coincat_app.fetch_snapshot',side_effect=broken_alternative):
            result=app._fast_cycle()
        self.assertEqual(result['state'],'RESEARCHED')
        self.assertGreater(result['plan']['exploratory_viable_routes'],0)
        self.assertTrue(result['plan']['ideas'])
        self.assertIn('SYNTHETIC_TIMEOUT',result['get_errors'])
        self.assertIsNone(app._fast_candidate_signature)
        self.assertFalse(result['live_order_permission'])


if __name__=='__main__':unittest.main()
