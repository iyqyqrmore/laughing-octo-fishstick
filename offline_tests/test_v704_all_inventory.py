"""Synthetic full-inventory and immediate-reuse regressions; no exchange IO.

Small native positions are never removed for a wallet-size cutoff. Market
minimums, exclusions, explicit spend limits and the live block still apply.
"""
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest

from coincat_app import CoinCatApp
from coincat_v507_shadow_arm import ShadowArmedResearch
from coincat_v6018_fast_path import select_fast_books
from coincat_v605_shadow_bridge import shadow_screen
from coincat_v701_transport import QuoteSnapshot, QuoteDeferred
from coincat_v701_quotes import mark_coverage
from coincat_v703_chain import experimental_score
from offline_tests import test_v703_chain_contract as fixtures

NOW=fixtures.NOW


class AllInventory(unittest.TestCase):
    def test_every_positive_native_position_is_considered_without_dollar_cutoff(self):
        app=CoinCatApp.__new__(CoinCatApp)
        rows=[{'asset':f'F{i:02}','remaining_qty':'0.00000001','enabled':1} for i in range(40)]
        rows += [{'asset':'BLOCKED','remaining_qty':'10','enabled':0},
                 {'asset':'LOCKED','remaining_qty':'10','enabled':1},
                 {'asset':'ZERO','remaining_qty':'0','enabled':1},
                 {'asset':'INVALID','remaining_qty':'NaN','enabled':1}]
        app.ledger=NS(assets=lambda:rows)
        app.current_balances={r['asset']:r['remaining_qty'] for r in rows}
        app.current_balances['LOCKED']='0'
        app.experimental_shadow=NS(armed=False);app.shadow_pilot=NS(armed=False)
        app.catalog=[r['asset']+'-USD' for r in rows]
        app.broker=NS(catalog_product_rules=fixtures.rules(app.catalog))
        sources,signature=app._funding_sources()
        expected={f'F{i:02}' for i in range(40)}
        self.assertEqual(sources,expected)
        self.assertEqual(len(signature[0][1]),40)
        self.assertEqual(set(app._research_catalog(fundable=True)),{a+'-USD' for a in expected})

    def test_quote_rotation_reaches_every_funder_with_bounded_requests(self):
        funding={f'F{i:02}' for i in range(25)}
        mark_pairs=[a+'-USD' for a in sorted(funding)]+['BTC-USD']
        trade_pairs={'BTC-'+a for a in funding}
        catalog=mark_pairs+sorted(trade_pairs)
        quotes={p:(D(1),D('1.0001'),NOW) for p in mark_pairs}
        cursor=0;seen=set()
        for _ in range(3):
            plan=select_fast_books(['BTC-USD'],catalog,funding,quotes=quotes,now=NOW,route_cursor=cursor)
            self.assertEqual(plan['funding_assets'],25)
            self.assertEqual(plan['candidate_routes'],25)
            self.assertLessEqual(len(plan['books']),16)
            seen.update(set(plan['books'])&trade_pairs)
            cursor=plan['next_route_cursor']
        self.assertEqual(seen,trade_pairs)
        # Fresh books are reused without repeatedly consuming all 16 slots.
        quotes.update({p:(D(1),D('1.0001'),NOW) for p in trade_pairs})
        cached=select_fast_books(['BTC-USD'],catalog,funding,quotes=quotes,now=NOW+1,route_cursor=cursor)
        self.assertEqual(cached['books'],['BTC-USD'])
        self.assertEqual(cached['funding_routes_deferred'],0)

    def test_excluded_balance_cannot_reappear_as_bridge_destination(self):
        books={'BTC-USD':(D('100'),D('100.01'),NOW)}
        plan=shadow_screen(balances={'USD':'10','BTC':'.001'},excluded=['BTC'],buy_signals=(),
            age_s=0,catalog=list(books),quotes=books,product_rules=fixtures.rules(books),
            portfolio_usd_cap='10',now=NOW,fee_rates_by_pair={'BTC-USD':D('.009')},
            relative_evidence=None,exploratory_candidates=[{'pair':'BTC-USD','momentum_pct':'2.4'}],
            direct_only=True,experimental=True,urgent=True)
        self.assertEqual(plan['ideas'],[])


class SmallWalletAndReuse(unittest.TestCase):
    def app(self,folder):
        # Use the preceding release's actual producer/consumer fixture; all
        # temporary-wallet cleanup hooks are registered on this test instance.
        return fixtures.SyntheticWholeChain.fixture(self,folder)

    def test_small_wallet_can_buy_then_use_new_coin_on_the_next_decision(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=self.app(folder)
            app.current_balances={'USD':'1.25'};rows[0]['remaining_qty']='1.25'
            app.experimental_shadow.disarm(now=NOW-1)
            app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,
                verified_balances=True,usd_coverage=True,enrolled_quantities={'USD':'1.25'},
                fresh_usd_rates={'USD':'1'},now=NOW-1)
            app._experimental_model_balances={'USD':'1.25'}
            app.catalog=['BTC-USD','ETH-BTC']
            app.broker.catalog_product_rules=fixtures.rules(app.catalog)
            app.broker.catalog_product_rules['BTC-USD']['quote_min_size']='1'
            target=['BTC-USD']
            app.stream_research=NS(rank_for_rest_scout=lambda catalog,**kw:[target[0]] if target[0] in catalog else [],
                snapshot=lambda **kw:{'rows':[{'pair':target[0],'last_trade':100,'age_ms':0,'change_30s_pct':D('2.4')}]})
            prices={'BTC-USD':(D('100'),D('100.01')),'ETH-BTC':(D('.001'),D('.0010001'))}
            fetch=Mock(side_effect=lambda pair,**kw:QuoteSnapshot(pair,*prices[pair],clock[0],clock[0],1))
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                first=app._fast_cycle()
                best=first['plan']['ideas'][0]
                self.assertEqual(best['source'],'USD')
                self.assertGreater(experimental_score(best),0)
                self.assertLess(experimental_score(best),D('.10'))
                self.assertEqual(app._apply_fast_experimental(first),1)
                acquired=app.experimental_shadow.model_balances()['BTC']
                self.assertGreater(acquired,0)
                self.assertNotIn('BTC',app.current_balances)  # Original real account is separate.
                target[0]='ETH-BTC';clock[0]+=1
                next_plan=app._fast_cycle()
                self.assertEqual(next_plan['state'],'RESEARCHED',next_plan.get('reason'))
                follow=next_plan['plan']['ideas'][0]
                self.assertEqual((follow['source'],follow['target']),('BTC','ETH'))
                self.assertLessEqual(follow['input_units_planned'],acquired)
                self.assertEqual(len(follow['shadow_fifo_steps']),1)
                self.assertEqual(app._apply_fast_experimental(next_plan),1)
            self.assertGreater(app.experimental_shadow.model_balances()['ETH'],0)
            self.assertEqual(app.experimental_shadow.fifo_posted,2)
            self.assertTrue(app.experimental_shadow.fifo_portfolios['TAKER_ASK'].quantity_parity())
            self.assertEqual([r['asset'] for r in rows],['USD','BLOCKED'])
            app.broker.submit.assert_not_called()

    def test_validated_manual_dollar_floor_is_preserved(self):
        session=ShadowArmedResearch()
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'USD':'2'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        try:
            idea=fixtures.make_plan(quantity='2',cap='1.25')
            idea.update(oos_validated=True,research_decision='SWITCH_WORTH_RESEARCH',net_p10_usd=D('.05'))
            session.observe(now=NOW,quotes={'BTC-USD':(D('100'),D('100.01'),NOW)},
                usd_rates={'USD':'1','BTC':'100'},route_ideas=[idea],minimum_advantage='.10',strict_quotes=True)
            self.assertEqual(session.fifo_posted,0)
            session.observe(now=NOW+1,quotes={'BTC-USD':(D('100'),D('100.01'),NOW+1)},
                usd_rates={'USD':'1','BTC':'100'},route_ideas=[idea],minimum_advantage='.01',strict_quotes=True)
            self.assertEqual(session.fifo_posted,1)
        finally:
            for wallet in session.fifo_portfolios.values():wallet.close()

    def test_small_wallet_still_obeys_exchange_minimum_and_explicit_turnover(self):
        for qty,turnover in (('.75','100'),('1.25','.50')):
            with self.subTest(qty=qty,turnover=turnover),TemporaryDirectory() as folder:
                app,clock,text,fetch,rows=self.app(folder)
                app.current_balances={'USD':qty};rows[0]['remaining_qty']=qty
                app.experimental_shadow.disarm(now=NOW-1)
                app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,
                    verified_balances=True,usd_coverage=True,enrolled_quantities={'USD':qty},
                    fresh_usd_rates={'USD':'1'},now=NOW-1)
                app._experimental_model_balances={'USD':qty}
                app._manual_budget_saved['daily_buy_usd']=turnover
                app.broker.catalog_product_rules['BTC-USD']['quote_min_size']='1'
                with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                    plan=app._fast_cycle()
                    self.assertEqual(plan['plan']['funding_assets'],1)
                    self.assertEqual(plan['plan']['ideas'],[])
                    self.assertEqual(app._apply_fast_experimental(plan),0)
                app.broker.submit.assert_not_called()

    def test_nonpositive_score_cannot_be_forced_by_small_wallet_policy(self):
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'USD':'2'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        try:
            for offset in (0,1):
                stamp=NOW+offset;books={'BTC-USD':(D('100'),D('100.01'),stamp)}
                idea=fixtures.make_plan(quantity='2',cap='1',now=stamp,books=books)
                # Construct an exactly zero or strictly negative provisional score.
                idea['immediate_change_usd']=-idea['shadow_fifo_steps'][0]['output_usd_mark']*D('.024')
                if offset:idea['immediate_change_usd']-=1
                self.assertLessEqual(experimental_score(idea),0)
                session.observe(now=stamp,quotes=books,usd_rates={'USD':'1','BTC':'100'},
                    route_ideas=[idea],minimum_advantage='0',strict_quotes=True)
            self.assertEqual(session.fifo_posted,0)
        finally:
            for wallet in session.fifo_portfolios.values():wallet.close()

    def test_wallet_update_bypasses_unchanged_stream_cooldown_but_idle_replay_does_not(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=self.app(folder)
            app.stream_research.snapshot=lambda **kw:{'rows':[{'pair':'BTC-USD','last_trade':100,
                'age_ms':0,'change_30s_pct':D('2.4')}]}
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                first=app._fast_cycle()
                self.assertEqual(app._apply_fast_experimental(first),1)
                clock[0]+=1
                follow=app._fast_cycle()
                self.assertEqual(follow['state'],'RESEARCHED',follow.get('reason'))
                clock[0]+=1
                unchanged=app._fast_cycle()
                self.assertEqual(unchanged['reason'],'STREAM_PRICES_UNCHANGED_COOLDOWN')

    def test_validated_wallet_new_asset_is_scouted_without_original_currency_bridge(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=self.app(folder)
            app.experimental_shadow.disarm()
            app.shadow_pilot=NS(armed=True,fifo_portfolios={},daily_model_buys=[],rolling_model_attempts=[])
            app._shadow_model_balances={'ALT':'2'};app._shadow_excluded_assets=()
            app.catalog=['ALT-USD','ETH-ALT']
            app.broker.catalog_product_rules=fixtures.rules(app.catalog)
            app.stream_research=NS(rank_for_rest_scout=lambda catalog,**kw:['ETH-ALT'] if 'ETH-ALT' in catalog else [],
                snapshot=lambda **kw:{'rows':[{'pair':'ETH-ALT','last_trade':1,'age_ms':0,'change_30s_pct':D('2.4')}]})
            prices={'ALT-USD':(D('5'),D('5.0001')),'ETH-ALT':(D(1),D('1.0001'))}
            fetch=Mock(side_effect=lambda pair,**kw:QuoteSnapshot(pair,*prices[pair],clock[0],clock[0],1))
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                result=app._fast_cycle()
            self.assertEqual(result['state'],'RESEARCHED',result.get('reason'))
            self.assertEqual(result['scope']['funding_assets_considered'],1)
            self.assertEqual(result['validated_plan']['funding_inventory_usd'],D(10))
            self.assertEqual({i['source'] for i in result['validated_plan']['ideas']},{'ALT'})
            self.assertEqual(app._funding_sources()[0],{'ALT'})
            self.assertFalse(result['live_order_permission'])

    def test_unrelated_missing_marks_do_not_block_priced_route_or_fake_whole_wallet_pnl(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=self.app(folder)
            extra={f'F{i:02}':'1' for i in range(21)}
            starting={'USD':'1000',**extra}
            app.experimental_shadow.disarm(now=NOW-1)
            app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,
                verified_balances=True,usd_coverage=True,enrolled_quantities=starting,
                fresh_usd_rates={a:'1' for a in starting},now=NOW-1)
            app._experimental_model_balances=dict(starting)
            app.current_balances=dict(starting)
            rows.extend({'asset':a,'remaining_qty':q,'enabled':1} for a,q in extra.items())
            app.catalog=['BTC-USD']+[a+'-USD' for a in extra]
            app.broker.catalog_product_rules=fixtures.rules(app.catalog)
            def quote(pair,**kw):
                if pair=='F05-USD':raise QuoteDeferred('SYNTHETIC_MISSING_MARK')
                bid=D('100') if pair=='BTC-USD' else D(1)
                return QuoteSnapshot(pair,bid,bid*D('1.0001'),clock[0],clock[0],1)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',side_effect=quote):
                payload=app._fast_cycle()
                self.assertEqual(payload['state'],'RESEARCHED',payload.get('reason'))
                self.assertEqual(payload['scope']['funding_assets_considered'],22)
                self.assertLessEqual(payload['book_requests'],16)
                self.assertFalse(payload['mark_coverage']['complete'])
                self.assertTrue(payload['plan']['funding_partial'])
                with patch('coincat_app.mark_coverage',wraps=mark_coverage) as marks:
                    self.assertEqual(app._apply_fast_experimental(payload),1)
                    self.assertEqual(sum(bool(c.kwargs.get('required_pairs')) for c in marks.call_args_list),1)
                snap=app.experimental_shadow.snapshot(now=clock[0])
                self.assertFalse(snap['whole_wallet_marks_complete'])
                self.assertTrue(snap['shadow_fifo_bands']['TAKER_ASK']['counterfactual_portfolio_vs_hold_usd'].startswith('NOT VERIFIED'))
                self.assertIn('NOT VERIFIED',text[-1])
                for asset in extra:self.assertEqual(app.experimental_shadow.model_balances()[asset],1)
                # Later complete, simultaneous marks restore an honest full P&L.
                clock[0]+=1
                app.forward.record_quotes([(a+'-USD',clock[0],'2','2.0002','synthetic') for a in extra])
                current=dict(payload,state='RESEARCHED',plan=dict(payload['plan'],ideas=[]),
                    experimental_model_snapshot=app._experimental_model_balances.copy(),
                    decision_quotes=app._shadow_valuation_books())
                self.assertEqual(app._apply_fast_experimental(current),0)
                snap=app.experimental_shadow.snapshot(now=clock[0])
                self.assertTrue(snap['whole_wallet_marks_complete'])
                value=D(snap['shadow_fifo_bands']['TAKER_ASK']['counterfactual_portfolio_vs_hold_usd'])
                step=payload['plan']['ideas'][0]['shadow_fifo_steps'][0]
                self.assertAlmostEqual(value,step['output_quantity']*100-step['input_quantity'],places=20)
                self.assertTrue(snap['shadow_fifo_bands']['TAKER_ASK']['verified_quantity_parity'])
            app.broker.submit.assert_not_called()

    def test_partial_marks_cannot_verify_asynchronous_pnl_or_mature_outcomes(self):
        session=ShadowArmedResearch(experimental=True)
        session.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'BTC':'1'},fresh_usd_rates={'BTC':'100'},now=NOW-1)
        try:
            books={'BTC-USD':(D('100'),D('100.01'),NOW),
                   'ETH-USD':(D('10'),D('10.001'),NOW),'BTC-ETH':(D('10'),D('10.001'),NOW)}
            idea=fixtures.make_plan('BTC','ETH',cap='10',quantity='1',books=books)
            session.observe(now=NOW,quotes=books,usd_rates={'BTC':'100','ETH':'10','USD':'1'},
                route_ideas=[idea],strict_quotes=True)
            self.assertEqual(session.fifo_posted,1)
            later={'BTC-USD':(D('100'),D('100.01'),NOW+281),
                   'ETH-USD':(D('10'),D('10.001'),NOW+301),
                   'BTC-ETH':(D('10'),D('10.001'),NOW+301)}
            app=CoinCatApp.__new__(CoinCatApp)
            rates,complete=app._shadow_mark_rates(session,later,NOW+301,allow_partial=True)
            self.assertFalse(complete)
            self.assertTrue({'BTC','ETH','USD'}<=set(rates))
            session.observe(now=NOW+301,quotes=later,usd_rates=rates,portfolio_marks_complete=complete)
            snap=session.snapshot(now=NOW+301)
            self.assertEqual(snap['marked_counterfactuals'],0)
            self.assertEqual(snap['experimental_forward_horizons']['300']['matured'],0)
            self.assertEqual(snap['shadow_fifo_bands']['TAKER_ASK']['counterfactual_portfolio_vs_hold_usd'],
                             'NOT VERIFIED - FX SNAPSHOT UNSYNCHRONIZED')
        finally:
            for wallet in session.fifo_portfolios.values():wallet.close()

    def test_route_book_must_be_synchronized_with_its_usd_fx_even_if_fx_agree(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=self.app(folder)
            app.experimental_shadow.disarm(now=NOW-1)
            app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,
                verified_balances=True,usd_coverage=True,enrolled_quantities={'BTC':'1'},
                fresh_usd_rates={'BTC':'100'},now=NOW-1)
            app._experimental_model_balances={'BTC':'1'}
            rows[0].update(asset='BTC',remaining_qty='1');app.current_balances={'BTC':'1'}
            app.catalog=['BTC-USD','ETH-USD','BTC-ETH']
            app.broker.catalog_product_rules=fixtures.rules(app.catalog)
            books={'BTC-USD':(D('100'),D('100.01'),NOW),
                   'ETH-USD':(D('10'),D('10.001'),NOW),
                   'BTC-ETH':(D('10'),D('10.001'),NOW+20)}
            idea=fixtures.make_plan('BTC','ETH',cap='10',quantity='1',now=NOW+20,books=books)
            self.assertGreater(experimental_score(idea),0)
            clock[0]=NOW+20
            payload=dict(state='RESEARCHED',plan={'ideas':[idea],'funding_inventory_usd':'100'},
                experimental_model_snapshot={'BTC':'1'},decision_quotes=books)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]):
                self.assertEqual(app._apply_fast_experimental(payload),0)
            self.assertEqual(app.experimental_shadow.model_balances(),{'BTC':D(1)})


if __name__=='__main__':unittest.main()
