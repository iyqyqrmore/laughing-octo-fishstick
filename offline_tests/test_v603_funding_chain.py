"""V60.3: per-asset fail-open-to-other-funding research; ALL trading fails closed.
Only disposable mocks and public artificial prices, never Coinbase API or ledgers.
"""
import unittest
from decimal import Decimal
from coincat_v60_research_sizing import funding_inventory_snapshot,available_enrolled_usd_ceiling
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_relative_strength_research import rank_observed_markets
from coincat_shadow_diagnostics import shadow_snapshot,make_shadow_report

TS=1800000000
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'0.01'}
CAT=['BTC-USD','USDC-USD','ETH-USD']
BOOKS={'BTC-USD':('49990','50000',TS),'USDC-USD':('0.9999','1',TS),
       'ETH-USD':('1999','2000',TS)}
HOLDINGS=[{'asset':'USD','remaining_qty':'120','enabled':1},
          {'asset':'USDC','remaining_qty':'80','enabled':1},
          {'asset':'UNVALUED','remaining_qty':'500','enabled':1},
          {'asset':'EXCLUDED','remaining_qty':'10','enabled':0}]
BALANCES={'USD':'120','USDC':'80','UNVALUED':'500','EXCLUDED':'10'}

class FundingEligibility(unittest.TestCase):
    def test_unpriced_enrolled_coin_does_not_zero_verified_other_funding(self):
        snap=funding_inventory_snapshot(HOLDINGS,BALANCES,BOOKS,CAT,now=TS)
        self.assertEqual(snap['eligible_count'],2)
        self.assertEqual(snap['ineligible_count'],1)
        self.assertTrue(snap['partial'])
        self.assertGreater(snap['funding_usd'],Decimal('199'))
        self.assertEqual(snap['ineligible_reasons']['STALE_OR_WIDE_USD_BOOK'],1)
        self.assertEqual(available_enrolled_usd_ceiling(HOLDINGS,BALANCES,BOOKS,CAT,now=TS),snap['funding_usd'])
        self.assertEqual({x['asset'] for x in snap['eligible']},{'USD','USDC'})
    def test_invalid_and_unavailable_never_fabricate_funding(self):
        data=[{'asset':'USD','remaining_qty':'NaN','enabled':1},
              {'asset':'BTC','remaining_qty':'1','enabled':1}]
        snap=funding_inventory_snapshot(data,{'USD':'100','BTC':'0'},BOOKS,CAT,now=TS)
        self.assertEqual(snap['funding_usd'],0)
        self.assertEqual(snap['ineligible_reasons']['INVALID_QUANTITY'],1)
        self.assertEqual(snap['ineligible_reasons']['NO_VERIFIED_AVAILABLE_BALANCE'],1)
    def test_stale_or_too_wide_book_excludes_only_that_source(self):
        books=dict(BOOKS,**{'USDC-USD':('0.80','1.00',TS)})
        snap=funding_inventory_snapshot(HOLDINGS,BALANCES,books,CAT,now=TS)
        self.assertEqual([x['asset'] for x in snap['eligible']],['USD'])
        self.assertEqual(snap['funding_usd'],Decimal('120'))

class AIResearchChain(unittest.TestCase):
    def run_screen(self,exploration=()):
        return auto_rotation_screen(buy_signals=[],exploratory_candidates=exploration,
            holdings=HOLDINGS,verified_balances=BALANCES,balance_age_s=10,
            catalog=CAT,quotes=BOOKS,product_rules={x:RULE for x in CAT},
            usd_per_order_cap=Decimal('100000'),now=TS,
            fee_rates_by_pair={x:Decimal('.009') for x in CAT},
            minimum_net_advantage_usd='0.10')
    def test_zero_buy_still_reaches_funded_exploratory_rotation_without_trade(self):
        result=self.run_screen([{'pair':'BTC-USD','momentum_pct':'0.28'}])
        self.assertEqual(result['funding_assets'],2)
        self.assertEqual(result['funding_unpriceable'],1)
        self.assertGreater(result['exploratory_route_attempts'],0)
        self.assertGreater(result['exploratory_viable_routes'],0)
        self.assertEqual(result['state'],'WAIT')
        self.assertGreater(result['exploratory_shortlist'],0)
        self.assertTrue(all(i['research_decision']=='NOT_BUY_QUALIFIED' for i in result['ideas']))
        self.assertTrue(all(i['oos_validated'] is False and i['sends_live_orders'] is False for i in result['ideas']))
        self.assertEqual(result['threshold_research']['qualified_predictions'],0)
        self.assertEqual(shadow_snapshot({'signals':[], 'auto_rotation':result},captured_at=TS)['state'],'WAIT')
    def test_no_fee_or_bad_rules_cannot_become_qualified_shadow(self):
        result=auto_rotation_screen(buy_signals=[],exploratory_candidates=[{'pair':'BTC-USD','momentum_pct':'1'}],
            holdings=HOLDINGS,verified_balances=BALANCES,balance_age_s=10,
            catalog=CAT,quotes=BOOKS,product_rules={},usd_per_order_cap=Decimal('10000'),now=TS,
            fee_rates_by_pair={})
        self.assertEqual(result['exploratory_viable_routes'],0)
        self.assertEqual(result['state'],'WAIT')
        self.assertEqual(result['ideas'],[])
    def test_observed_market_algorithm_is_rank_only_and_spread_filtered(self):
        ranked=rank_observed_markets([
            {'pair':'BTC-USD','bid':'99.9','ask':'100','count':25,'trend':'0.14'},
            {'pair':'ETH-USD','bid':'99','ask':'100','count':25,'trend':'3'},
            {'pair':'SOL-USD','bid':'99.9','ask':'100','count':25,'trend':'0.35'}],max_targets=2)
        self.assertEqual(ranked['eligible_markets'],2)
        self.assertEqual(ranked['candidates'][0]['pair'],'SOL-USD')
        self.assertTrue(all(x['action']=='EXPLORE_ONLY' for x in ranked['candidates']))
        self.assertNotIn('BUY',str(ranked['candidates']))
    def test_no_price_at_all_produces_zero_not_orders(self):
        result=auto_rotation_screen(buy_signals=[],exploratory_candidates=[{'pair':'BTC-USD','momentum_pct':'1'}],
            holdings=HOLDINGS,verified_balances=BALANCES,balance_age_s=999,
            catalog=CAT,quotes=BOOKS,product_rules={x:RULE for x in CAT},usd_per_order_cap=10,now=TS)
        self.assertEqual(result['state'],'WAIT')
        self.assertFalse(result['ideas'])

if __name__=='__main__':unittest.main()
