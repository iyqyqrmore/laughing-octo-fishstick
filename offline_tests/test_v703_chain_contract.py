"""Synthetic chain contracts. No keys, external calls or real financial data.

The hourly replay advances an artificial clock; it does not measure Coinbase
execution, Windows latency, predictive accuracy or profitable opportunities.
"""
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import sqlite3
import time
import unittest

from coincat_app import CoinCatApp
from coincat_cross_quote import usd_conversion
from coincat_live_forward_store import ForwardStore
from coincat_multicurrency import RotationContext, available_routes, evaluate_rotation
from coincat_v507_shadow_arm import ShadowArmedResearch, experimental_shadow_report
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio
from coincat_v6018_fast_path import fast_funnel, select_fast_books
from coincat_v605_shadow_bridge import shadow_screen
from coincat_v606_budgets import DEFAULT, effective
from coincat_v701_transport import QuoteSnapshot
from coincat_v703_chain import (approved_pairs, decision_key, experimental_score,
                                ranked_one_order_ideas, step_input_usd, target_momentum)


NOW=1800000000


def rules(pairs):
    return {p:dict(product_id=p,product_type='SPOT',status='online',
                   base_increment='.00000001',base_min_size='.00000001',
                   quote_min_size='.00001') for p in pairs}


def make_plan(source='USD',target='BTC',cap='10',now=NOW,books=None,quantity='1000'):
    books=books or {'BTC-USD':(D('100'),D('100.01'),now)}
    result=evaluate_rotation(source=source,target=target,authorized_qty=quantity,
        verified_available_qty=quantity,balance_age_s=0,catalog=list(books),quotes=books,
        now=now,usd_per_order_cap=cap,product_rules=rules(books),fee_rate='.009',max_legs=1)
    route=result['routes'][0]
    return dict(source=source,target=target,trigger_pair=route['route'][0][0],
        route=route['route'],shadow_fifo_steps=route['steps'],
        input_units_planned=route['input_units_planned'],
        destination_units_estimate=route['destination_units_estimate'],
        immediate_change_usd=route['immediate_change_usd'],research_size_cap_usd=D(cap),
        observed_momentum_pct=D('2.4'),sends_live_orders=False,oos_validated=False)


class SyntheticUnitsAndReceipts(unittest.TestCase):
    def test_buy_sell_cross_quote_fee_slippage_rounding_and_fifo_parity(self):
        books={'BTC-USD':(D('50000'),D('50001'),NOW),
               'ETH-USD':(D('2000'),D('2000.1'),NOW),
               'SOL-USD':(D('100'),D('100.01'),NOW),
               'USDC-USD':(D('.94'),D('.9401'),NOW),
               'BTC-ETH':(D('25'),D('25.001'),NOW),
               'SOL-BTC':(D('.002'),D('.0020001'),NOW),
               'SOL-USDC':(D('106.38'),D('106.39'),NOW)}
        cases=[('USD','BTC','1000','500'),('BTC','USD','.5','500'),
               ('BTC','ETH','.5','500'),('ETH','BTC','4','500'),
               ('BTC','SOL','.5','500'),('SOL','BTC','12','500'),
               ('USDC','SOL','1000','500')]
        for source,target,qty,cap in cases:
            with self.subTest(source=source,target=target):
                # Source authorization and available quantity are independent.
                available=D(qty)*D('.7')
                plan=evaluate_rotation(source=source,target=target,authorized_qty=qty,
                    verified_available_qty=available,balance_age_s=0,catalog=list(books),
                    quotes=books,now=NOW,usd_per_order_cap=cap,product_rules=rules(books),
                    fee_rate='.009',slippage_bps=15,max_legs=1)['routes'][0]
                self.assertEqual(len(plan['steps']),1)
                step=plan['steps'][0];bid,ask,_=books[step['pair']]
                rates={a:usd_conversion(a,books,now=NOW)['rate'] for a in (source,target,'USD')}
                budget=min(available,D(cap)/rates[source]);inc=D('.00000001')
                if step['side']=='BUY':
                    gross=(budget/(ask*D('1.0015')*D('1.009'))/inc).to_integral_value(rounding=ROUND_DOWN)*inc
                    spent=gross*ask*D('1.0015')*D('1.009');received=gross
                else:
                    gross=(budget/inc).to_integral_value(rounding=ROUND_DOWN)*inc
                    spent=gross;received=gross*bid*D('.9985')*D('.991')
                self.assertEqual(step['gross_base_quantity'],gross)
                self.assertEqual(step['input_quantity'],spent)
                self.assertEqual(step['output_quantity'],received)
                self.assertLessEqual(spent,available)
                self.assertLessEqual(step_input_usd(step,rates),D(cap))
                self.assertEqual(plan['residual_wallet_estimate'].get(source,D(0)),available-spent)
                expected=received*rates[target]-spent*rates[source]
                self.assertAlmostEqual(plan['immediate_change_usd'],expected,places=20)
                wallet=ShadowFIFOPortfolio({source:str(available)},rates)
                try:
                    wallet.post_hypothetical_route(session_id='SHADOW-SYNTHETIC-UNITS',
                        steps=plan['steps'],usd_rates=rates,at_utc=NOW)
                    self.assertTrue(wallet.quantity_parity())
                    self.assertAlmostEqual(wallet.mark_vs_hold(rates)['delta_usd'],expected,places=20)
                    # Fee is embedded in receipts. Never subtract it from delta again.
                    self.assertGreater(wallet.fees_estimated_usd,0)
                finally:wallet.close()
        self.assertEqual(usd_conversion('USDC',books,now=NOW)['rate'],D('.94'))

    def test_sell_budget_uses_base_units_and_strict_source_fx(self):
        books={'BTC-USD':(D('50000'),D('50001'),NOW)}
        idea=make_plan('BTC','USD','500',books=books,quantity='1')
        idea['observed_momentum_pct']=D('-2.4')
        self.assertEqual(step_input_usd(idea['shadow_fifo_steps'][0],{'BTC':'50000','USD':'1'}),D('500'))
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'BTC':'1'},fresh_usd_rates={'BTC':'50000'},now=NOW-1)
        try:
            cap=effective(dict(DEFAULT,per_order_usd='100',added_exposure_usd='100',daily_buy_usd='10000'),'50000')
            # A wrong display FX input must not let a $500 SELL pass a $100 limit.
            session.observe(now=NOW,quotes=books,usd_rates={'BTC':'1','USD':'1'},route_ideas=[idea],
                            minimum_advantage='.01',strict_quotes=True,risk_budgets=cap,approved_catalog=list(books))
            self.assertEqual(session.fifo_posted,0)
            self.assertEqual(session.rejected_budget,1)
        finally:
            for wallet in session.fifo_portfolios.values():wallet.close()

    def test_actual_receipts_rank_and_falling_base_direction(self):
        idea=make_plan()
        self.assertEqual(experimental_score(idea),
            idea['shadow_fifo_steps'][0]['output_usd_mark']*D('.024')+idea['immediate_change_usd'])
        nominal=dict(idea,research_size_cap_usd=D('1000000'))
        self.assertEqual(experimental_score(nominal),experimental_score(idea))
        falling=dict(idea,target='USD',observed_momentum_pct=D('-20'))
        self.assertEqual(target_momentum(falling),D('25'))
        self.assertIsNone(target_momentum(dict(falling,observed_momentum_pct=D('-100'))))
        poor=[dict(idea,source=f'A{i}',immediate_change_usd=D('-100')) for i in range(20)]
        best=dict(idea,source='ZZZ')
        self.assertIs(ranked_one_order_ideas(poor+[best],limit=6)[0],best)

    def test_attempt_counts_and_recycled_turnover_are_not_wallet_dollars(self):
        settings=dict(DEFAULT,attempts_24h='240',daily_buy_usd='2400',per_order_usd='10')
        for mode in ('MANUAL','FULL_AVAILABLE'):
            caps=effective(dict(settings,mode=mode),'15')
            self.assertEqual(caps['max_attempts'],'240')
            self.assertEqual(caps['daily_buy_usd'],'2400')
            self.assertLessEqual(D(caps['per_order_usd']),15)
        self.assertEqual(effective(DEFAULT,'1000')['max_attempts'],DEFAULT['attempts_24h'])


class SyntheticApprovalAndPlanner(unittest.TestCase):
    def test_valuation_only_excluded_holding_never_becomes_swap_candidate(self):
        selected=select_fast_books(['BLOCKED-USD','ETH-USD'],['ETH-USD'],['USD'],
            required_assets=['BLOCKED'],quotes={},now=NOW,
            valuation_catalog=['BLOCKED-USD','ETH-USD'])
        self.assertEqual(selected['targets'],[('ETH','ETH-USD')])
        self.assertEqual(selected['books'],['ETH-USD','BLOCKED-USD'])
        self.assertEqual(selected['candidate_routes'],1)

    def test_gpu_training_examples_only_read_current_approved_scope(self):
        from coincat_gpu_research import collect_two_way_examples
        with TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic-gpu.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE directional_trials (id INTEGER,pair TEXT,state TEXT,observed_at INTEGER,entry_bid TEXT,entry_ask TEXT,buy_net_pct TEXT,sell_rebuy_net_pct TEXT,fee_taker_at_entry TEXT,fee_source_at_entry TEXT)')
                for i,pair in enumerate(('BTC-USD','BLOCKED-USD')):
                    db.execute('INSERT INTO directional_trials VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (i,pair,'OBSERVED',NOW,'100','100.01','1','-1','.009','AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY'))
            self.assertEqual(len(collect_two_way_examples(path)),2)
            self.assertEqual(len(collect_two_way_examples(path,allowed_pairs=['BTC-USD'])),1)
            self.assertEqual(collect_two_way_examples(path,allowed_pairs=[]),[])

    def test_exclusions_restrictions_missing_rules_and_unlisted_products(self):
        catalog=['BTC-USD','ETH-BTC','SOL-USD','DOGE-USD','ADA-USD','USD-BTC']
        metadata=rules(catalog[:-1])
        metadata['ETH-BTC']['trading_disabled']=True
        metadata['SOL-USD']['status']='offline'
        metadata['ADA-USD'].pop('base_increment')
        self.assertEqual(approved_pairs(catalog,metadata,['DOGE']),['BTC-USD'])
        self.assertEqual(approved_pairs(catalog,metadata,['BTC','DOGE']),[])
        books={p:(D(1),D('1.0001'),NOW) for p in catalog}
        self.assertEqual(available_routes('USD','BTC',['BTC-USD'],books,now=NOW,max_legs=1),
                         [(('BTC-USD','BUY','USD','BTC'),)])
        self.assertEqual(available_routes('ETH','USD',['ETH-BTC','BTC-USD'],books,now=NOW,max_legs=1),[])

    def test_per_decision_context_parity_caching_and_new_event_invalidation(self):
        books={'BTC-USD':(D('100'),D('100.01'),NOW)}
        args=dict(source='USD',target='BTC',authorized_qty='100',verified_available_qty='100',
            balance_age_s=0,catalog=list(books),quotes=books,now=NOW,usd_per_order_cap='10',
            product_rules=rules(books),fee_rate='.009',max_legs=1)
        expected=evaluate_rotation(**args)
        with patch('coincat_multicurrency.usd_conversion',wraps=usd_conversion) as convert:
            ctx=RotationContext(args['catalog'],books,NOW)
            self.assertEqual(evaluate_rotation(**args,_context=ctx),expected)
            self.assertEqual(evaluate_rotation(**args,_context=ctx),expected)
            self.assertEqual(convert.call_count,2)  # USD and BTC once per decision.
        with self.assertRaises(TypeError):ctx.books['BTC-USD']=('1','1',NOW)
        with self.assertRaises(ValueError):evaluate_rotation(**dict(args,now=NOW+1),_context=ctx)
        newbooks={'BTC-USD':(D('120'),D('120.01'),NOW+1)}
        changed=evaluate_rotation(**dict(args,quotes=newbooks,now=NOW+1))
        self.assertNotEqual(changed['routes'][0]['destination_units_estimate'],expected['routes'][0]['destination_units_estimate'])
        self.assertEqual(evaluate_rotation(**dict(args,now=NOW+121))['routes'],[])

    def test_all_funding_ranked_before_clipping_and_budget_applied_before_sizing(self):
        # A public, deterministic fixture; no dependence on the external benchmark.
        sources=[f'F{i:02}' for i in range(9)]
        books={'BTC-USD':(D('100'),D('100.01'),NOW)}
        for i,asset in enumerate(sources):
            price=D(i+1)
            books[asset+'-USD']=(price,price*D('1.0001'),NOW)
            books['BTC-'+asset]=(D(100)/price,D('100.01')/price,NOW)
        evidence=Mock(return_value={'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0})
        args=dict(balances={s:'10' for s in sources},excluded=(),buy_signals=(),age_s=0,
            catalog=list(books),quotes=books,product_rules=rules(books),portfolio_usd_cap='1e9',
            now=NOW,fee_rates_by_pair={p:D('.009') for p in books},relative_evidence=evidence,
            exploratory_candidates=[{'pair':'BTC-USD','momentum_pct':D('2.4'),'action':'EXPLORE_ONLY'}],
            direct_only=True,experimental=True,urgent=True)
        all_fuel=shadow_screen(**args)
        self.assertEqual(all_fuel['ideas'][0]['source'],'F08')
        self.assertGreater(all_fuel['exploratory_viable_routes'],12)
        self.assertEqual(all_fuel['sell_first']['state'],'DEFERRED_BACKGROUND_ADVISORY')
        settings=dict(DEFAULT,per_order_usd='10',added_exposure_usd='10',daily_buy_usd='1000',attempts_24h='240')
        clipped=shadow_screen(**args,budget_settings=settings,budget_usage={'turnover_usd':'995','attempts':2})
        self.assertTrue(clipped['ideas'])
        self.assertLessEqual(max(i['research_size_cap_usd'] for i in clipped['ideas']),5)
        blocked=shadow_screen(**args,budget_settings=settings,budget_usage={'turnover_usd':'1000'})
        self.assertEqual(blocked['reason'],'SHADOW_BUDGET_TURNOVER_EXHAUSTED')
        self.assertEqual(blocked['ideas'],[])
        # Held-out evidence is queried once per source/target, not once per size.
        evidence.reset_mock()
        shadow_screen(**dict(args,buy_signals=[{'pair':'BTC-USD','action':'BUY','momentum_pct':'2.4'}]))
        self.assertEqual(evidence.call_count,len(sources))

    def test_batch_journal_equivalence_duplicates_and_atomic_bad_batch(self):
        with TemporaryDirectory() as folder:
            batch=ForwardStore(Path(folder)/'batch.sqlite');single=ForwardStore(Path(folder)/'single.sqlite')
            rows=[('BTC-USD',NOW,'100','100.01','synthetic'),
                  ('ETH-USD',NOW,'10','10.001','synthetic'),
                  ('BTC-USD',NOW+1,'101','101.01','synthetic')]
            self.assertEqual(batch.record_quotes(rows),3)
            self.assertEqual(batch.record_quotes(rows),0)
            for row in rows:single.record_quote(*row)
            for table in ('market_quotes','live_quote_summaries'):
                with batch._db() as b,single._db() as s:
                    self.assertEqual(b.execute(f'SELECT * FROM {table} ORDER BY 1,2,3').fetchall(),
                                     s.execute(f'SELECT * FROM {table} ORDER BY 1,2,3').fetchall())
            with self.assertRaises(ValueError):batch.record_quotes([rows[0],('BAD-USD',NOW,'NaN','2','synthetic')])
            with batch._db() as b:self.assertEqual(b.execute('SELECT COUNT(*) FROM market_quotes').fetchone()[0],3)


class SyntheticWholeChain(unittest.TestCase):
    def fixture(self,folder):
        clock=[float(NOW)]
        app=CoinCatApp.__new__(CoinCatApp)
        app.catalog=['BTC-USD','BLOCKED-USD','INVALID-USD']
        metadata=rules(app.catalog);metadata['INVALID-USD'].pop('base_increment')
        app.broker=NS(catalog_product_rules=metadata,submit=Mock(side_effect=AssertionError('NO REAL ORDERS')))
        app.current_balances={'USD':'1000'}
        app._last_portfolio_sync_monotonic=time.monotonic()
        app.external_mismatches=[]
        holdings=[{'asset':'USD','remaining_qty':'1000','enabled':1},
                  {'asset':'BLOCKED','remaining_qty':'0','enabled':0}]
        app.ledger=NS(assets=lambda:holdings)
        app.fee_learning=NS(latest_tier=lambda:{'fresh':True,'taker':D('.009')})
        app.stream_research=NS(rank_for_rest_scout=lambda catalog,**kw:[p for p in catalog if p=='BTC-USD'],
            snapshot=lambda **kw:{'rows':[{'pair':'BTC-USD','last_trade':clock[0],
                'age_ms':0,'change_30s_pct':D('2.4')}]})
        app._fast_candidate_signature=None;app._fast_candidate_signature_at=0
        app.experimental_shadow=ShadowArmedResearch(experimental=True)
        app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'USD':'1000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        self.addCleanup(lambda:[w.close() for w in app.experimental_shadow.fifo_portfolios.values()])
        app._experimental_model_balances={'USD':'1000'};app._experimental_excluded_assets=()
        app.shadow_pilot=NS(armed=False)
        app.relative_lab=NS(paired_outcomes=lambda *a,**kw:{'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0})
        app._manual_budget_saved=dict(DEFAULT,per_order_usd='10',daily_buy_usd='10000',
                                      added_exposure_usd='10',attempts_24h='1000')
        app.switch_minimum_usd=D('.10')
        app.forward=ForwardStore(Path(folder)/'synthetic-market.sqlite')
        app._shadow_valuation_books=lambda:app.forward.recent_bid_ask(now=clock[0],max_age=180)
        text=[];app.experimental_pnl_status=NS(set=text.append)
        fetch=Mock(side_effect=lambda pair,**kw:QuoteSnapshot(pair,D('100'),D('100.01'),clock[0],clock[0],1))
        return app,clock,text,fetch,holdings

    def test_twelve_decisions_in_hour_actual_producer_to_ram_fifo_to_pnl(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,holdings=self.fixture(folder)
            independent_loss=D(0)
            for event in range(12):
                clock[0]=NOW+event*300
                app._last_portfolio_sync_monotonic=time.monotonic()
                with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                    payload=app._fast_cycle()
                    self.assertEqual(payload['state'],'RESEARCHED',payload.get('reason'))
                    best=payload['plan']['ideas'][0];step=best['shadow_fifo_steps'][0]
                    self.assertEqual(len(best['shadow_fifo_steps']),1)
                    self.assertEqual(step['pair'],'BTC-USD')
                    independent_loss+=step['output_quantity']*100-step['input_quantity']
                    self.assertEqual(app._apply_fast_experimental(payload),1)
            snap=app.experimental_shadow.snapshot(now=clock[0])
            self.assertEqual(snap['modeled_conversions_last_hour'],12)
            self.assertEqual(snap['modeled_legs_last_hour'],12)
            self.assertEqual(snap['real_order_submissions'],0)
            self.assertEqual(snap['rolling_24h_model_attempts'],12)
            self.assertEqual(snap['last_mark_observed_at'],clock[0])
            value=snap['shadow_fifo_bands']['TAKER_ASK']
            self.assertAlmostEqual(D(value['counterfactual_portfolio_vs_hold_usd']),independent_loss,places=20)
            self.assertLess(independent_loss,0)  # Constant-price synthetic turnover loses costs.
            self.assertTrue(value['verified_quantity_parity'])
            self.assertIn('12/10 goal',text[-1]);self.assertIn('NO REAL P&L',text[-1])
            self.assertEqual({c.args[0] for c in fetch.call_args_list},{'BTC-USD'})
            app.broker.submit.assert_not_called()
            self.assertEqual(fast_funnel(planner=payload['plan'])['one_order_routes'],
                             payload['plan']['one_order_routes_evaluated'])
            # A quote observation cannot be recycled by the movement consumer.
            clock[0]+=.5
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]):
                self.assertEqual(app._apply_fast_experimental(payload),0)

    def test_late_exclusion_stale_payload_and_daily_limit_cannot_force_quota(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,holdings=self.fixture(folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                payload=app._fast_cycle()
                holdings.append({'asset':'BTC','enabled':0,'remaining_qty':'0'})
                self.assertEqual(app._apply_fast_experimental(payload),0)
                holdings.pop()
                clock[0]+=121
                self.assertEqual(app._apply_fast_experimental(payload),0)
                app._manual_budget_saved['attempts_24h']='1'
                app.experimental_shadow.rolling_model_attempts=[(clock[0],1)]
                stopped=app._fast_cycle()
                self.assertEqual(stopped['plan']['reason'],'SHADOW_ATTEMPT_LIMIT_REACHED')
                self.assertEqual(stopped['plan']['ideas'],[])
            self.assertEqual(app.experimental_shadow.fifo_posted,0)
            app.broker.submit.assert_not_called()

    def test_same_market_idempotency_independent_of_size_and_no_15minute_lock(self):
        books={'BTC-USD':(D('100'),D('100.01'),NOW)}
        idea=make_plan(books=books)
        self.assertEqual(decision_key(idea,books),decision_key(dict(idea,research_size_cap_usd=1),books))
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'USD':'1000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        try:
            for offset,stamp in ((0,NOW),(1,NOW),(2,NOW+2)):
                event_books={'BTC-USD':(D('100'),D('100.01'),stamp)}
                event=make_plan(now=NOW+offset,books=event_books)
                session.observe(now=NOW+offset,quotes=event_books,usd_rates={'BTC':'100','USD':'1'},
                    route_ideas=[event],strict_quotes=True,approved_catalog=['BTC-USD'])
            self.assertEqual(session.fifo_posted,2)
            self.assertGreater(session.duplicate_decisions,0)
            validated=ShadowArmedResearch()
            try:
                validated.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
                    enrolled_quantities={'USD':'1000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
                validated.observe(now=NOW,quotes=books,usd_rates={'BTC':'100','USD':'1'},route_ideas=[idea])
                self.assertEqual(validated.fifo_posted,0)
            finally:
                for w in validated.fifo_portfolios.values():w.close()
        finally:
            for w in session.fifo_portfolios.values():w.close()

    def test_completed_outcome_storage_does_not_stop_after_144_lifetime_routes(self):
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'USD':'5000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        try:
            for event in range(150):
                stamp=NOW+event*180
                books={'BTC-USD':(D('100'),D('100.01'),stamp)}
                idea=make_plan(now=stamp,books=books)
                session.observe(now=stamp,quotes=books,usd_rates={'BTC':'100','USD':'1'},
                    route_ideas=[idea],strict_quotes=True,approved_catalog=['BTC-USD'])
            self.assertEqual(session.fifo_posted,150)
            self.assertLess(len(session.entries),30)
            self.assertEqual(session.entry_sequence,150)
            self.assertTrue(session.fifo_portfolios['TAKER_ASK'].quantity_parity())
            self.assertGreater(session.experimental_horizons[3600]['matured'],100)
        finally:
            for w in session.fifo_portfolios.values():w.close()

    def test_missing_outcome_window_is_not_backfilled_with_a_later_gain(self):
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'USD':'1000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        try:
            books={'BTC-USD':(D('100'),D('100.01'),NOW)}
            session.observe(now=NOW,quotes=books,usd_rates={'BTC':'100','USD':'1'},
                route_ideas=[make_plan(books=books)],strict_quotes=True,approved_catalog=['BTC-USD'])
            session.observe(now=NOW+1000,quotes={},usd_rates={'BTC':'200','USD':'1'})
            self.assertEqual(session.experimental_horizons[300]['matured'],0)
            self.assertEqual(session.matured,0)
            self.assertEqual(session.entries[0]['experimental_future_marks'][300],'NOT_OBSERVED_IN_WINDOW')
            session.observe(now=NOW+4000,quotes={},usd_rates={})
            self.assertEqual(session.expired_outcome_entries,1)
            self.assertEqual(session.entries,[])
        finally:
            for w in session.fifo_portfolios.values():w.close()

    def test_fifo_replay_noop_does_not_increment_trades_or_hourly_count(self):
        session=ShadowArmedResearch(experimental=True)
        session.fifo_portfolios={'TAKER_ASK':NS(post_hypothetical_route=lambda **kw:
            {'state':'SHADOW_FIFO_REPLAY_NOOP','steps':0})}
        entry={'band':'TAKER_ASK','shadow_id':'SHADOW-SYNTHETIC-REPLAY','fifo_steps':[]}
        self.assertFalse(session._post_fifo(entry,{},NOW))
        self.assertEqual(session.fifo_posted,0)
        self.assertEqual(session.hourly_model_fills,[])


if __name__=='__main__':unittest.main()
