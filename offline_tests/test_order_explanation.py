from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_order_explanation import construct,explain,reported_manual_example,minimum_budget
from coincat_intelligent_policy import seed
from coincat_multi_policy import MultiConfig
from coincat_execution_limits import native_math
from coincat_beta_store import BetaBlocked
from offline_tests.multi_fixtures import Clock,predictions,observed

class Construction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Clock();cls.f=observed(cls.c,predictions(cls.c))
    def setUp(self):self.wallet=seed(self.f,self.c.wall(),MultiConfig())['wallet']
    @native_math
    def test_all_in_btc_budget_is_converted_to_native_eth_base_size_with_fee_once(self):
        budget=D('.00014');r=construct(self.f,self.wallet,'ETH-BTC','BUY',budget)
        self.assertEqual((r['source'],r['target']),('BTC','ETH'));q,p=r['ticket']['size'],r['ticket']['price']
        self.assertEqual(r['source_debit'],q*p*(1+D('.005')));self.assertLessEqual(r['source_debit'],budget)
        self.assertLess(budget-r['source_debit'],D('.000001')*p*(1+D('.005')))
        self.assertEqual(r['estimated_destination'],q);self.assertEqual(r['estimated_commission'],q*p*D('.005'))
    def test_sell_source_budget_stays_in_eth_and_fee_is_subtracted_from_btc_proceeds(self):
        r=construct(self.f,self.wallet,'ETH-BTC','SELL',D('.001'))
        self.assertEqual(r['source_debit'],D('.001'));self.assertEqual(r['fee_currency'],'BTC')
        self.assertEqual(r['estimated_destination'],r['ticket']['size']*r['ticket']['price']-r['estimated_commission'])
    def test_valid_native_ticket_is_not_an_economic_qualification_or_live_authority(self):
        f=deepcopy(self.f);f['horizon_forecasts']={};budget=minimum_budget(f,'ETH-BTC','BUY')
        r=explain(f,self.wallet,self.wallet,self.wallet,'ETH-BTC','BUY',budget)
        self.assertEqual(r['validity']['state'],'NATIVE_RULES_AND_FUNDS_PASS');self.assertEqual(r['economics']['state'],'HOLD')
        self.assertFalse(r['authorization']['automatic_live_authority']);self.assertEqual(len(r['horizons']),6)
    def test_minimum_and_insufficient_budget_do_not_silently_enlarge_source_allocation(self):
        budget=minimum_budget(self.f,'ETH-BTC','BUY')
        construct(self.f,self.wallet,'ETH-BTC','BUY',budget)
        with self.assertRaises(BetaBlocked):construct(self.f,self.wallet,'ETH-BTC','BUY',budget/2)
    def test_reported_historical_fill_does_not_invent_original_decision_or_exact_commission(self):
        row=reported_manual_example();self.assertIsNone(row['actual_unrounded_commission']);self.assertEqual(row['actual_settlement'],'UNKNOWN')
        self.assertIn('NOT_CAPTURED',row['economics']);self.assertIn('NOT_A_FILL_PROBABILITY',row['execution'])
        self.assertEqual(row['computed_gross_btc'],D('.00496514')*D('.028457'))
