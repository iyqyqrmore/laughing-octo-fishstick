"""Synthetic ETH-funded topology; all market directions, no trading claims."""
import unittest
from coincat_eth_cycles import eth_cycle_inventory
from offline_tests.test_native_receipts import market


def inventory(products,**changes):
    _,template=market()
    rules={p:dict(template['BTC-USD'],product_id=p) for p in products}
    return eth_cycle_inventory(catalog=products,rules=changes.pop('rules',rules),sample_limit=100,**changes)


class ETHCycles(unittest.TestCase):
    def test_every_approved_direction_is_classified_and_every_cycle_has_eth_endpoints(self):
        products=['VET-ETH','VET-BTC','ETH-BTC','ETH-USD']
        out=inventory(products)
        self.assertEqual(out['directions_checked'],8)
        self.assertEqual(out['bounded_eth_cycles'],8)
        self.assertTrue(out['all_directions_classified'])
        self.assertEqual(len(out['direction_results']),out['directions_checked'])
        self.assertEqual(len({(r['product'],r['side']) for r in out['direction_results']}),8)
        for route in out['cycle_examples']:
            self.assertEqual((route['assets'][0],route['assets'][-1]),('ETH','ETH'))
            self.assertNotIn('ETH',route['assets'][1:-1])
            self.assertEqual(len(route['legs']),route['total_legs'])
            self.assertLessEqual(route['total_legs'],5)
            for n,leg in enumerate(route['legs']):
                self.assertIn(leg['product'],products)
                base,quote=leg['product'].split('-')
                self.assertEqual((leg['source'],leg['target']),
                    (base,quote) if leg['side']=='SELL' else (quote,base))
                self.assertEqual((leg['source'],leg['target']),tuple(route['assets'][n:n+2]))
        self.assertFalse(out['eth_profit_selection_enabled']);self.assertFalse(out['live_order_permission'])

    def test_eth_can_fund_new_coin_and_vet_btc_can_be_an_intermediate_leg(self):
        out=inventory(['VET-ETH','VET-BTC','ETH-BTC'])
        direct=next(r for r in out['cycle_examples'] if (r['product'],r['side'])==('VET-ETH','BUY'))
        self.assertEqual(direct['assets'],['ETH','VET','ETH'])
        cross=next(r for r in out['cycle_examples'] if (r['product'],r['side'])==('VET-BTC','SELL'))
        self.assertEqual(cross['assets'],['ETH','VET','BTC','ETH'])
        self.assertEqual(cross['total_legs'],3)  # All three legs would need costs, not only the cross swap.
        self.assertEqual(out['costs_and_native_sizing'],'UNVERIFIED')

    def test_disconnected_and_connected_beyond_model_are_distinct_and_not_fabricated(self):
        out=inventory(['ETH-AA','AA-BB','BB-CC','XX-YY'])
        self.assertEqual(out['directions_checked'],8)
        self.assertEqual(out['disconnected_directions'],2)
        self.assertGreater(out['beyond_bridge_model_directions'],0)
        self.assertEqual(out['bounded_eth_cycles']+out['beyond_bridge_model_directions']+
                         out['disconnected_directions'],out['directions_checked'])
        self.assertEqual(len(out['direction_results']),out['directions_checked'])
        reasons={r['reason'] for r in out['blocked_examples']}
        self.assertEqual(reasons,{'NO_ETH_CONNECTION_IN_APPROVED_CATALOG','CONNECTED_BUT_BEYOND_TWO_LEG_BRIDGE_MODEL'})

    def test_restrictions_exclusions_and_missing_eth_market_are_honored(self):
        _,template=market();products=['VET-ETH','VET-BTC','ETH-BTC']
        rules={p:dict(template['BTC-USD'],product_id=p) for p in products}
        rules['VET-ETH']['trading_disabled']=True
        out=inventory(products,rules=rules,excluded={'BTC'})
        self.assertEqual(out['approved_markets'],0)
        self.assertEqual(out['cycle_examples'],[])
        disconnected=inventory(['VET-BTC'])
        self.assertEqual(disconnected['bounded_eth_cycles'],0)
        self.assertEqual(disconnected['disconnected_directions'],2)

    def test_examples_are_bounded_and_do_not_contain_quantities_or_imply_execution(self):
        out=eth_cycle_inventory(catalog=market()[0],rules=market()[1],sample_limit=1)
        self.assertLessEqual(len(out['cycle_examples']),1)
        self.assertLessEqual(len(out['blocked_examples']),1)
        self.assertEqual(out['funding_authorization'],'NOT_ESTABLISHED_BY_TOPOLOGY')
        for row in out['cycle_examples']:
            for leg in row['legs']:
                self.assertEqual(set(leg),{'product','side','source','target'})
        self.assertFalse(out['live_order_permission'])
