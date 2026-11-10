"""Owner's BTC-mid rule, cycle freezing and matched alternating comparison."""
from copy import deepcopy
from decimal import Decimal as D, localcontext
from unittest.mock import patch
import unittest
from v106.simulator import Simulator
from v106.strategies import eth_btc_weight, side_for
from v106.backtest import study, render, choose
from v106.preregistered import MAKER, grid, STRATEGIES
from v106.tests.test_roundtrip import RULES, frame

PARAMS=dict(profit_margin=D('.003'),reprice_ticks=3,max_hold_days=None)


def start(name='ROUNDTRIP', price='.05', fee=MAKER):
    sim=Simulator(name,frame(0),deepcopy(RULES),params=PARAMS,fee=fee,record=True)
    sim.step(frame(0,price));return sim


def complete(sim, i, price='.05'):
    """Explicit later bars trade through each leg; no quote-touch fills."""
    for index in (i,i+1):
        o=deepcopy(sim.order);p=D(price);tick=D(RULES['price_increment'])
        low=min(p,o['price']-tick) if o['side']=='BUY' else p
        high=max(p,o['price']+tick) if o['side']=='SELL' else p
        sim.step(frame(index,price,low=str(low),high=str(high)))


class Direction(unittest.TestCase):
    def test_native_mid_overrules_contradictory_usd_weights_and_other_holdings(self):
        f=dict(frame(0),eth_usd=D(1000000))
        wallet=dict(ETH=D(1),BTC=D('.1'),SOL=D('1e30'),ADA=D('1e30'),LINK=D('1e30'))
        self.assertEqual(side_for('ROUNDTRIP',PARAMS,wallet,f,[]),'BUY')
        f['eth_usd']=D(1);wallet['BTC']=D('.01')
        self.assertEqual(side_for('ROUNDTRIP',PARAMS,wallet,f,[]),'SELL')
        self.assertEqual(eth_btc_weight(wallet,f),eth_btc_weight({a:wallet[a] for a in ('ETH','BTC')},f))

    def test_exact_tie_buys_without_tolerance_on_either_side(self):
        f={'bid':D('.049999'),'ask':D('.050001')}
        wallet={'ETH':D(2),'BTC':D('.1')}
        self.assertEqual(eth_btc_weight(wallet,f),D('.5'))
        self.assertEqual(side_for('ROUNDTRIP',{},wallet,f,[]),'BUY')
        for btc,side in (('.1000000000000000000000000000000000001','BUY'),
                         ('.0999999999999999999999999999999999999','SELL')):
            wallet['BTC']=D(btc)
            self.assertEqual(side_for('ROUNDTRIP',{},wallet,f,[]),side)

    def test_total_wallet_keeps_locked_funds_in_weight_until_fill(self):
        sim=start();total=deepcopy(sim.wallet);o=sim.order
        free=dict(total,BTC=total['BTC']-o['quantity']*o['price']*(1+MAKER))
        self.assertGreater(eth_btc_weight(free,frame(0)),D('.5'))
        self.assertEqual(eth_btc_weight(total,frame(0)),D('.5'))
        self.assertEqual(sim.snapshot()['wallet'],total)
        self.assertEqual(sim.cycle['side'],'BUY')
        sim.step(frame(1))
        self.assertEqual(sim.wallet,total);self.assertEqual(sim.cycle['side'],'BUY')

    def test_buy_side_frozen_across_reprice_spread_wait_window_change_and_gap(self):
        sim=start();began=sim.cycle['started_at']
        with patch('v106.strategies.side_for',side_effect=AssertionError('Direction re-evaluated mid-cycle')):
            sim.step(frame(1,'.06'))  # ETH is now overweight, but the existing cycle is BUY.
            self.assertEqual(sim.order['side'],'BUY')
            sim.step(frame(2,'.07',spread='.001'));self.assertIsNone(sim.order)
            sim.step(frame(3,'.08'),dict(profit_margin=D('.005'),reprice_ticks=1,max_hold_days=1))
            sim.step(frame(9,'.09'))
        self.assertEqual(sim.order['side'],'BUY');self.assertEqual(sim.cycle['started_at'],began)
        self.assertEqual(sim.by_entry_side['BUY']['started'],1);self.assertEqual(sim.by_entry_side['SELL']['started'],0)
        self.assertEqual(sim.metrics['fills'],0);self.assertEqual(sim.cycle['params'],PARAMS)

    def test_sell_side_frozen_when_price_falls_through_fifty_percent_weight(self):
        sim=start(price='.06');self.assertEqual(sim.order['side'],'SELL')
        for i,p in enumerate(('.05','.04','.03'),1):sim.step(frame(i,p))
        self.assertLess(eth_btc_weight(sim.wallet,frame(3,'.03')),D('.5'))
        self.assertEqual(sim.order['side'],'SELL');self.assertEqual(sim.metrics['fills'],0)
        self.assertEqual(sim.by_entry_side['SELL']['started'],1)

    def test_rejected_native_size_does_not_start_or_freeze_a_cycle(self):
        sim=Simulator('ROUNDTRIP',frame(0),dict(RULES,quote_min_size='200'),params=PARAMS)
        sim.step(frame(0));self.assertIsNone(sim.order);self.assertIsNone(sim.cycle)
        sim.rules=deepcopy(RULES);sim.step(frame(1,'.06'))
        self.assertEqual(sim.cycle['side'],'SELL');self.assertEqual(sim.by_entry_side['BUY']['started'],0)

    def test_partial_entry_keeps_origin_side_and_reverses_only_filled_quantity(self):
        sim=start();p=sim.order['price']
        sim.step(frame(1,low=str(p-D('.000001')),volume='.001'))
        self.assertEqual(sim.cycle['side'],'BUY');self.assertEqual(sim.order['side'],'SELL')
        self.assertEqual(sim.order['quantity'],D('.001'))
        sim.step(frame(2,'.04'))
        groups=sim.snapshot()['by_entry_side']
        self.assertEqual(groups['BUY']['entered'],1);self.assertEqual(groups['SELL']['entered'],0)
        self.assertEqual(groups['BUY']['completed'],0)

    def test_alternating_begins_buy_even_overweight_and_does_not_flip_on_entry_cancels(self):
        sim=start('ROUNDTRIP_ALTERNATING',price='.06');self.assertEqual(sim.order['side'],'BUY')
        sim.step(frame(1,'.07'));sim.step(frame(2,'.08',spread='.001'));sim.step(frame(3,'.09'))
        self.assertEqual(sim.order['side'],'BUY');self.assertEqual(sim.metrics['cycles'],0)
        self.assertEqual(sim.by_entry_side['BUY']['started'],1);self.assertEqual(sim.by_entry_side['SELL']['started'],0)

    def test_alternating_flips_after_each_completed_cycle_and_weighted_rule_rechecks_only_then(self):
        a=start('ROUNDTRIP_ALTERNATING');r=start()
        complete(a,1);complete(r,1)
        self.assertEqual(a.wallet,r.wallet);self.assertEqual(a.metrics['fees_btc'],r.metrics['fees_btc'])
        self.assertEqual(a.order['side'],'SELL');self.assertEqual(r.order['side'],'BUY')
        complete(a,3)
        self.assertEqual(a.order['side'],'BUY');self.assertEqual(a.metrics['cycles'],2)
        self.assertEqual(a.snapshot()['original'],r.snapshot()['original'])

    def test_by_side_counts_duration_net_and_fees_reconcile_in_both_fee_scenarios(self):
        for fee in (MAKER,2*MAKER):
            with self.subTest(fee=fee),localcontext() as context:
                context.prec=80
                sim=start('ROUNDTRIP_ALTERNATING',fee=fee);complete(sim,1);complete(sim,3)
                result=sim.snapshot();groups=result['by_entry_side']
                for side,g in groups.items():
                    fills=[r for r in sim.records if r['event']=='CONDITIONAL_BAR_FILL' and r['entry_side']==side]
                    self.assertEqual(g['entered'],1);self.assertEqual(g['completed'],1)
                    self.assertEqual(g['average_days_to_exit'],D(300)/86400)
                    self.assertEqual(g['max_stuck_days'],D(300)/86400);self.assertGreater(g['net_btc'],0)
                    fees=sum(r['fee_btc'] for r in fills)
                    self.assertEqual(g['fees_btc'],fees)
                    gross=sum(r['quantity']*r['price']*(1 if r['side']=='SELL' else -1) for r in fills)
                    self.assertEqual(g['net_btc'],gross-fees);self.assertEqual(g['net_usd'],g['net_btc']*40000)
                for group_key,total_key in (('fees_btc','fees_btc'),('fees_usd','fees_usd'),('net_btc','cycle_profit_btc'),('net_usd','cycle_profit_usd'),('completed','cycles')):
                    self.assertEqual(sum(g[group_key] for g in groups.values()),result[total_key])
                self.assertEqual(groups['BUY']['started'],2);self.assertEqual(groups['BUY']['open_entry'],1)
                self.assertEqual(groups['SELL']['started'],1);self.assertEqual(groups['SELL']['open_entry'],0)

    def test_open_adverse_cycle_is_stuck_exposure_and_not_completed_profit(self):
        sim=start();p=sim.order['price'];sim.step(frame(1,low=str(p-D('.000001'))))
        sim.step(frame(300,'.04'));r=sim.snapshot();g=r['by_entry_side']['BUY']
        self.assertLess(r['advantage_usd'],0);self.assertEqual(g['completed'],0);self.assertEqual(g['net_btc'],0)
        self.assertIsNone(g['average_days_to_exit']);self.assertEqual(g['open_exit'],1)
        self.assertGreater(g['current_stuck_days'],1);self.assertEqual(g['max_stuck_days'],r['max_stuck_days'])
        self.assertGreater(g['fees_btc'],0);self.assertEqual(r['by_entry_side']['SELL']['fees_btc'],0)

    def test_walk_forward_comparison_reuses_training_choices_and_preserves_shared_hold(self):
        frames=[frame(i,'.05' if i<288 else '.04',low='.039') for i in range(864)];calls=[]
        def selection(name,training,rules):
            self.assertNotEqual(name,'ROUNDTRIP_ALTERNATING')
            calls.append((name,training[-1]['at']));return grid(name)[-1]
        with patch('v106.backtest.choose',selection):result=study(frames,RULES,train_days=1,test_days=1)
        self.assertEqual(len(calls),(len(STRATEGIES)-1)*len(result['windows']))
        for w in result['windows']:
            r=w['results']['ROUNDTRIP'];a=w['results']['ROUNDTRIP_ALTERNATING']
            self.assertEqual(r['selected_params'],a['selected_params'])
            self.assertEqual(sum(g['completed'] for g in a['by_entry_side'].values()),a['cycles'])
            self.assertEqual(sum(g['fees_usd'] for g in a['by_entry_side'].values()),a['fees_usd'])
        hold=result['strategies']['HOLD50'];self.assertEqual(hold['advantage_usd'],0);self.assertEqual(hold['fees_usd'],0)
        for name in ('ROUNDTRIP','ROUNDTRIP_ALTERNATING'):
            r=result['strategies'][name];self.assertEqual(r['original'],hold['original'])
            self.assertIn('BUY',r['stress_by_entry_side']);self.assertIn('SELL',r['stress_by_entry_side'])
        report=render(result)
        for term in ('ROUNDTRIP_ALTERNATING','BUY-first','SELL-first','Current stuck days','1.0% stress'):
            self.assertIn(term,report)

    def test_alternating_has_no_independent_optimizer(self):
        with self.assertRaisesRegex(ValueError,'no alternating parameter search'):
            choose('ROUNDTRIP_ALTERNATING',[frame(0)],RULES)


if __name__=='__main__':unittest.main()
