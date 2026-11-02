"""Fixed seven-market scope, ETH-only starts and truthful spot-workspace views."""
from contextlib import closing
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import time
import unittest
from unittest.mock import Mock,patch

from coincat_chart import read_history
from coincat_eth_maker import MakerConfig
from coincat_live_forward_store import ForwardStore
from coincat_monitor import capture,encode
from coincat_portfolio_view import PortfolioView
from coincat_simple_diagnostics import make_report
from coincat_watchlist import WATCH_PAIRS,eligible_watchlist,schedule_books
from coincat_working_allocation import AllocationRow
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_native_receipts import NOW
from offline_tests.test_v100_eth_growth import prepare


def network(folder):
    ledger,client,scanner=prepare(folder)
    template=deepcopy(scanner.rules['ADA-ETH'])
    for pair,price in zip(WATCH_PAIRS,('.000084','.02924','.00493','.04116','.000146','.001201','.00000245')):
        base,quote=pair.split('-')
        rule=dict(template,product_id=pair,base_currency_id=base,quote_currency_id=quote,
            price_increment='.000000001',base_increment='.00000001',quote_increment='.0000000001')
        client.rules[pair]=rule;client.q[pair]=(D(price),D(price)*D('1.0001'),NOW)
    client.rules['DOGE-ETH']=dict(template,product_id='DOGE-ETH');client.q['DOGE-ETH']=client.q['ADA-ETH']
    scanner.refresh(now=NOW,force_catalog=True)
    return ledger,client,scanner


class FixedMarketNetwork(unittest.TestCase):
    def test_all_seven_are_covered_in_two_six_book_passes_without_other_products(self):
        books=[]
        for i in range(3):
            selected,deferred=schedule_books(WATCH_PAIRS,i)
            self.assertEqual(len(selected),6);self.assertEqual(len(deferred),1)
            self.assertTrue(set(WATCH_PAIRS[:4]).issubset(selected));books.append(set(selected))
        self.assertEqual(books[0]|books[1],set(WATCH_PAIRS));self.assertNotEqual(books[0],books[1])
        selected,_=schedule_books((*WATCH_PAIRS,'DOGE-ETH'),0)
        self.assertNotIn('DOGE-ETH',selected)

    def test_actual_authentication_rules_and_exclusions_still_gate_each_market(self):
        with TemporaryDirectory() as folder:
            _,_,scanner=network(folder)
            eligible,rejects=eligible_watchlist(scanner.catalog,scanner.rules)
            self.assertEqual(eligible,WATCH_PAIRS);self.assertFalse(rejects)
            scanner.rules['LINK-BTC']['view_only']=True
            eligible,rejects=eligible_watchlist(scanner.catalog,scanner.rules,('ADA',))
            self.assertNotIn('LINK-BTC',eligible);self.assertEqual(rejects['LINK-BTC'],'ACCOUNT_TRADABILITY_UNVERIFIED')
            self.assertNotIn('ADA-BTC',eligible);self.assertNotIn('ADA-ETH',eligible)
            self.assertEqual(rejects['ADA-BTC'],'EXCLUDED')

    def test_eth_only_wallet_models_four_entries_and_observes_btc_links_without_fake_inventory(self):
        with TemporaryDirectory() as folder:
            ledger,client,scanner=network(folder);before=fixtures.ledger_dump(ledger)
            self.assertEqual(scanner.balances,{'ETH':D(2)});self.assertNotIn('DOGE-ETH',scanner.catalog)
            config=MakerConfig(('BTC','ADA','LINK','SOL'),D('.1'),observe_watchlist=True)
            seen=set();snapshots=[]
            for i in range(3):
                collect=Mock(side_effect=fixtures.collector(client,at=NOW+i))
                result=scanner.scan_growth(config,now=NOW+i,collect=collect,allocation_draft=(AllocationRow('ETH',D(2)),))
                requested=collect.call_args.args[0];seen.update(requested)
                self.assertLessEqual(len(requested),6);self.assertTrue(set(requested).issubset(WATCH_PAIRS))
                self.assertEqual(len(result['rows']),4);self.assertEqual(result['study_counts']['setups'],4)
                self.assertEqual(result['orders_submitted'],0);self.assertFalse(result['live_order_permission'])
                for row in result['rows']:
                    self.assertIsNotNone(row['hypothesis']);self.assertIsNone(row['actual_profit_eth'])
                for row in result['watched_markets']:
                    if row['pair'] in WATCH_PAIRS[4:]:self.assertEqual(row['mode'],'OBSERVE_ONLY')
                snapshots.append(result)
            self.assertEqual(seen,set(WATCH_PAIRS));self.assertEqual(scanner.balances,{'ETH':D(2)})
            self.assertEqual(before,fixtures.ledger_dump(ledger))
            with closing(sqlite3.connect(scanner.market_store.path)) as db:
                self.assertEqual({p[0] for p in db.execute('SELECT DISTINCT pair FROM market_quotes')},set(WATCH_PAIRS))
            first_deferred=snapshots[0]['quote_scheduling']['deferred_markets'][0]
            first=next(r for r in snapshots[0]['watched_markets'] if r['pair']==first_deferred)
            self.assertIsNone(first['book']);self.assertTrue(first['deferred'])

    def test_cancelled_pass_does_not_advance_rotation_or_publish_watch_cache(self):
        import threading
        with TemporaryDirectory() as folder:
            _,client,scanner=network(folder);cancel=threading.Event()
            def collect(pairs,**kwargs):
                result=fixtures.collector(client)(pairs,**kwargs);cancel.set();return result
            result=scanner.scan_growth(MakerConfig(('ADA',),D('.1'),observe_watchlist=True),now=NOW,
                cancel=cancel,collect=collect,allocation_draft=(AllocationRow('ETH',D(2)),))
            self.assertEqual(result['state'],'CANCELLED');self.assertEqual(scanner.sequence,0)
            self.assertEqual(scanner.watch_books,{})

    def test_failed_cross_fetch_keeps_old_timestamp_with_explicit_gap_reason(self):
        from coincat_v701_transport import QuoteErrors
        with TemporaryDirectory() as folder:
            _,client,scanner=network(folder)
            config=MakerConfig(('BTC','ADA','LINK','SOL'),D('.1'),observe_watchlist=True)
            scanner.scan_growth(config,now=NOW,collect=fixtures.collector(client),allocation_draft=(AllocationRow('ETH',D(2)),))
            def partial(pairs,**kwargs):
                books,_,elapsed=fixtures.collector(client,at=NOW+1)(pairs,**kwargs)
                books.pop('SOL-BTC');errors=QuoteErrors();errors['ConnectionError']=1
                errors.by_product={'SOL-BTC':'ConnectionError'}
                return books,errors,elapsed
            result=scanner.scan_growth(config,now=NOW+1,collect=partial,allocation_draft=(AllocationRow('ETH',D(2)),))
            cross=next(row for row in result['watched_markets'] if row['pair']=='SOL-BTC')
            self.assertEqual(cross['reason'],'CONNECTION_ERROR');self.assertEqual(cross['book'][2],NOW)
            self.assertEqual(result['study_counts']['setups'],4)
            self.assertTrue(all(row['current_estimate_available'] for row in result['rows']))


class WatchedBasketReference(unittest.TestCase):
    def test_eth_only_start_needs_no_companion_holdings_or_companion_purchase(self):
        view=PortfolioView();result=view.measure({'ETH':D('.077'),'USD':D(20),'VET':D(3)},NOW,{},NOW)
        self.assertEqual(result['watched_value_eth'],D('.077'));self.assertEqual(result['change_eth'],0)
        self.assertEqual(result['outside_assets'],('USD','VET'));self.assertEqual(result['missing_assets'],())
        self.assertEqual(result['trading_profit'],'UNVERIFIED');self.assertFalse(result['flow_adjusted'])

    def test_inverse_btc_valuation_and_price_changes_are_reference_value_not_bot_profit(self):
        balances={'ETH':D(2),'BTC':D('.1'),'ADA':D(100)}
        books={'ETH-BTC':(D('.05'),D('.05'),NOW),'ADA-ETH':(D('.01'),D('.01'),NOW)}
        view=PortfolioView();initial=view.measure(balances,NOW,books,NOW)
        self.assertEqual(initial['watched_value_eth'],D(5))
        books['ADA-ETH']=(D('.02'),D('.02'),NOW+1)
        later=view.measure(balances,NOW,books,NOW+1)
        self.assertEqual(later['change_eth'],D(1));self.assertEqual(later['trading_profit'],'UNVERIFIED')
        balances['ETH']=D(3)
        deposit=view.measure(balances,NOW,books,NOW+1)
        self.assertEqual(deposit['change_eth'],D(2));self.assertFalse(deposit['flow_adjusted'])

    def test_missing_stale_or_wide_quotes_and_stale_accounts_do_not_create_complete_totals(self):
        for books,now in (({},NOW),({'ETH-BTC':(D(1),D(2),NOW)},NOW),
                ({'ETH-BTC':(D(1),D(1),NOW)},NOW+31)):
            result=PortfolioView().measure({'ETH':D(2),'BTC':D(1)},NOW,books,now)
            self.assertIsNone(result['watched_value_eth']);self.assertIsNone(result['change_eth'])
        result=PortfolioView().measure({'ETH':D(2)},NOW,{},NOW+121)
        self.assertIsNone(result['eth_held']);self.assertIsNone(result['watched_value_eth'])


class ScopedNativeCharts(unittest.TestCase):
    def test_native_eth_btc_and_btc_cross_candles_match_product_units_and_hide_other_history(self):
        with TemporaryDirectory() as folder:
            store=ForwardStore(Path(folder)/'quotes.sqlite3');at=int(time.time())-30
            store.record_quotes([('ETH-BTC',at,'.03','.03','TEST'),('ADA-BTC',at,'.000002','.000002','TEST'),
                ('DOGE-ETH',at,'.01','.01','TEST')])
            native=read_history(store.path,'ETH-BTC',span='All stored',allowed_products=WATCH_PAIRS,native=True)
            self.assertAlmostEqual(native['candles'][0]['close'],.03);self.assertEqual(native['price_unit'],'BTC_PER_ETH')
            self.assertNotIn('DOGE-ETH',native['products'])
            cross=read_history(store.path,'ADA-BTC',span='All stored',allowed_products=WATCH_PAIRS,native=True)
            self.assertAlmostEqual(cross['candles'][0]['close'],.000002);self.assertEqual(cross['price_unit'],'BTC_PER_ADA')
            with patch('coincat_chart.sqlite3.connect') as connect:
                result=read_history(store.path,'DOGE-ETH',allowed_products=WATCH_PAIRS,native=True)
                self.assertEqual(result['state'],'OUTSIDE_APPROVED_WATCHLIST');connect.assert_not_called()


class SpotWorkspaceGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def test_chart_left_controls_right_and_activity_below_fit_minimum_window(self):
        app=self.app;self.root.geometry('1040x780');self.root.update()
        self.assertEqual(len(app.tabs.tabs()),4);self.assertEqual(len(app.activity_tabs.tabs()),4)
        self.assertEqual(len(app.companions),4);self.assertEqual(set(app.watch_tree.get_children()),set(WATCH_PAIRS))
        self.assertGreater(app.funding_label.winfo_rootx(),app.chart.winfo_rootx()+app.chart.winfo_width())
        self.assertGreater(app.growth_tree.winfo_rooty(),app.chart.winfo_rooty())
        self.assertLessEqual(app.chart.winfo_rootx()+app.chart.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
        self.assertEqual(app.orders_tree.get_children(),())
        self.assertIn('Verified bot fills 0',app.counter_text.get())
        self.assertLessEqual(app.counter_label.winfo_rooty()+app.counter_label.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(set(app.chart.product['values']).issubset(WATCH_PAIRS))

    def test_baseline_reset_and_chart_selection_do_not_change_applied_eth_plan_or_ledger(self):
        app=self.app;ledger,client,scanner=network(self.temp.name);app.scanner=scanner;app.connected=True
        app.allocation_editor.clock=lambda:NOW;app._render_wallet();app.companions[0].set('ADA')
        app.mixer.controls['amount_eth'].set('.1');app._apply_plan()
        result=scanner.scan_growth(app.applied_config,now=NOW,collect=fixtures.collector(client),allocation_draft=(AllocationRow('ETH',D(2)),))
        app.last_result=result;app._render(result);config=app.applied_config;generation=app.generation
        before=fixtures.ledger_dump(ledger)
        with patch('coincat_app.time.time',return_value=NOW):
            app._reset_view_baseline();self.assertEqual(app.basket_change_text.get(),'+0 ETH')
            app.watch_tree.selection_set('ADA-BTC');app._select_watch()
        self.assertEqual(app.chart.pair.get(),'ADA-BTC');self.assertIs(app.applied_config,config)
        self.assertEqual(app.generation,generation);self.assertEqual(before,fixtures.ledger_dump(ledger))
        app._update_market_view(NOW);self.assertIn('Stopped',app.watch_tree.set('ADA-ETH','status'))
        accepted_value=app.basket_text.get();scanner.balances['ETH']=D(3)
        app._update_market_view(NOW)
        self.assertEqual(app.basket_text.get(),accepted_value)  # Unpublished worker state is not a new GUI snapshot.
        app.recovery.state='RETRYING';app._update_market_view(NOW)
        self.assertIn('Paused',app.watch_tree.set('ADA-ETH','status'))

    def test_four_eth_scenarios_fit_helper_and_diagnostics_redact_reference_quantities(self):
        app=self.app;_,client,scanner=network(self.temp.name);app.scanner=scanner
        config=MakerConfig(('BTC','ADA','LINK','SOL'),D('.1'),observe_watchlist=True)
        app.last_result=scanner.scan_growth(config,now=NOW,collect=fixtures.collector(client),allocation_draft=(AllocationRow('ETH',D(2)),))
        for variable,asset in zip(app.companions,config.companions):
            # Avoid GUI invalidation clearing the staged synthetic result.
            variable.set(asset)
        app.last_result=scanner.last_result
        snap=capture(app,session='a'*32,sequence=1,now=NOW)
        self.assertEqual(len(snap['products']),4);encode(snap)
        app.portfolio_result={'watched_value_eth':D('9876543.210987654321'),'change_eth':D('9876543.210987654321')}
        report=make_report(app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report);self.assertIn('ADA-BTC',report)
        self.assertNotIn('9876543.210987654321',report);self.assertNotIn('9876543.210987654321',str(snap))
