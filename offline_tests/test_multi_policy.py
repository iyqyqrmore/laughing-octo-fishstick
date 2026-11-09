from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_multi_policy import MultiConfig,evaluate,assess_horizon,corrected_core
from coincat_horizon_forecast import HORIZONS
from coincat_intelligent_policy import seed
from coincat_portfolio_policy import DIRECTIONS
from coincat_order_services import native_fill_changes
from coincat_execution_limits import native_math
from coincat_assumed_math import rounded
from offline_tests.multi_fixtures import Clock,predictions,observed,series
from coincat_horizon_forecast import immediate_inputs

class MultiPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Clock();cls.forecasts=predictions(cls.c);cls.f=observed(cls.c,cls.forecasts)
    def setUp(self):self.config=MultiConfig().checked();self.wallet=seed(self.f,self.c.wall(),self.config)['wallet']
    def test_supported_short_horizon_can_qualify_while_24_hours_has_no_data(self):
        rows,best=evaluate(self.f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertEqual(len(rows),14);self.assertIsNotNone(best);self.assertNotEqual(best['selected_horizon'],'H24')
        self.assertEqual(best['target'],'BTC');self.assertEqual(best['side'],'SELL');self.assertGreater(best['projected_advantage_usd'],0)
        for row in rows:self.assertEqual(row['horizons']['H24']['reason'],'FORECAST_HISTORY_INSUFFICIENT')
    def test_all_horizons_and_sizes_receive_a_fixed_multiplicity_allowance(self):
        core,z=corrected_core(self.config);self.assertGreater(z,D('2.58'));self.assertEqual(self.config.selection_tests,14*6*8)
        self.assertEqual(core.uncertainty_z,z)
    def test_missing_all_horizons_holds_without_fabricated_trade_or_return_fee(self):
        f=deepcopy(self.f);f['horizon_forecasts']={};rows,best=evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertIsNone(best);self.assertTrue(all(r['state']=='HOLD' for r in rows));self.assertEqual(sum(len(r['horizons']) for r in rows),84)
    def test_immediate_requires_net_current_marks_after_fee_not_a_previous_last_trade(self):
        f=deepcopy(self.f);f['horizon_forecasts']['IMMEDIATE']=immediate_inputs(series(self.c,60,61,rate=D(0)),self.c.wall())
        book=f['books']['ETH-BTC'];book['previous_last']=D(1)
        row=assess_horizon(f,self.wallet,self.wallet,self.config,dict(pair='ETH-BTC',side='BUY',size=D('.001'),price=book['bid']),'IMMEDIATE')
        self.assertEqual(row['state'],'HOLD');self.assertLess(row['projected_marked_change_usd'],0)
        for key in ('bid','ask'):book[key]*=D('.991')
        for key in ('bids','asks'):book[key]=tuple((p*D('.991'),q) for p,q in book[key])
        # Exact native tick, never arbitrary limit precision.
        for key in ('bid','ask'):book[key]=rounded(book[key],D('.000000000001'),up=key=='ask')
        row=assess_horizon(f,self.wallet,self.wallet,self.config,dict(pair='ETH-BTC',side='BUY',size=D('.001'),price=book['bid']),'IMMEDIATE')
        self.assertEqual(row['state'],'QUALIFIED');self.assertGreater(row['conservative_immediate_mark_usd'],0);self.assertLess(row['projected_advantage_usd'],1)
    def test_selector_prefers_defensible_lower_bound_instead_of_largest_raw_forecast(self):
        f=deepcopy(self.f)
        for name in HORIZONS:
            if name not in ('M5','H2'):f['horizon_forecasts'][name]=dict(state='HOLD',reason='HORIZON_HISTORY_INSUFFICIENT')
        for name,mean in (('M5',D('.02')),('H2',D('.10'))):
            forecast=f['horizon_forecasts'][name];forecast['mean']=dict.fromkeys(self.wallet,D(0));forecast['mean']['ETH']=mean
        f['horizon_forecasts']['H2']['error_covariance']={a:{b:D('.1') if a==b else D(0) for b in self.wallet} for a in self.wallet}
        rows,best=evaluate(f,self.wallet,self.wallet,self.wallet,[],self.config)
        self.assertEqual(best['selected_horizon'],'M5');self.assertTrue(all(r['horizons']['H2']['state']=='HOLD' for r in rows))
    @native_math
    def test_native_flows_and_entry_fee_are_correct_once_for_each_direction(self):
        for d in DIRECTIONS:
            book=self.f['books'][d['pair']];price=book['bid'] if d['side']=='BUY' else book['ask'];size=rounded(max(D('.0001'),D(self.f['rules'][d['pair']]['quote_min_size'])/price),D('.000001'),up=True)
            row=assess_horizon(self.f,self.wallet,self.wallet,self.config,dict(pair=d['pair'],side=d['side'],size=size,price=price),'M5')
            expected=native_fill_changes(dict(product_id=d['pair'],side=d['side'],size=size,price=price,commission=size*price*D('.005'),fee_currency=d['pair'].split('-')[1],size_in_quote=False))
            for a in self.wallet:self.assertEqual(row['projected_wallet'][a],self.wallet[a]+expected['changes'][a])
            self.assertNotIn('estimated_future_exit_cost_usd',row);self.assertNotIn('expected_24h_incremental_usd',row)
