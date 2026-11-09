"""Authenticated SDK shapes, budget, per-pair failures and no mutation authority."""
from copy import deepcopy
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from coincat_beta_store import BetaBlocked
from coincat_intelligent_source import IntelligentSource
from coincat_intelligent_market import quality,REFERENCES
from coincat_spot_market import SpotReader
from coincat_watchlist import WATCH_PAIRS
from offline_tests.test_spot_manual import Venue
from offline_tests.intelligent_fixtures import Clock,history,frame

class IntelligentVenue(Venue):
    def __init__(self,clock,template=None):
        super().__init__(clock);self.template=template or frame(clock);self.books_read=[];self.rules_read=[];self.trade_calls=[]
        self.available=deepcopy(self.template['account']['available']);self.missing=None
    def get_product(self,product_id,**kwargs):
        self.rules_read.append(product_id)
        if product_id==self.missing:raise ValueError('PRIVATE raw SDK error')
        return deepcopy(self.template['rules'][product_id])
    def get_product_book(self,product_id,**kwargs):
        self.books_read.append(product_id)
        b=(self.template['books'] if product_id in WATCH_PAIRS else self.template['reference_books'])[product_id]
        return dict(pricebook=dict(product_id=product_id,bids=[dict(price=str(p),size=str(q)) for p,q in b['bids']],
            asks=[dict(price=str(p),size=str(q)) for p,q in b['asks']]))
    def get_market_trades(self,**kwargs):self.trade_calls.append(kwargs);return dict(trades=[])
    def get_transaction_summary(self,**kwargs):return dict(fee_tier=dict(maker_fee_rate='.005'))

class HistoryEstimate:
    def __init__(self,clock,template):self.clock=clock;self.template=template
    def estimate(self,at,config=None):
        f=deepcopy(self.template['forecast']);f.update(decision_at=at,forecast_end_at=at+86400);return f

class IntelligentSourceTests(unittest.TestCase):
    def setUp(self):
        self.c=Clock();self.template=frame(self.c);self.venue=IntelligentVenue(self.c,self.template)
        self.reader=SpotReader(self.venue,clock=self.c.wall,monotonic=self.c.monotonic,budget=None)
        self.source=IntelligentSource(self.reader,HistoryEstimate(self.c,self.template))
    def test_warmup_then_twelve_books_and_active_native_trades_fit_single_paced_sixteen_get_wave(self):
        f=self.source.collect();self.assertEqual(f['state'],'PRIMING');self.assertLessEqual(self.reader.calls,9)
        self.c.tick(10);f=self.source.collect('ETH-BTC')
        self.assertEqual(f['state'],'OBSERVED');self.assertEqual(quality(f),(True,7));self.assertLessEqual(self.reader.calls,16)
        self.assertEqual(set(self.venue.books_read),set(WATCH_PAIRS)|set(REFERENCES))
        self.assertEqual(set(self.venue.rules_read),set(WATCH_PAIRS));self.assertEqual(self.venue.trade_calls,[dict(product_id='ETH-BTC',limit=100)])
        self.assertEqual(f['tier']['maker'],D('.005'));self.assertNotIn('taker',f['tier'])
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
        for name in ('limit_order_gtc_buy','cancel_orders'):
            with self.assertRaises(BetaBlocked):self.reader.call(name)
    def test_one_failed_pair_rules_are_retained_as_unavailable_without_global_drop_or_raw_error(self):
        self.venue.missing='ADA-ETH';self.source.collect();self.c.tick(10);f=self.source.collect()
        self.assertEqual(quality(f),(True,7));self.assertNotIn('ADA-ETH',f['rules']);self.assertEqual(len(f['rules']),6)
        self.assertNotIn('PRIVATE',str(f));self.assertEqual(self.venue.posts,[])
    def test_scope_is_rechecked_and_usd_reference_cannot_be_the_active_order_market(self):
        self.source.collect();self.c.tick(10)
        with self.assertRaises(BetaBlocked):self.source.collect('BTC-USD')
        self.venue.permission['can_view']=False
        with self.assertRaises(BetaBlocked):self.source.collect()
        self.assertEqual(self.venue.posts,[])
