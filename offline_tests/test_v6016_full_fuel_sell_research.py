"""v60.16 full verified holding research, isolated from LIVE limits/orders.
No Coinbase calls, GUI creation, real financial ledger, or credentials.
"""
import unittest,time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from coincat_v6016_sell_research import verified_full_sell_quantity,research_preview_slice_cap


class FullHoldingResearch(unittest.TestCase):
    def test_full_funding_uses_min_of_enrolled_and_available(self):
        self.assertEqual(Decimal('.4'),verified_full_sell_quantity('.8','.4',fresh=True))
        self.assertEqual(Decimal('.8'),verified_full_sell_quantity('.8','1.2',fresh=True))
        self.assertEqual(Decimal('0'),verified_full_sell_quantity('0','8',fresh=True))

    def test_missing_stale_or_nonfinite_funding_never_invented(self):
        for available in (None,'NaN','Infinity','-1',True,0.1):
            self.assertIsNone(verified_full_sell_quantity('1',available,fresh=True))
        self.assertIsNone(verified_full_sell_quantity('1','1',fresh=False))
        self.assertIsNone(verified_full_sell_quantity('1','1',fresh=1))

    def test_live_cap_used_only_as_read_only_slice_reference(self):
        self.assertEqual(Decimal('5'),research_preview_slice_cap('5','10'))
        self.assertEqual(Decimal('10'),research_preview_slice_cap('100','10'))
        self.assertEqual(Decimal('10'),research_preview_slice_cap(None,'10'))
        self.assertEqual(Decimal('10'),research_preview_slice_cap('NaN','10'))

    def fake_app(self,*,enrolled='.8',available='.6',balance_age=2):
        from coincat_app import CoinCatApp
        now=time.time()
        app=CoinCatApp.__new__(CoinCatApp)
        base={'asset':'BTC','enabled':1,'remaining_qty':enrolled,
              'snapshot_unit_usd':None,'trading_basis_unit_quote':'10000'}
        app.ledger=SimpleNamespace(assets=lambda:[base],setting=lambda *a: '0')
        app.current_balances={'BTC':available}
        app._last_portfolio_sync_monotonic=time.monotonic()-balance_age
        app.catalog=['BTC-USD']
        app.lab=SimpleNamespace(observations=lambda pair:[(now-3,Decimal('20000'),Decimal('20001'))],
                                recommendation=Mock(return_value={'action':'SELL','net_pct':Decimal('5'),
                                                                      'reason':'research-only target'}))
        app.fee_learning=SimpleNamespace(latest_tier=lambda:{'fresh':True,'taker':Decimal('.009')})
        app.preview_target_net_usd=Decimal('.10')
        app.target_net_usd=Decimal('.10')
        app.broker=SimpleNamespace(armed=False,per_order_max='5')
        app.limits=[SimpleNamespace(get=lambda:'100000')]
        app._watchlist=lambda advance=False:[]
        return app

    def test_sell_review_does_not_fallback_to_five_dollars(self):
        from coincat_app import CoinCatApp
        app=self.fake_app()
        records=CoinCatApp._review_sell_inventory(app)
        self.assertEqual(len(records),1)
        self.assertEqual(Decimal('12000.0'),records[0]['value'])
        self.assertEqual(Decimal('12000.0'),app.lab.recommendation.call_args.kwargs['planned_quote_value'])
        self.assertEqual('SELL',records[0]['action'])

    def test_full_preview_fails_closed_with_stale_or_zero_liquid_balance(self):
        from coincat_app import CoinCatApp
        app=self.fake_app(balance_age=310)
        rows=CoinCatApp._review_sell_inventory(app)
        self.assertEqual('WAIT',rows[0]['action'])
        self.assertIsNone(rows[0]['value'])
        self.assertEqual(0,app.lab.recommendation.call_count)
        app=self.fake_app(available='0')
        rows=CoinCatApp._review_sell_inventory(app)
        self.assertEqual('WAIT',rows[0]['action'])
        self.assertEqual(0,app.lab.recommendation.call_count)

    def test_crypto_quote_sell_research_uses_correct_asset_verified_fuel(self):
        from coincat_app import CoinCatApp
        app=self.fake_app(enrolled='.8',available='.6')
        at=time.time()-2
        books={'BTC-ETH':(Decimal('20'),Decimal('20.001'),at),
               'ETH-USD':(Decimal('1000'),Decimal('1000.1'),at)}
        app.catalog=['BTC-ETH','ETH-USD']
        app._last_research_watch=list(books)
        app.lab.observations=lambda pair:[(books[pair][2],books[pair][0],books[pair][1])] if pair in books else []
        app.ledger.sale_basis=lambda *args:{'performance_basis':Decimal('6000')}
        app.fee_learning.account_cost=lambda *args:{'fresh':True,'taker':Decimal('.009')}
        rows=CoinCatApp._review_sell_inventory(app)
        cross=[r for r in rows if r['pair']=='BTC-ETH']
        self.assertEqual(1,len(cross))
        self.assertEqual(Decimal('12000.0'),cross[0]['value'])
        self.assertEqual('RESEARCH SELL',cross[0]['action'])
        # Never take another asset's previously iterated qty into BTC estimate.
        app.current_balances['BTC']='0.1'
        rows=CoinCatApp._review_sell_inventory(app)
        cross=[r for r in rows if r['pair']=='BTC-ETH']
        self.assertEqual(Decimal('2000.0'),cross[0]['value'])

    def test_whole_holding_view_not_blacked_out_by_high_manual_cap(self):
        from coincat_app import CoinCatApp
        app=self.fake_app(enrolled='.8',available='.6')
        at=time.time()-3
        app._shadow_valuation_books=lambda:{'BTC-USD':(Decimal('20000'),Decimal('20001'),at)}
        records=CoinCatApp._full_exit_research(app)
        self.assertEqual(1,len(records))
        self.assertEqual(Decimal('12000.0'),records[0]['gross_usd_before_fees'])
        self.assertGreater(records[0]['min_cap_slices_estimate'],1)
        self.assertEqual('RESEARCH ONLY',records[0]['state'])

    def test_snowball_full_available_routing_stays_separately_costed(self):
        from coincat_v606_budgets import DEFAULT,effective
        from coincat_rotation_autopilot import auto_rotation_screen
        budget=effective(dict(DEFAULT,mode='FULL_AVAILABLE'),'175')
        self.assertEqual(budget['per_order_usd'],'175')
        self.assertEqual(budget['daily_buy_usd'],'175')
        src=(Path(__file__).resolve().parents[1]/'app'/'coincat_rotation_autopilot.py').read_text()
        self.assertIn("(full_cap, full_cap*Decimal('.75'), full_cap*Decimal('.5')",src)
        self.assertIn('authorized_qty=qty, verified_available_qty=qty',src)
        broker=(Path(__file__).resolve().parents[1]/'app'/'coincat_live.py').read_text()
        self.assertIn('LiveBlocked',broker)

    def test_trading_limit_edits_are_not_changed(self):
        from coincat_app import CoinCatApp
        app=self.fake_app()
        app.broker.armed=True
        rows=CoinCatApp._review_sell_inventory(app)
        self.assertEqual(Decimal('12000.0'),rows[0]['value'])
        self.assertEqual('5',app.broker.per_order_max)
        self.assertEqual('100000',app.limits[0].get())

if __name__=='__main__':unittest.main()
