"""Header valuation is GET-only display data, separate from native funding."""
from copy import deepcopy
from decimal import Decimal as D
import unittest
from coinbase.rest.types.portfolios_types import GetPortfolioBreakdownResponse
from coincat_beta_store import BetaBlocked
from coincat_portfolio_display import parse_portfolio,presentation,PortfolioDisplayReader,REFRESH_S
from coincat_spot_market import SpotReader
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from offline_tests import test_spot_manual as fixtures


def breakdown():
    positions=[('BTC',.002,100.),('ETH',.01,20.),('VTHO',800.,2.3),('VET',100.,1.15)]
    return dict(breakdown=dict(portfolio=dict(uuid=fixtures.PORTFOLIO),
        portfolio_balances=dict(total_balance=dict(value='123.45',currency='USD')),
        spot_positions=[dict(asset=a,account_uuid=fixtures.cid(40000+i),total_balance_crypto=q,total_balance_fiat=v)
            for i,(a,q,v) in enumerate(positions)],perp_positions=[],futures_positions=[]))

class PortfolioVenue(fixtures.Venue):
    def __init__(self,clock):super().__init__(clock);self.portfolio_data=breakdown();self.portfolio_calls=[];self.portfolio_fail=False
    def get_portfolio_breakdown(self,**kwargs):
        self.portfolio_calls.append(kwargs)
        if self.portfolio_fail:raise TimeoutError('PRIVATE_RESPONSE_MUST_NOT_APPEAR')
        return GetPortfolioBreakdownResponse(deepcopy(self.portfolio_data))

class PortfolioDisplay(unittest.TestCase):
    def setUp(self):
        self.clock=fixtures.Clock();self.venue=PortfolioVenue(self.clock)
        self.reader=SpotReader(self.venue,clock=self.clock.wall,monotonic=self.clock.monotonic,budget=None)
        self.display=PortfolioDisplayReader(self.reader)
    def test_sdk_breakdown_includes_unwatched_holdings_without_price_calls_or_funding_changes(self):
        self.reader.snapshot('ETH-BTC',account=True);account=deepcopy(self.reader.account);books=deepcopy(self.reader.books)
        result=self.display.collect();data=result['data']
        self.assertEqual(data['total_usd'],D('123.45'));self.assertTrue(data['complete'])
        self.assertEqual({v['asset'] for v in data['positions']},{'BTC','ETH','VET','VTHO'})
        self.assertEqual(self.venue.portfolio_calls,[dict(portfolio_uuid=fixtures.PORTFOLIO,currency='USD')])
        self.assertEqual(self.reader.calls,2);self.assertEqual(self.reader.books,books);self.assertEqual(self.reader.account,account)
        self.assertEqual(len(WATCH_PAIRS),7);self.assertNotIn('VET',WATCH_ASSETS)
        with self.assertRaises(BetaBlocked):self.reader.book('VET-USD')
        with self.assertRaises(ValueError):exact(.002) # Display floats never relax financial parsers.
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_refresh_cadence_and_successive_values(self):
        self.assertTrue(self.display.due());first=self.display.collect();self.assertFalse(self.display.due())
        self.clock.tick(REFRESH_S);self.assertTrue(self.display.due())
        self.assertFalse(self.display.overdue());self.clock.tick(REFRESH_S);self.assertTrue(self.display.overdue())
        self.venue.portfolio_data['breakdown']['portfolio_balances']['total_balance']['value']='133.45'
        self.venue.portfolio_data['breakdown']['spot_positions'][0]['total_balance_fiat']=110.
        second=self.display.collect();self.assertEqual(first['data']['total_usd'],D('123.45'))
        self.assertEqual(second['data']['total_usd'],D('133.45'));self.assertGreater(second['data']['at'],first['data']['at'])
    def test_wrong_scope_or_denomination_and_nonfinite_values_do_not_become_live_totals(self):
        for kind in ('scope','currency','nan','negative','shape'):
            raw=breakdown()
            if kind=='scope':raw['breakdown']['portfolio']['uuid']=fixtures.cid(999)
            if kind=='currency':raw['breakdown']['portfolio_balances']['total_balance']['currency']='EUR'
            if kind in ('nan','negative'):
                raw['breakdown']['portfolio_balances']['total_balance']['value']='NaN' if kind=='nan' else '-10'
            if kind=='shape':raw['breakdown']['portfolio']=1
            with self.subTest(kind=kind):
                if kind in ('nan','negative'):
                    data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall());self.assertEqual(data['total_source'],'PRICED_SUBTOTAL')
                    self.assertFalse(data['complete']);self.assertIn('Priced subtotal',presentation(dict(data=data),self.clock.wall(),True)['title'])
                else:
                    with self.assertRaises(BetaBlocked):parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall())
    def test_unknown_position_value_is_not_zero_and_keeps_reported_total_separate(self):
        raw=breakdown();raw['breakdown']['spot_positions'][2].pop('total_balance_fiat')
        data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall());self.assertFalse(data['complete'])
        self.assertEqual(data['total_usd'],D('123.45'));row=next(v for v in data['positions'] if v['asset']=='VTHO')
        self.assertIsNone(row['usd']);view=presentation(dict(data=data),self.clock.wall(),True)
        self.assertIn('UNKNOWN',view['hover']);self.assertIn('partial',view['caption'])
        raw['breakdown']['portfolio_balances']['total_balance'].pop('value')
        for row in raw['breakdown']['spot_positions']:row.pop('total_balance_fiat',None)
        data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall());self.assertIsNone(data['total_usd'])
        self.assertEqual(presentation(dict(data=data),self.clock.wall(),True)['amount'],'—')
    def test_total_already_includes_held_balances_and_duplicate_positions_are_not_added_twice(self):
        raw=breakdown();raw['breakdown']['spot_positions'][0]['available_to_trade_crypto']=.001
        original=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall())
        raw['breakdown']['spot_positions'].append(deepcopy(raw['breakdown']['spot_positions'][0]))
        repeated=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall())
        self.assertEqual(original['positions'],repeated['positions']);self.assertEqual(repeated['priced_subtotal_usd'],D('123.45'))
        self.assertFalse(repeated['complete']);self.assertEqual(repeated['positions'][0]['quantity'],D('.002'))
    def test_distinct_accounts_for_same_asset_aggregate_once_and_unlisted_value_is_explicit(self):
        raw=breakdown();row=deepcopy(raw['breakdown']['spot_positions'][0]);row['account_uuid']=fixtures.cid(50000)
        raw['breakdown']['spot_positions'].append(row);raw['breakdown']['portfolio_balances']['total_balance']['value']='223.45'
        data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall());self.assertTrue(data['complete'])
        self.assertEqual(data['positions'][0]['quantity'],D('.004'))
        raw['breakdown']['portfolio_balances']['total_balance']['value']='230.45';data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall())
        self.assertFalse(data['complete']);self.assertIn('Other reported value: $7.00',presentation(dict(data=data),self.clock.wall(),True)['hover'])
    def test_data_age_disconnect_and_failed_refresh_never_appear_fresh(self):
        result=self.display.collect();self.assertFalse(presentation(result,self.clock.wall(),True)['stale'])
        self.clock.tick(31);self.assertTrue(presentation(result,self.clock.wall(),True)['stale'])
        self.assertTrue(presentation(result,self.clock.wall(),False)['stale'])
        self.venue.portfolio_fail=True;result=self.display.collect();view=presentation(result,self.clock.wall(),True)
        self.assertTrue(view['stale']);self.assertIn('Stale',view['caption']);self.assertIn('$123.45',view['amount'])
        self.assertNotIn('PRIVATE_RESPONSE',view['hover'])
    def test_changed_permission_scope_never_retains_other_portfolio_values(self):
        self.display.collect();self.venue.permission['portfolio_uuid']=fixtures.cid(777);result=self.display.collect()
        self.assertIsNone(result['data']);self.assertTrue(result['failed'])
        self.venue.permission['can_view']=False;result=self.display.collect();self.assertIsNone(result['data'])
    def test_empty_portfolio_is_zero_and_missing_positions_or_timestamp_is_unavailable(self):
        raw=breakdown();raw['breakdown']['spot_positions']=[];raw['breakdown']['portfolio_balances']['total_balance']['value']='0'
        data=parse_portfolio(raw,fixtures.PORTFOLIO,self.clock.wall());self.assertTrue(data['complete'])
        self.assertIn('$0.00',presentation(dict(data=data),self.clock.wall(),True)['amount'])
        for bad in (None,{},dict(breakdown=dict(portfolio=dict(uuid=fixtures.PORTFOLIO),portfolio_balances={},spot_positions=[]))):
            with self.subTest(raw=bad),self.assertRaises(BetaBlocked):parse_portfolio(bad,fixtures.PORTFOLIO,self.clock.wall())
        with self.assertRaises(BetaBlocked):parse_portfolio(raw,fixtures.PORTFOLIO,float('nan'))
