"""Prospective fixed-policy tests; all market/print data is synthetic."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import unittest

from coincat_assumed_math import rounded
from coincat_beta_store import BetaBlocked
from coincat_opportunity_policy import OpportunityConfig,seed,evaluate,assess,performance
from coincat_portfolio_policy import usd_marks
from coincat_opportunity_venue import parse_trades,modeled_fill
from offline_tests.test_resumable_trial import Clock,frame

def market(clock,step=0,*,depth=D(100000)):
    result=frame(clock,step)
    for pair,b in result['books'].items():
        tick=D('.000000000001');bid=rounded(b['bid'],tick);ask=rounded(b['ask'],tick,up=True)
        b.update(bid=bid,ask=ask,bids=((bid,min(depth,D('.000001'))),(bid-tick,depth)),
            asks=((ask,min(depth,D('.000001'))),(ask+tick,depth)))
    result['market_trades']=None;result['trade_status']='TEST_UNSUPPLIED';return result

def history(clock,*,trend=True):
    rows=[];first=clock.wall()
    for i in range(21):
        f=market(clock,i if trend else 0);marks,_=usd_marks(f);rows.append(dict(at=clock.wall(),marks=marks));clock.tick(30)
    return rows

class OpportunitySelection(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.config=OpportunityConfig();funding=seed(market(self.clock),self.clock.wall())
        self.wallet=funding['wallet'];self.original=deepcopy(self.wallet)
    def evaluate(self,observations,step=21):
        return evaluate(market(self.clock,step),self.wallet,self.wallet,self.original,observations,self.config)
    def test_flat_market_rejects_all_fourteen_after_costs_without_alternating_or_spending_fees(self):
        saved=deepcopy(self.wallet);rows,chosen=self.evaluate(history(self.clock,trend=False),0)
        self.assertEqual(len(rows),14);self.assertIsNone(chosen)
        self.assertTrue(all(r['state']=='HOLD' for r in rows));self.assertEqual(self.wallet,saved)
        self.assertEqual(performance(market(self.clock),self.wallet,self.original,D(500))['advantage_usd'],0)
    def test_positive_small_advantage_qualifies_with_no_one_dollar_threshold_or_eth_return(self):
        rows,chosen=self.evaluate(history(self.clock))
        self.assertIsNotNone(chosen);self.assertGreater(chosen['projected_advantage_usd'],0);self.assertLess(chosen['projected_advantage_usd'],1)
        self.assertEqual((chosen['pair'],chosen['side'],chosen['target']),('ETH-BTC','SELL','BTC'))
        self.assertTrue(chosen['post_only']);self.assertEqual(chosen['price'],market(self.clock,21)['books']['ETH-BTC']['ask'])
    def test_future_exit_estimate_affects_decision_without_being_deducted_as_an_executed_fee(self):
        observations=history(self.clock);saved=deepcopy(self.wallet);_,chosen=self.evaluate(observations)
        self.assertGreaterEqual(chosen['estimated_future_exit_cost_usd'],0);self.assertEqual(self.wallet,saved)
        self.assertEqual(chosen['projected_entry_fee_native'],chosen['size']*chosen['price']*D('.005'))
        self.assertEqual(chosen['projected_wallet']['ETH'],saved['ETH']-chosen['size'])
        self.assertEqual(chosen['projected_wallet']['BTC'],saved['BTC']+chosen['size']*chosen['price']-chosen['projected_entry_fee_native'])
    def test_warmup_gaps_and_insufficient_sized_exit_depth_never_claim_positive_advantage(self):
        observations=history(self.clock)
        for kind in ('warmup','gap','depth','fees'):
            obs=deepcopy(observations);f=market(self.clock,21)
            if kind=='warmup':obs=obs[:3]
            if kind=='gap':self.clock.tick(3600);f=market(self.clock,21);obs.append(dict(at=self.clock.wall(),marks=usd_marks(f)[0]))
            if kind=='depth':
                for book in f['books'].values():book.update(bids=((book['bid'],D('.000001')),),asks=((book['ask'],D('.000001')),))
            if kind=='fees':f['tier']['at']-=3601
            rows,chosen=evaluate(f,self.wallet,self.wallet,self.original,obs,self.config)
            with self.subTest(kind=kind):self.assertIsNone(chosen);self.assertEqual(len(rows),14)
    def test_fee_and_uncertainty_changes_can_remove_an_otherwise_positive_candidate(self):
        obs=history(self.clock);f=market(self.clock,21)
        _,selected=evaluate(f,self.wallet,self.wallet,self.original,obs,self.config);self.assertIsNotNone(selected)
        f['tier'].update(maker=D('.04'),taker=D('.04'))
        _,selected=evaluate(f,self.wallet,self.wallet,self.original,obs,self.config);self.assertIsNone(selected)
    def test_finite_native_order_settings_are_validated_and_no_usd_profit_minimum_is_present(self):
        self.assertNotIn('min_profit_usd',self.config.__dict__);self.assertEqual(self.config.review_s,30);self.assertEqual(self.config.reconsider_s,120)
        for changes in (dict(order_lifetime_s=0),dict(retry_budget=100),dict(review_s=15),dict(campaign_lifetime_s=120),dict(provider='REAL')):
            with self.subTest(changes=changes),self.assertRaises(BetaBlocked):replace(self.config,**changes).checked()

class TradeEvidence(unittest.TestCase):
    def test_parser_uses_native_sdk_fields_and_never_infers_aggressor_side(self):
        from datetime import datetime,timezone
        from coinbase.rest.types.product_types import GetMarketTradesResponse
        from coinbase_account import as_dict
        c=Clock();raw=dict(trades=[dict(trade_id='1',product_id='ETH-BTC',price='.03',size='.1',time=datetime.fromtimestamp(c.wall(),timezone.utc).isoformat(),side='BUY')])
        value=parse_trades(as_dict(GetMarketTradesResponse(deepcopy(raw))),'ETH-BTC',c.wall())
        self.assertEqual(value['prints'][0]['size'],D('.1'));self.assertEqual(value['aggressor_side'],'NOT_INFERRED')
        for key,v in (('product_id','BTC-USD'),('price','NaN'),('time','not a timestamp')):
            bad=deepcopy(raw);bad['trades'][0][key]=v
            with self.subTest(key=key),self.assertRaises((ValueError,ArithmeticError)):parse_trades(bad,'ETH-BTC',c.wall())
