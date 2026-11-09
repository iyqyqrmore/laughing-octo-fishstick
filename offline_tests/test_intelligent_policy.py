from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import unittest
from coincat_beta_store import BetaBlocked
from coincat_intelligent_policy import IntelligentConfig,seed,evaluate,assess
from coincat_order_services import native_fill_changes
from coincat_portfolio_policy import DIRECTIONS
from coincat_assumed_math import rounded
from offline_tests.intelligent_fixtures import Clock,history,frame

class OneLegPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Clock();cls.rows=history(cls.c);cls.f=frame(cls.c,cls.rows)
    def setUp(self):
        self.config=IntelligentConfig();self.wallet=seed(self.f,self.c.wall(),self.config)['wallet']
    def test_btc_preference_selects_sell_eth_btc_and_small_positive_advantages_can_qualify(self):
        rows,chosen=evaluate(self.f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertEqual(len(rows),14);self.assertIsNotNone(chosen)
        self.assertEqual(chosen['target'],'BTC');self.assertEqual(chosen['side'],'SELL')
        self.assertGreater(chosen['projected_advantage_usd'],0);self.assertLess(chosen['projected_advantage_usd'],1)
        self.assertNotIn('estimated_future_exit_cost_usd',chosen);self.assertEqual(chosen['horizon_s'],86400)
    def test_all_fourteen_native_conversions_debit_correct_source_and_credit_correct_destination(self):
        for d in DIRECTIONS:
            book=self.f['books'][d['pair']];price=book['bid'] if d['side']=='BUY' else book['ask']
            q=rounded(max(D('.00001'),D(self.f['rules'][d['pair']]['quote_min_size'])/price),D('.000001'),up=True)
            value=assess(self.f,self.wallet,self.wallet,[],self.config,dict(pair=d['pair'],side=d['side'],size=q,price=price))
            with self.subTest(pair=d['pair'],side=d['side']):
                self.assertLess(value['projected_wallet'][d['source']],self.wallet[d['source']])
                self.assertGreater(value['projected_wallet'][d['target']],self.wallet[d['target']])
                self.assertEqual(value['reserve'],self.wallet[d['source']]-value['projected_wallet'][d['source']])
                self.assertEqual(value['fee_currency'],d['pair'].split('-')[1])
                self.assertEqual(value['projected_entry_fee_native'],q*price*D('.005'))
    def test_inverse_eth_preference_buys_eth_with_btc(self):
        f=frame(self.c,history(self.c,mode='eth_trend'));wallet=seed(f,self.c.wall(),self.config)['wallet']
        rows,_=evaluate(f,wallet,wallet,wallet,[],self.config);row=next(r for r in rows if r['pair']=='ETH-BTC' and r['side']=='BUY')
        self.assertEqual(row['state'],'QUALIFIED');self.assertEqual((row['source'],row['target']),('BTC','ETH'))
        self.assertIn('BTC for approximately',row['explanation'])
    def test_large_forecast_uncertainty_blocks_despite_positive_raw_relative_momentum(self):
        f=deepcopy(self.f)
        for asset,row in f['forecast']['error_covariance'].items():
            for other in row:row[other]=D('.01') if asset==other else D(0)
        rows,chosen=evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertIsNone(chosen);self.assertIn('FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE',{r['reason'] for r in rows})
        self.assertTrue(all(r['state']=='HOLD' for r in rows))
    def test_no_taker_or_future_exit_gate_and_entry_commission_in_forecast_exactly_once(self):
        f=deepcopy(self.f);self.assertNotIn('taker',f['tier'])
        for b in f['books'].values():
            b['bids']=((b['bid'],D(100000)),);b['asks']=((b['ask'],D(100000)),)
        _,r=evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config);self.assertIsNotNone(r)
        from coincat_intelligent_market import marks as usd_marks
        from coincat_portfolio_policy import portfolio_value
        marks,_=usd_marks(f);prices={a:marks[a]*(1+f['forecast']['mean'][a]) for a in marks}
        expected=portfolio_value(r['projected_wallet'],prices)-portfolio_value(self.wallet,prices)
        self.assertAlmostEqual(r['expected_24h_incremental_usd'],expected,places=20)
        self.assertEqual(r['projected_wallet'][r['source']],self.wallet[r['source']]-r['reserve'])
    def test_unreserved_funding_native_minima_and_risk_caps_prevent_unjustified_upscaling(self):
        empty={a:D(0) for a in self.wallet};rows,chosen=evaluate(self.f,self.wallet,empty,self.wallet,[],self.config)
        self.assertIsNone(chosen);self.assertTrue(all(r['state']=='HOLD' for r in rows))
        f=deepcopy(self.f)
        for raw in f['rules'].values():raw['base_min_size']='1000000'
        self.assertIsNone(evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config)[1])
        _,r=evaluate(self.f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertLess(r['reserve'],self.wallet[r['source']]*self.config.max_source_fraction)
        self.assertGreater(r['evaluated_sizes'],1)
    def test_forecast_missing_uncertain_and_flat_after_fees_produce_explained_hold(self):
        f=deepcopy(self.f);f['forecast']=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT')
        rows,chosen=evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config);self.assertIsNone(chosen)
        self.assertEqual({r['reason'] for r in rows},{'FORECAST_HISTORY_INSUFFICIENT'})
        f=frame(self.c,history(self.c,mode='flat'));wallet=seed(f,self.c.wall(),self.config)['wallet']
        rows,chosen=evaluate(f,wallet,wallet,wallet,[],self.config);self.assertIsNone(chosen)
        self.assertTrue(all(r['reason'] in ('ENTRY_FEE_REMOVES_ADVANTAGE','INSUFFICIENT_24H_EXPECTED_ADVANTAGE','PORTFOLIO_RISK_REMOVES_ADVANTAGE') for r in rows))
    def test_seed_is_one_frozen_copy_of_available_balances_not_available_plus_holds(self):
        f=deepcopy(self.f);f['account']['holds']['ETH']=D(10);funding=seed(f,self.c.wall(),self.config)
        self.assertEqual(funding['wallet']['ETH'],f['account']['available']['ETH'])
        f['account']['at']-=31
        with self.assertRaises(BetaBlocked):seed(f,self.c.wall(),self.config)
