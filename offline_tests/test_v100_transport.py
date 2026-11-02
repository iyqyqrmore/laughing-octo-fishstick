"""Retained shared GET-budget and collector-error regressions."""
from decimal import Decimal as D
import unittest
from coincat_v701_transport import GetBudget,QuoteDeferred,QuoteSnapshot,ScoutCollector
from offline_tests.test_native_receipts import NOW

class Transport(unittest.TestCase):

    def test_public_get_rate_and_retry_after_are_preserved(self):
        clock=[0.0];budget=GetBudget(clock=lambda:clock[0]);times=[]
        def sleep(seconds):clock[0]+=seconds
        for i in range(16):
            budget.acquire(6,sleep=sleep);times.append(clock[0])
        self.assertAlmostEqual(times[-1],3)
        self.assertTrue(all(b-a>=.199999 for a,b in zip(times,times[1:])))
        budget.postpone('120')
        with self.assertRaises(QuoteDeferred):budget.acquire(6,sleep=sleep)
        self.assertGreaterEqual(budget.blocked_until,123)


    def test_collector_attributes_error_classes_without_exporting_messages(self):
        import requests
        def fetch(pair,**kwargs):
            if pair=='BTC-USD':raise ValueError('SENSITIVE_TEST_MESSAGE')
            if pair=='SOL-USD':
                response=requests.Response();response.status_code=503
                raise requests.HTTPError('SENSITIVE_TEST_MESSAGE',response=response)
            return QuoteSnapshot(pair,D(100),D('100.01'),NOW,NOW,1)
        got,errors,elapsed=ScoutCollector().collect(['BTC-USD','ETH-USD','SOL-USD'],fetch=fetch)
        self.assertEqual(set(got),{'ETH-USD'})
        self.assertEqual(dict(errors),{'ValueError':1,'HTTP_503':1})
        self.assertEqual(errors.by_product,{'BTC-USD':'ValueError','SOL-USD':'HTTP_503'})
        self.assertNotIn('SENSITIVE_TEST_MESSAGE',str(errors))
