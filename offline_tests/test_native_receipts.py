"""Full native sizing and W-only ranking through the canonical receipt path."""
from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_full_balance import rank_full_balances
from coincat_v80_immediate import _frame

NOW=1800000000


def market():
    quotes={'BTC-USD':(D('50000'),D('50000.01'),NOW),
            'ETH-USD':(D('2600'),D('2600.01'),NOW),
            'ETH-BTC':(D('.051199'),D('.0512'),NOW)}
    rules={p:dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
        base_min_size='.00000001',quote_min_size='.00000001',quote_increment='.00000001') for p in quotes}
    return quotes,rules


def scan(qty='.002',*,quotes=None,rules=None,balances=None,**changes):
    q,r=market();args=dict(balances={'BTC':D(qty)} if balances is None else balances,
        catalog=list(quotes if quotes is not None else q),rules=rules if rules is not None else r,
        quotes=quotes if quotes is not None else q,fee_rate=D('.009'),now=NOW,balances_at=NOW)
    args.update(changes);return rank_full_balances(**args)


class FullBalancePolicy(unittest.TestCase):
    def test_one_full_size_per_direction_exact_residual_and_fee_once(self):
        r=scan();best=r['best']
        self.assertEqual((best['pair'],best['side']),('ETH-BTC','BUY'))
        self.assertEqual(best['available'],D('.002'))
        self.assertEqual(best['spent']+best['residual'],D('.002'))
        self.assertLess(best['residual'],D('.00000001')*D('.0512')*D('1.0015')*D('1.009')+D('.00000001'))
        self.assertEqual(len({(i['pair'],i['side']) for i in r['ranked']}),len(r['ranked']))
        f=best['frame'];step=f['idea']['shadow_fifo_steps'][0]
        self.assertEqual(best['w'],step['output_quantity']*f['target_rate']-step['input_quantity']*f['source_rate'])
        self.assertEqual(len(f['orders']),1)
        self.assertIsNone(f['l'])
        self.assertFalse(r['live_order_permission'])

    def test_positive_cents_do_not_need_ten_cent_floor(self):
        r=scan(qty='.0001')
        self.assertGreater(r['best']['w'],0);self.assertLess(r['best']['w'],D('.10'))

    def test_large_native_holding_has_no_five_or_hundred_dollar_cap(self):
        r=scan(qty='2')
        self.assertEqual(r['best']['available'],D(2))
        self.assertGreater(r['best']['spent'],D('1.999'))
        self.assertGreater(r['best']['frame']['orders'][0]['approx_usd_notional'],D('99900'))

    def test_rank_is_greatest_usd_advantage_not_lowest_cost_or_future_signal(self):
        q,r=market();q.update({'SOL-BTC':(D('.0002499'),D('.00025'),NOW),
                             'SOL-USD':(D('12.9'),D('12.9001'),NOW)})
        for p in ('SOL-BTC','SOL-USD'):r[p]=dict(r['ETH-BTC'],product_id=p)
        result=scan(quotes=q,rules=r)
        self.assertEqual(result['best']['pair'],'SOL-BTC')
        self.assertEqual(result['best']['w'],max(i['w'] for i in result['ranked']))

    def test_all_nonpositive_routes_hold_without_size_search(self):
        q,r=market();q['ETH-USD']=(D(2500),D('2500.01'),NOW)
        result=scan(quotes=q,rules=r)
        self.assertIsNone(result['best']);self.assertEqual(result['state'],'HOLD')
        self.assertTrue(all(i['w']<=0 for i in result['ranked']))

    def test_product_maximum_blocks_full_size_instead_of_fitting_smaller(self):
        q,r=market();r['ETH-BTC']['base_max_size']='.001'
        result=scan(quotes=q,rules=r)
        self.assertFalse(any(i['pair']=='ETH-BTC' for i in result['ranked']))
        self.assertGreater(result['blockers']['FULL_SIZE_PRODUCT_OR_FRAME_BLOCK'],0)

    def test_minimum_blocks_tiny_holding_instead_of_increasing_it(self):
        q,r=market();r['ETH-BTC']['quote_min_size']='.1'
        result=scan(quotes=q,rules=r)
        self.assertFalse(any(i['pair']=='ETH-BTC' for i in result['ranked']))
        self.assertIsNone(result['best'])

    def test_sell_rounding_retains_native_dust(self):
        r=scan(balances={'ETH':D('.123456789')})
        sell=next(i for i in r['ranked'] if i['pair']=='ETH-USD' and i['side']=='SELL')
        self.assertEqual(sell['spent'],D('.12345678'))
        self.assertEqual(sell['residual'],D('.000000009'))

    def test_missing_fx_and_skew_are_unpriced_not_losses(self):
        q,r=market();q['ETH-USD']=(D(2600),D('2600.01'),NOW-17)
        result=scan(quotes=q,rules=r)
        self.assertIn('PRICE_SKEW',result['blockers'])
        self.assertFalse(any(i['pair']=='ETH-BTC' for i in result['ranked']))
        del q['ETH-USD'];result=scan(quotes=q,rules=r)
        self.assertIn('CIRCULAR_WALLET_MARK_PATH',result['blockers'])

    def test_stale_balance_unknown_fee_and_disabled_products_do_not_rank(self):
        self.assertEqual(scan(balances_at=NOW-121)['reason'],'AVAILABLE_BALANCES_STALE_OR_UNOBSERVED')
        self.assertEqual(scan(fee_rate=None)['reason'],'FEE_ESTIMATE_UNAVAILABLE')
        q,r=market();r['ETH-BTC']['view_only']=True
        result=scan(quotes=q,rules=r)
        self.assertFalse(any(i['pair']=='ETH-BTC' for i in result['ranked']))

    def test_explicit_exclusions_are_preserved(self):
        self.assertEqual(scan(excluded={'BTC'})['eligible_directions'],0)
        result=scan(excluded={'ETH'})
        self.assertFalse(any(i['target']=='ETH' for i in result['ranked']))

    def test_canonical_frame_still_supports_comparable_liquidation_for_other_callers(self):
        r=scan();f=r['best']['frame'];q,rules=market()
        full=_frame(f['idea'],q,rules,NOW)
        self.assertIsNotNone(full['l'])
        self.assertEqual(full['w'],f['w'])
        self.assertEqual(f['books'],full['books'])

    def test_direct_usd_sale_cannot_gain_by_weakening_source_hold_mark(self):
        q,r=market();q['ETH-USD']=(D(2500),D('2500.01'),NOW)
        result=scan(quotes=q,rules=r)
        sale=next(row for row in result['ranked'] if row['pair']=='BTC-USD')
        self.assertEqual(sale['frame']['source_rate'],D(50000))
        self.assertLess(sale['w'],0)
        self.assertIsNone(result['best'])

    def test_ranking_is_independent_of_catalog_iteration_and_ai_history(self):
        q,r=market();args=dict(balances={'BTC':D('.002')},rules=r,quotes=q,fee_rate=D('.009'),now=NOW,balances_at=NOW)
        a=rank_full_balances(catalog=list(q),**args)
        b=rank_full_balances(catalog=list(reversed(q)),**args)
        self.assertEqual([(i['pair'],i['w']) for i in a['ranked']],[(i['pair'],i['w']) for i in b['ranked']])
