"""Fake read-only SDK with real Tk; arithmetic and opportunity remain independent."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal as D
import time
import unittest

from coincat_opportunity_policy import OpportunityConfig
from coincat_opportunity_venue import OpportunitySource
from coincat_monitor import capture,encode,validate
from coincat_spot_market import SpotReader
from coincat_spot_public import diagnostic
from coincat_monitor_server import HTML,JS
from offline_tests import test_spot_workspace as manual
from offline_tests.test_opportunity_policy import market
from offline_tests.test_spot_manual import Venue

class OpportunityVenue(Venue):
    def __init__(self,clock):super().__init__(clock);self.trade_calls=[];self.step=0;self.trades=[]
    def get_product(self,product_id,**kwargs):return deepcopy(market(self.clock,self.step)['rules'][product_id])
    def get_product_book(self,product_id,**kwargs):
        b=market(self.clock,self.step)['books'][product_id]
        return dict(pricebook=dict(product_id=product_id,bids=[dict(price=str(p),size=str(q)) for p,q in b['bids']],
            asks=[dict(price=str(p),size=str(q)) for p,q in b['asks']]))
    def get_market_trades(self,**kwargs):self.trade_calls.append(kwargs);return dict(trades=deepcopy(self.trades))

class OpportunitySourceTests(unittest.TestCase):
    def test_one_active_native_trade_get_stays_in_existing_budget_and_never_writes(self):
        from offline_tests.test_resumable_trial import Clock
        c=Clock();venue=OpportunityVenue(c);reader=SpotReader(venue,clock=c.wall,monotonic=c.monotonic,budget=None);source=OpportunitySource(reader)
        self.assertEqual(source.collect()['state'],'PRIMING');c.tick(10)
        venue.trades=[dict(trade_id='1',product_id='ETH-BTC',price='.03',size='.01',time=datetime.fromtimestamp(c.wall(),timezone.utc).isoformat(),side='SELL')]
        result=source.collect('ETH-BTC');self.assertEqual(result['market_trades']['pair'],'ETH-BTC')
        self.assertEqual(venue.trade_calls,[dict(product_id='ETH-BTC',limit=100)]);self.assertLessEqual(reader.calls,16)
        self.assertEqual(venue.posts,[]);self.assertEqual(venue.cancels,[])
        with self.assertRaises(BetaBlocked):source.collect('BTC-USD')

from coincat_beta_store import BetaBlocked
