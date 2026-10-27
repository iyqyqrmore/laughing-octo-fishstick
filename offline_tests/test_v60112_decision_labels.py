"""v60.12 presenter + eligibility checks; do not access network, orders or user data."""
import unittest
from decimal import Decimal
from coincat_v60112_decision_display import (history_percent,cost_drag_percent,
  decision_label,reason_tooltip,known_small_direct_buy)
from coincat_v502_relative_learning import evaluate_hold_switch

class DecisionLabels(unittest.TestCase):
    def test_history_requires_time_as_well_as_observations(self):
        self.assertEqual(history_percent({'evidence_windows':35,'evidence_span_days':0}),0)
        self.assertEqual(history_percent({'evidence_windows':35,'evidence_span_days':'3.5'}),50)
        self.assertEqual(history_percent({'evidence_windows':35,'evidence_span_days':'7'}),100)
        self.assertEqual(history_percent({'evidence_windows':10,'evidence_span_days':'7'}),28)
        self.assertEqual(history_percent({'evidence_windows':7000}),0)
        self.assertEqual(decision_label({'research_decision':'STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED','evidence_windows':35,'evidence_span_days':7}), 'History 100%')
    def test_history_is_never_probability_or_auto_permission(self):
        item={'research_decision':'STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED','evidence_windows':35,'evidence_span_days':7}
        tip=reason_tooltip(item)
        self.assertIn('NOT probability of profit',tip)
        self.assertIn('validation',tip)
        self.assertNotIn('filled',tip.lower())
    def test_costs_ceil_to_tenths_not_double_counted(self):
        idea={'research_decision':'HOLD_PREFERRED','initial_wallet_usd_mark':Decimal('100'),
            'immediate_change_usd':Decimal('-0.111'), 'net_mean_usd':Decimal('-0.15')}
        self.assertEqual(cost_drag_percent(idea),Decimal('0.2'))
        self.assertEqual(decision_label(idea),'Costs 0.2%')
        self.assertIn('immediate wallet-value',reason_tooltip(idea))
        self.assertEqual(decision_label({'research_decision':'HOLD_PREFERRED'}),'Hold')
    def test_ready_yes_no_is_not_fill(self):
        idea={'research_decision':'SWITCH_WORTH_RESEARCH'}
        self.assertEqual(decision_label(idea,shadow_armed=False,delivered_to_shadow=True),'S.Ready - N')
        self.assertEqual(decision_label(idea,shadow_armed=True,delivered_to_shadow=False),'S.Ready - N')
        self.assertEqual(decision_label(idea,shadow_armed=True,delivered_to_shadow=True),'S.Ready - Y')
        self.assertIn('does not mean it filled',reason_tooltip(idea,shadow_armed=True,delivered_to_shadow=True))
    def test_small_minimum_is_known_and_funded(self):
        now=20000
        rules={'ADA-USDC':{'quote_min_size':'5','base_min_size':'1.0'}}
        enrolled=[{'asset':'USDC','remaining_qty':'2.0','enabled':1}]
        balances={'USDC':'3.0'}
        books={'ADA-USDC':('1','1.01',now)}
        reason=known_small_direct_buy('ADA-USDC',rules,enrolled,balances,books,now=now)
        self.assertIn('at least 5 USDC',reason)
        self.assertIsNone(known_small_direct_buy('ADA-USDC',rules,[{'asset':'USDC','remaining_qty':'6','enabled':1}],{'USDC':'6'},books,now=now))
        self.assertIsNone(known_small_direct_buy('ADA-USDC',rules,enrolled,balances,{},now=now))
        self.assertIsNone(known_small_direct_buy('ADA-USDC',rules,[{'asset':'USDC','remaining_qty':'2','enabled':0}],balances,books,now=now))
        self.assertIsNone(known_small_direct_buy('ADA-USDC',{},enrolled,balances,books,now=now))
    def test_recheck_is_catalog_only_and_respects_arm(self):
        from coincat_app import CoinCatApp
        class Broker:
            armed=False
            def catalog(self):return ['ADA-USDC','SOL-BTC']
        class Probe:
            broker=Broker()
            catalog=['ADA-USDC']
            worker_busy=False
            _connection_requested=False
            _connection_in_progress=False
            _portfolio_sync_running=False
            _last_catalog_refresh_attempt=0.0
            portfolio_sync_status=type('Status',(),{'set':lambda self,value:None})()
            seen=None
            def _async(self,task,operation=''):
                self.seen=(operation,task())
                return True
        x=Probe()
        self.assertTrue(CoinCatApp._recheck_excluded_pairs(x))
        self.assertEqual(x.seen[0],'catalog recheck')
        self.assertEqual(x.seen[1]['catalog'],['ADA-USDC','SOL-BTC'])
        x.broker.armed=True
        x.seen=None
        self.assertFalse(CoinCatApp._recheck_excluded_pairs(x))
        self.assertIsNone(x.seen)
        # The only authenticated call is products, never the ledger or balances.
        import inspect
        code=inspect.getsource(CoinCatApp._recheck_excluded_pairs)
        self.assertIn('self.broker.catalog()',code)
        self.assertNotIn('self.ledger.',code)
        self.assertNotIn('self.broker.balances()',code)
        self.assertNotIn('self._refresh_portfolio_live(',code)

    def test_only_real_catalog_pairs_eligible_for_active_one_order_research(self):
        from coincat_v6010_registry import one_order_catalog
        cat=['ADA-USDC','SOL-BTC']
        self.assertEqual(one_order_catalog(cat,{}),cat)
        self.assertNotIn('SOL-ADA',one_order_catalog(cat,{}))
        self.assertEqual(one_order_catalog(['SOL-ADA'],{'SOL-ADA':{'product_id':'SOL-ADA',
                      'product_type':'SPOT','trading_disabled':True}}),[])

    def test_no_rewrite_of_evidence_or_risk_gate(self):
        idea={'initial_wallet_usd_mark':100,'post_route_wallet_usd_mark':99,
              'input_units_planned':1,'source_units':1}
        evidence={'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':30,'span_days':Decimal('7')}
        r=evaluate_hold_switch(idea,evidence)
        self.assertEqual(r['research_decision'],'HOLD_UNTIL_VERIFIED')
        self.assertFalse(r['oos_validated'])
        self.assertEqual(history_percent(r),85)
        self.assertEqual(decision_label(dict(idea,**r)),'History 85%')

if __name__=='__main__':unittest.main()
