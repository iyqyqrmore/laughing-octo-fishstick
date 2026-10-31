"""Native-only cycle economics; no network, orders or account quantities."""
from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_eth_evaluator import enumerate_cycles, evaluate_cycle, rank_cycles, public_cycle_report

NOW = 1800000000
CYCLE = (('ETH-AA','SELL','ETH','AA'), ('AA-BB','SELL','AA','BB'),
         ('BB-ETH','SELL','BB','ETH'))


def inputs():
    quotes = {p: (D(1), D(1), NOW) for p, *_ in CYCLE}
    quotes['BB-ETH'] = (D('1.1'), D('1.1'), NOW)
    rules = {p: dict(product_id=p, product_type='SPOT', status='online',
        base_increment='1e-40', base_min_size='1e-40', quote_min_size='1e-40') for p in quotes}
    return dict(starting_eth=D(1), catalog=list(quotes), rules=rules, quotes=quotes,
                now=NOW, balances_at=NOW)


class NativeCycles(unittest.TestCase):
    def test_simple_cycles_orientations_deduplication_and_no_usd_dependency(self):
        x=inputs(); inv=enumerate_cycles(catalog=x['catalog']*2, rules=x['rules'])
        self.assertEqual(len(inv['cycles']), 2)
        self.assertIn(CYCLE, inv['cycles']); self.assertTrue(inv['coverage_complete'])
        for cycle in inv['cycles']:
            self.assertEqual(len({leg[0] for leg in cycle}), len(cycle))
            self.assertEqual(cycle[0][2], 'ETH'); self.assertEqual(cycle[-1][3], 'ETH')

    def test_retracing_tree_has_no_genuine_cycles(self):
        x=inputs(); del x['rules']['BB-ETH']
        self.assertEqual(enumerate_cycles(catalog=x['catalog'], rules=x['rules'])['cycles'], [])

    def test_native_receipts_cost_every_leg_once_and_rank_without_usd(self):
        x=inputs(); old=deepcopy(x); r=evaluate_cycle(cycle=CYCLE, **x)
        self.assertEqual(r['state'], 'MODELED_UNVERIFIED')
        factor=D('.9985')*D('.991')
        self.assertEqual(r['final_eth'], D('1.1')*factor**3)
        self.assertEqual(r['net_additional_eth'], r['final_eth']-D(1))
        self.assertEqual(len(r['receipts']), 3)
        self.assertTrue(all('approx_usd_notional' not in row for row in r['receipts']))
        self.assertFalse(r['live_order_permission']); self.assertFalse(r['execution_eligible'])
        self.assertEqual(x, old)
        self.assertEqual(rank_cycles(**x)['best_positive']['cycle'], CYCLE)

    def test_no_edge_is_a_valid_research_result(self):
        x=inputs(); x['quotes']['BB-ETH']=(D(1), D(1), NOW)
        self.assertIsNone(rank_cycles(**x)['best_positive'])
        self.assertLess(evaluate_cycle(cycle=CYCLE, **x)['net_additional_eth'], 0)

    def test_product_maximum_rejects_full_size_without_fit(self):
        x=inputs(); x['rules']['ETH-AA']['base_max_size']='.1'
        r=evaluate_cycle(cycle=CYCLE, **x)
        self.assertEqual(r['state'], 'BLOCKED'); self.assertIsNone(r['final_eth'])
        self.assertIn('ABOVE_BASE_MAXIMUM:ETH-AA', r['blockers'])

    def test_non_eth_dust_remains_unknown(self):
        x=inputs(); x['rules']['AA-BB']['base_increment']='.01'
        r=evaluate_cycle(cycle=CYCLE, **x)
        self.assertIn('AA', r['residuals']); self.assertIsNone(r['net_additional_eth'])
        self.assertIn('UNCONVERTED_NATIVE_RESIDUE', r['blockers'])

    def test_all_quote_failures_visible_and_cycle_skew_separate(self):
        x=inputs(); del x['quotes']['ETH-AA']; x['quotes']['AA-BB']=(D(1), D(1), NOW-31)
        r=evaluate_cycle(cycle=CYCLE, **x)
        self.assertEqual(set(r['blockers']), {'QUOTE_UNOBSERVED:ETH-AA','QUOTE_STALE:AA-BB'})
        x=inputs(); x['quotes']['AA-BB']=(D(1), D(1), NOW-13)
        self.assertEqual(evaluate_cycle(cycle=CYCLE, **x)['blockers'], ['CYCLE_QUOTE_SKEW'])

    def test_exclusions_stale_balances_and_future_quotes_fail_closed(self):
        x=inputs(); x['excluded']={'AA'}
        self.assertFalse(rank_cycles(**x)['results'])
        self.assertTrue(evaluate_cycle(cycle=CYCLE, **x)['blockers'])
        x=inputs(); x['balances_at']=NOW-121
        self.assertIsNone(evaluate_cycle(cycle=CYCLE, **x)['final_eth'])
        x=inputs(); x['quotes']['ETH-AA']=(D(1),D(1),NOW+1)
        self.assertIn('QUOTE_FUTURE:ETH-AA',evaluate_cycle(cycle=CYCLE, **x)['blockers'])

    def test_search_bounds_report_incomplete_coverage(self):
        x=inputs(); inv=enumerate_cycles(catalog=x['catalog'],rules=x['rules'],max_expansions=1)
        self.assertTrue(inv['truncated']); self.assertFalse(inv['coverage_complete'])

    def test_invalid_topology_and_exact_financial_inputs(self):
        x=inputs()
        self.assertEqual(evaluate_cycle(cycle=CYCLE[:2], **x)['state'], 'BLOCKED')
        x['starting_eth']=1.0
        self.assertIsNone(evaluate_cycle(cycle=CYCLE, **x)['final_eth'])

    def test_public_report_excludes_quantities_and_receipts(self):
        r=public_cycle_report(rank_cycles(**inputs()))
        self.assertEqual(r['cycles_reviewed'], 2)
        self.assertGreater(r['positive_modeled_cycles'], 0)
        for row in r['candidates']:
            self.assertEqual(set(row), {'route','state','blockers','evidence'})
        self.assertFalse(r['execution_eligible'])
