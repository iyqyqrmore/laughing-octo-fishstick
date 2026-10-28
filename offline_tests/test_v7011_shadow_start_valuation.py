"""Synthetic shadow-start regressions; no account, file-backed ledger or HTTP."""
from decimal import Decimal as D
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import time
import unittest

from coincat_app import CoinCatApp
from coincat_portfolio_prices import portfolio_coverage
from coincat_v6018_fast_path import fast_candidates, select_fast_books
from coincat_v701_quotes import newest_books, mark_coverage
from coincat_v701_transport import QuoteSnapshot


class ShadowStartValuation(unittest.TestCase):
    def app(self):
        app=CoinCatApp.__new__(CoinCatApp)
        app.broker=NS(armed=False)
        app._last_portfolio_sync_monotonic=time.monotonic()
        app.current_balances={'ALT':D(1),'USD':D(10)}
        app.catalog=['ALT-USD'];app.external_mismatches=[]
        app.ledger=NS(setting=lambda *a:'0',assets=lambda:[
            {'asset':a,'remaining_qty':str(q),'enabled':1} for a,q in app.current_balances.items()])
        app._portfolio_quotes={'ALT-USD':(D(100),D(101),time.time())}
        app.forward=NS(recent_bid_ask=lambda **kw:{})
        app.experimental_shadow=NS(armed=False,arm=Mock(),model_balances=lambda:dict(app.current_balances))
        app.shadow_pilot=NS(armed=False,arm=Mock(),model_balances=lambda:dict(app.current_balances))
        for name in ('experimental_shadow_button','experimental_shadow_status',
                     'shadow_mode_button','shadow_mode_status'):
            setattr(app,name,Mock())
        return app

    def test_display_priced_holding_is_not_lost_by_shadow_merger(self):
        app=self.app()
        self.assertTrue(portfolio_coverage(app.current_balances,app.catalog,app._portfolio_quotes)['complete'])
        books=app._shadow_valuation_books()
        self.assertTrue(portfolio_coverage(app.current_balances,app.catalog,books)['complete'])

    def test_explicit_experimental_start_keeps_valued_wide_holdings(self):
        app=self.app()
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_experimental_shadow()
        warning.assert_not_called()
        kwargs=app.experimental_shadow.arm.call_args.kwargs
        self.assertEqual(kwargs['enrolled_quantities'],{'ALT':'1','USD':'10'})
        self.assertEqual(kwargs['fresh_usd_rates']['ALT'],'100')
        self.assertFalse(kwargs['real_arm'])

    def test_validated_start_uses_same_valuation_policy(self):
        app=self.app()
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_shadow_arm()
        warning.assert_not_called()
        app.shadow_pilot.arm.assert_called_once()
        self.assertFalse(app.shadow_pilot.arm.call_args.kwargs['real_arm'])

    def test_missing_mark_message_names_cause_without_balance_values(self):
        app=self.app();app._portfolio_quotes={}
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_experimental_shadow()
        app.experimental_shadow.arm.assert_not_called()
        message=warning.call_args.args[1]
        self.assertIn('USD_VALUATION_INCOMPLETE',message)
        self.assertIn('ALT',message)

    def test_balance_mismatch_remains_blocked_and_distinct(self):
        app=self.app();app.external_mismatches=[{'asset':'ALT'}]
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_experimental_shadow()
        app.experimental_shadow.arm.assert_not_called()
        self.assertIn('BALANCE_MISMATCH',warning.call_args.args[1])

    def test_excluded_unpriced_asset_is_not_part_of_authorized_shadow_wallet(self):
        app=self.app();app.current_balances['EXCLUDED']=D('1')
        app.ledger.assets=lambda:[{'asset':'ALT','remaining_qty':'1','enabled':1},
            {'asset':'USD','remaining_qty':'10','enabled':1},
            {'asset':'EXCLUDED','remaining_qty':'1','enabled':0}]
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_experimental_shadow()
        warning.assert_not_called()
        self.assertNotIn('EXCLUDED',app.experimental_shadow.arm.call_args.kwargs['enrolled_quantities'])

    def test_wide_holding_can_be_marked_without_becoming_trade_eligible(self):
        app=self.app();now=time.time()
        books=app._shadow_valuation_books()
        valuation=mark_coverage(['ALT'],books,now=now,max_spread=D('.20'),max_legs=3)
        self.assertTrue(valuation['complete'])
        self.assertEqual(valuation['rates']['ALT'],'100')
        self.assertFalse(mark_coverage(['ALT'],books,now=now)['complete'])
        ideas,rejected=fast_candidates([('ALT','ALT-USD')],books,{},now=now)
        self.assertEqual(ideas,[]);self.assertEqual(rejected,1)

    def test_wide_newest_book_does_not_hide_behind_older_tight_quote(self):
        now=time.time()
        old={'ALT-USD':('100','100.01',now-1)}
        new={'ALT-USD':('90','91',now)}
        books=newest_books(old,new,now=now)
        self.assertEqual(books['ALT-USD'][2],now)
        self.assertFalse(mark_coverage(['ALT'],books,now=now)['complete'])

    def test_unusable_wider_than_display_limit_stays_blocked(self):
        app=self.app();app._portfolio_quotes['ALT-USD']=('100','200',time.time())
        with patch('coincat_app.messagebox.showwarning') as warning:
            app._toggle_experimental_shadow()
        app.experimental_shadow.arm.assert_not_called()
        self.assertIn('USD_VALUATION_INCOMPLETE',warning.call_args.args[1])

    def test_stop_and_stale_balances_stay_blocked(self):
        for reason in ('stop','stale'):
            app=self.app()
            if reason=='stop':app.ledger.setting=lambda *a:'1'
            else:app._last_portfolio_sync_monotonic-=301
            with patch('coincat_app.messagebox.showwarning') as warning:
                app._toggle_experimental_shadow()
            app.experimental_shadow.arm.assert_not_called()
            expected='EMERGENCY_STOP_ACTIVE' if reason=='stop' else 'BALANCES_STALE'
            self.assertIn(expected,warning.call_args.args[1])

    def test_cached_wide_hold_mark_does_not_consume_each_urgent_budget(self):
        app=self.app();now=time.time()
        app.catalog+=['SOL-USD']
        plan=select_fast_books(['SOL-USD'],app.catalog,['USD'],required_assets=['ALT'],
                               quotes=app._portfolio_quotes,now=now)
        self.assertEqual(plan['books'],['SOL-USD'])

    def test_three_leg_hold_mark_is_retained_without_changing_trade_policy(self):
        now=time.time()
        books={'ALT-BTC':('1','1.001',now),'BTC-USDC':('10','10.01',now),
               'USDC-USD':('.9','.901',now)}
        self.assertFalse(mark_coverage(['ALT'],books,now=now)['complete'])
        valuation=mark_coverage(['ALT'],books,now=now,max_legs=3,max_spread=D('.20'))
        self.assertTrue(valuation['complete'])
        self.assertEqual(valuation['rates']['ALT'],'9.0')

    def test_urgent_planner_can_research_tight_route_while_wide_hold_is_valued(self):
        app=self.app();app.catalog+=['SOL-USD']
        app.broker.catalog_product_rules={'SOL-USD':{'base_increment':'.00001',
            'base_min_size':'.00001','quote_min_size':'.01'}}
        app.fee_learning=NS(latest_tier=lambda:{'fresh':True,'taker':D('.009')})
        app.stream_research=NS(rank_for_rest_scout=lambda *a,**kw:['SOL-USD'],
            snapshot=lambda **kw:{'rows':[{'pair':'SOL-USD','last_trade':10,'change_30s_pct':2.4}]})
        app._fast_candidate_signature=None;app._fast_candidate_signature_at=0
        app.relative_lab=NS(paired_outcomes=lambda *a,**kw:{'status':'NOT_VERIFIED'})
        app.switch_minimum_usd=D('.1')
        app.forward=NS(recent_bid_ask=lambda **kw:books.copy(),
            record_quote=lambda p,ts,b,a,**kw:books.update({p:(b,a,ts)}))
        books={}
        def snapshot(pair,**kw):
            self.assertEqual(pair,'SOL-USD')
            return QuoteSnapshot(pair,D('9.98'),D('10'),time.time(),time.time(),1)
        with patch('coincat_app.fetch_snapshot',side_effect=snapshot):
            result=app._fast_cycle()
        self.assertEqual(result['state'],'RESEARCHED')
        self.assertTrue(result['mark_coverage']['complete'])
        self.assertGreater(result['plan']['exploratory_viable_routes'],0)
        self.assertFalse(result['live_order_permission'])


if __name__=='__main__':unittest.main()
