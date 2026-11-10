from copy import deepcopy
from decimal import Decimal as D
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json,unittest
from v106.simulator import Simulator
from v106.strategies import exit_price
from v106.backtest import study,render,main,fmt
from v106.preregistered import MAKER,verdict,grid

RULES=dict(base_increment='0.00000001',price_increment='0.000001',base_min_size='0.00000001',
    quote_min_size='0.00001',base_max_size='6100',quote_max_size='200')
START=1794000000


def frame(i,price='.05',*,low=None,high=None,volume='100',spread=None):
    p=D(price);tick=D('.000001');at=START+i*300
    return dict(start=at,at=at+300,close=p,open=p,low=D(low) if low is not None else p,high=D(high) if high is not None else p,
        volume=D(volume),bid=p-tick,ask=p+(D(spread) if spread else tick),eth_usd=p*40000,btc_usd=D(40000))


class Roundtrip(unittest.TestCase):
    def begin(self,*,params=None,fee=MAKER):
        sim=Simulator('ROUNDTRIP',frame(0),RULES,params=params or dict(profit_margin=D('.003'),reprice_ticks=3,max_hold_days=None),fee=fee,record=True)
        sim.step(frame(0));return sim
    def enter(self,**kwargs):
        sim=self.begin(**kwargs);o=deepcopy(sim.order)
        sim.step(frame(1,low=str(o['price']-D('.000001')),high='.08'))
        return sim,o
    def test_no_trade_hold50_has_no_fees_orders_or_benchmark_redefinition(self):
        sim=Simulator('HOLD50',frame(0),RULES);before=deepcopy(sim.original)
        for i in range(20):sim.step(frame(i,'.04'))
        r=sim.snapshot();self.assertEqual(r['orders'],0);self.assertEqual(r['fees_btc'],0)
        self.assertEqual(r['advantage_usd'],0);self.assertEqual(r['advantage_btc'],0);self.assertEqual(sim.original,before)
    def test_touch_alone_is_not_a_fill_and_expiry_keeps_miss_in_denominator(self):
        sim=self.begin();p=sim.order['price'];sim.step(frame(1,low=str(p)))
        self.assertEqual(sim.metrics['fills'],0);sim.step(frame(2,low=str(p)))
        self.assertEqual(sim.metrics['misses'],1);self.assertEqual(sim.metrics['fees_btc'],0)
        self.assertEqual(sim.metrics['orders'],2);self.assertEqual(sim.metrics['entry_replaces'],1)
    def test_entry_spends_at_most_half_btc_including_own_fee(self):
        sim=self.begin();o=sim.order
        self.assertLessEqual(o['quantity']*o['price']*(1+MAKER),sim.wallet['BTC']/2)
        self.assertEqual(o['quantity']%D(RULES['base_increment']),0)
    def test_chasing_entry_changes_price_only_after_distance_or_age(self):
        sim=self.begin();first=deepcopy(sim.order);sim.step(frame(1,'.050010'))
        self.assertNotEqual(sim.order['id'],first['id']);self.assertEqual(sim.metrics['entry_replaces'],1)
        self.assertEqual(sim.metrics['fees_btc'],0)
    def test_wide_spread_cancels_then_waits_with_zero_fee(self):
        sim=self.begin();sim.step(frame(1,spread='.001'))
        self.assertIsNone(sim.order);self.assertEqual(sim.metrics['misses'],1);self.assertEqual(sim.metrics['fees_btc'],0)
        sim.step(frame(2));self.assertIsNotNone(sim.order)
    def test_partial_entry_exits_filled_quantity_only_and_cannot_exit_in_same_bar(self):
        sim=self.begin();o=deepcopy(sim.order);q=D('.001')
        sim.step(frame(1,low=str(o['price']-D('.000001')),high='.08',volume=str(q)))
        self.assertEqual(sim.order['phase'],'EXIT');self.assertEqual(sim.order['quantity'],q)
        self.assertEqual(sim.metrics['fills'],1);self.assertEqual(sim.metrics['cycles'],0)
        self.assertEqual(sim.metrics['fees_btc'],q*o['price']*MAKER);self.assertEqual(sim.metrics['entry_cancels'],1)
    def test_two_filled_legs_pay_exactly_two_own_fees_and_finish_with_positive_btc(self):
        sim,entry=self.enter();exit=deepcopy(sim.order);original=deepcopy(sim.original)
        sim.step(frame(2,high=str(exit['price']+D('.000001'))))
        self.assertEqual(sim.metrics['cycles'],1);q=entry['quantity']
        self.assertEqual(sim.metrics['fees_btc'],q*(entry['price']+exit['price'])*MAKER)
        self.assertGreater(sim.metrics['cycle_profit_btc'],0);self.assertEqual(sim.wallet['ETH'],original['ETH'])
        self.assertEqual(sim.original,original);self.assertEqual(sim.metrics['max_stuck_seconds'],300)
        r=sim.snapshot();self.assertEqual(r['fees_pct_initial_portfolio'],sim.metrics['fees_usd']/D(200)*100)
    def test_sell_entry_then_buy_exit_restores_eth_and_retains_btc_profit(self):
        sim=Simulator('ROUNDTRIP',frame(0),RULES,params=dict(profit_margin=D('.003'),reprice_ticks=3,max_hold_days=None))
        sim.step(frame(0,'.06'));entry=deepcopy(sim.order);self.assertEqual(entry['side'],'SELL')
        sim.step(frame(1,'.06',high=str(entry['price']+D('.000001'))));exit=deepcopy(sim.order)
        self.assertEqual(exit['side'],'BUY');self.assertLess(exit['price'],entry['price'])
        sim.step(frame(2,'.06',low=str(exit['price']-D('.000001'))))
        self.assertEqual(sim.metrics['cycles'],1);self.assertEqual(sim.wallet['ETH'],sim.original['ETH'])
        self.assertGreater(sim.wallet['BTC'],sim.original['BTC'])
    def test_partial_exit_charges_only_filled_size_and_keeps_remaining_order(self):
        sim,_=self.enter();o=deepcopy(sim.order);fees=sim.metrics['fees_btc'];q=D('.001')
        sim.step(frame(2,high=str(o['price']+D('.000001')),volume=str(q)))
        self.assertEqual(sim.order['remaining'],o['quantity']-q)
        self.assertEqual(sim.metrics['fees_btc']-fees,q*o['price']*MAKER);self.assertEqual(sim.metrics['cycles'],0)
    def test_break_even_is_derived_and_doubled_fees_raise_sell_floor(self):
        p=D('.05');tick=D('.000001')
        base=exit_price('BUY',p,MAKER,MAKER,D(0),tick)
        stress=exit_price('BUY',p,2*MAKER,2*MAKER,D(0),tick)
        self.assertGreater(stress,base);self.assertGreaterEqual(base*(1-MAKER),p*(1+MAKER))
        mirror=exit_price('SELL',p,MAKER,MAKER,D(0),tick)
        self.assertLessEqual(mirror*(1+MAKER),p*(1-MAKER))
    def test_stuck_exit_never_lowers_target_without_explicit_max_hold_and_open_loss_is_kept(self):
        sim,_=self.enter();floor=sim.order['price'];original=deepcopy(sim.original)
        sim.step(frame(900,'.04'))
        self.assertEqual(sim.order['phase'],'EXIT');self.assertGreaterEqual(sim.order['price'],floor)
        self.assertLess(sim.snapshot()['advantage_usd'],0);self.assertEqual(sim.metrics['cycles'],0)
        self.assertEqual(sim.original,original);self.assertGreater(sim.snapshot()['max_stuck_days'],3)
    def test_explicit_hold_limit_only_relaxes_margin_not_break_even_or_market_order(self):
        sim,entry=self.enter(params=dict(profit_margin=D('.003'),reprice_ticks=3,max_hold_days=1));floor=sim.order['price']
        sim.step(frame(300,'.04'));self.assertLess(sim.order['price'],floor)
        self.assertGreaterEqual(sim.order['price']*(1-MAKER),entry['price']*(1+MAKER))
        self.assertEqual(sim.metrics['cycles'],0);self.assertGreater(sim.snapshot()['max_stuck_days'],1)
    def test_new_window_parameters_do_not_rewrite_active_cycle_margin(self):
        sim,_=self.enter();old=sim.order['price']
        sim.step(frame(2,'.04'),dict(profit_margin=D(0),reprice_ticks=1,max_hold_days=1))
        self.assertEqual(sim.order['price'],old);self.assertEqual(sim.cycle['params']['profit_margin'],D('.003'))
    def test_gap_cannot_create_a_fill_even_when_later_bar_trades_through(self):
        sim=self.begin();o=deepcopy(sim.order);sim.step(frame(5,low=str(o['price']-D('.000001'))))
        self.assertEqual(sim.metrics['fills'],0);self.assertEqual(sim.metrics['fees_btc'],0);self.assertEqual(sim.metrics['gaps'],1)
    def test_go_rule_boundaries_and_registered_roundtrip_grid(self):
        self.assertEqual(verdict(6,10,D(2),D(0)),'GO')
        for args in ((9,9,D(200),D(200)),(5,10,D(2),D(1)),(6,10,D('1.9999999999999999999999999999'),D(1)),
                (6,10,D(0),D(1)),(6,10,D(2),D('-.01')),(0,0,D(200),D(200))):
            with self.subTest(args=args):self.assertEqual(verdict(*args),'NO-GO')
        self.assertEqual(verdict(6,10,D(10),D(0),D(1000)),'GO')
        self.assertEqual(verdict(6,10,D('9.99'),D(1),D(1000)),'NO-GO')
        self.assertEqual(len(grid('ROUNDTRIP')),27);self.assertTrue(all(len(p)==3 for p in grid('ROUNDTRIP')))
    def test_zero_decimal_formatting_keeps_nonzero_precision_and_unknowns(self):
        for value in ('0','-0','0.00000000','0E-80','-0E+12'):
            with self.subTest(value=value):self.assertEqual(fmt(D(value)),'0')
        self.assertEqual(fmt(D('0.00000000000000000001')),'1e-20')
        self.assertEqual(fmt(D('-1.234567891')),'-1.2345679');self.assertEqual(fmt(None),'UNKNOWN')
    def test_report_zero_cells_and_amended_go_rule_are_rendered_together(self):
        value=Simulator('HOLD50',frame(0),RULES).snapshot()
        for key,number in value.items():
            if isinstance(number,D) and not number:value[key]=D('-0E-80')
        value.update(verdict='REFERENCE',winning_windows=0,test_windows=10,stress_advantage_usd=D('0E-80'))
        report=render(dict(status='EVALUATED',strategies={'HOLD50':value},windows=[]))
        self.assertIn('| HOLD50 | REFERENCE | 0/10 | 0 | 0 | 0 | 0 | 0 | 0 | UNKNOWN | 0 | 0/0 | False | 0 |',report)
        self.assertIn('>=10 unseen test windows',report);self.assertIn('>=1% of the starting portfolio',report)
        self.assertIn('Preregistration commit: `eed34e25f5dd35499d5e3086a2d4f090a3ffd3b3`.',report)
    def test_walk_forward_keeps_unseen_training_separate_and_adverse_stuck_losses(self):
        frames=[frame(i,'.05' if i<288 else '.04',low='.039') for i in range(864)]
        seen=[]
        def selection(name,train,rules):
            seen.append((name,train[-1]['at']));return grid(name)[0]
        with patch('v106.backtest.choose',selection):result=study(frames,RULES,train_days=1,test_days=1)
        self.assertEqual(result['status'],'EVALUATED');self.assertEqual(len(result['windows']),2)
        for i,w in enumerate(result['windows']):
            self.assertLess(seen[i*4][1],__import__('v106.export_candles',fromlist=['stamp']).stamp(w['start_utc']))
        original=result['strategies']['HOLD50']['original']
        self.assertTrue(all(s['original']==original for s in result['strategies'].values()))
        self.assertTrue(all('stress_advantage_usd' in s for s in result['strategies'].values()))
        self.assertIn('Fee percentage denominator: total starting portfolio',render(result))
    def test_absent_market_data_is_not_presented_as_a_strategy_verdict(self):
        result=study([],RULES);self.assertEqual(result['status'],'NOT_EVALUATED');self.assertEqual(result['strategies'],{})
        self.assertIn('NOT EVALUATED',render(result))

    def test_real_parameter_selector_runs_only_on_training_and_all_outputs_are_reproducible(self):
        frames=[frame(i,'.05' if i<288 else '.04',low='.039') for i in range(576)]
        first=study(frames,RULES,train_days=1,test_days=1)
        second=study(frames,RULES,train_days=1,test_days=1)
        self.assertEqual(first,second);self.assertEqual(len(first['windows']),1)
        self.assertEqual(first['strategies']['HOLD50']['fees_usd'],0)
        self.assertLess(first['strategies']['ROUNDTRIP']['advantage_usd'],0)
        for name,result in first['strategies'].items():
            if name!='HOLD50':
                self.assertEqual(result['verdict'],'NO-GO');self.assertEqual(result['verdict_reason'],'INSUFFICIENT_WINDOWS')
        self.assertIn('NO-GO (INSUFFICIENT_WINDOWS)',render(first))

    def test_incomplete_export_has_no_market_go_no_go_claim(self):
        with TemporaryDirectory() as folder:
            path=Path(folder);(path/'export_summary.json').write_text('{"status":"INCOMPLETE"}')
            fees=dict(status='VERIFIED',product_id='ETH-BTC',fees=dict(maker_rate='0.005',taker_rate='0.009'),product=RULES)
            (path/'fees.json').write_text(json.dumps(fees))
            result=main(['--data',folder,'--fees',str(path/'fees.json'),'--output',folder])
            self.assertEqual(result,1)
            report=json.loads((path/'backtest_results.json').read_text())
            self.assertEqual(report['reason'],'M1_EXPORT_INCOMPLETE');self.assertFalse(report['strategies'])


if __name__=='__main__':unittest.main()
