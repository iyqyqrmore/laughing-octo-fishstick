"""v50.2 real fee source vs estimated research data; all SDK clients are mocks.
NO Coinbase network, no order POST and all SQLite ledgers disposable.
"""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from coincat_v502_fee_learning import FeeLearning, FeeEvidenceError
from coincat_directional import DirectionalLab
from coincat_gpu_research import collect_two_way_examples, _features, FEATURE_NAMES
from coincat_gpu_advisory import advisory

class ReadOnlyClient:
    def __init__(self,response=None,fail=False):
        self.calls=[]
        self.response=response or {'fee_tier':{'pricing_tier':'Advanced Test Tier','maker_fee_rate':'.006','taker_fee_rate':'.012'}}
        self.fail=fail
    def get_transaction_summary(self,*,product_type):
        self.calls.append(product_type)
        if self.fail:raise RuntimeError('synthetic Coinbase GET failure')
        return self.response
    def market_order_buy(self,*args,**kwargs):
        raise AssertionError('No order submissions allowed')

class FauxStore:
    def __init__(self,path):self.path=path
    @contextmanager
    def _db(self):
        # Mirror ForwardStore's transaction AND explicit connection cleanup.
        db=sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

class FeeLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.fee=FeeLearning(self.path/'fee.sqlite3')

    def test_fake_forward_store_closes_connection_on_context_exit(self):
        store=FauxStore(self.path/'closed.sqlite3')
        with store._db() as db:
            db.execute('CREATE TABLE demo(x INTEGER)')
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
    def test_hourly_get_tier_only_and_research_cache(self):
        c=ReadOnlyClient()
        self.assertEqual(self.fee.refresh_from_client(c,now=1000000)['status'],'VERIFIED')
        self.assertEqual(c.calls,['SPOT'])
        self.assertEqual(self.fee.refresh_from_client(c,now=1000010)['status'],'NOT_DUE')
        self.assertEqual(c.calls,['SPOT'])
        r=self.fee.account_cost('ETH-BTC',now=1000100)
        self.assertTrue(r['fresh']);self.assertEqual(r['taker'],Decimal('.012'))
        self.assertFalse(r['pair_verified'])
        self.assertEqual(self.fee.account_cost('ETH-DAI',now=1000100)['taker'],Decimal('.012'))
        self.assertFalse(self.fee.account_cost('ETH-BTC',now=1009000)['fresh'])
        self.assertEqual(self.fee.refresh_from_client(c,now=1003700)['status'],'VERIFIED')
        self.assertEqual(c.calls,['SPOT','SPOT'])

    def test_bad_response_rejected_does_not_create_false_verified_tier(self):
        for raw in ('nan','1.5',float('nan'),None):
            with self.subTest(raw=raw):
                with self.assertRaises(FeeEvidenceError):
                    self.fee.capture_tier({'fee_tier':{'maker_fee_rate':'.006','taker_fee_rate':raw}})
        self.assertFalse(self.fee.latest_tier()['fresh'])

    def test_failed_sdk_refresh_preserves_previous_evidence_but_does_not_authenticate_new(self):
        self.fee.capture_tier({'fee_tier':{'maker_fee_rate':'.002','taker_fee_rate':'.005'}},now=10000)
        bad=ReadOnlyClient(fail=True)
        self.assertEqual(self.fee.refresh_from_client(bad,now=14000)['status'],'UNAVAILABLE')
        self.assertEqual(len(bad.calls),1)
        self.assertEqual(self.fee.refresh_from_client(bad,now=14100)['status'],'NOT_DUE')
        self.assertFalse(self.fee.account_cost('SOL-BTC',now=20000)['fresh'])

    def test_real_fee_sensitive_screen_never_authorizes_trade(self):
        self.fee.capture_tier({'fee_tier':{'maker_fee_rate':'.001','taker_fee_rate':'.009'}},now=50000)
        low=self.fee.research_screen('BTC-USD','.40','8',now=50020)
        high=self.fee.research_screen('BTC-USD','9','8',now=50020)
        self.assertEqual(low['state'],'MOMENTUM_BELOW_COST')
        self.assertEqual(high['state'],'UNVALIDATED_MOMENTUM_ABOVE_COST')
        self.assertFalse(high['trade_authorized'])
        self.assertFalse(high['pair_verified'])

    def test_pair_preview_distinct_from_account_tier_and_expires(self):
        self.fee.capture_pair_preview(pair='ETH-BTC',side='BUY',rate='.004',observed_at=200000)
        self.assertTrue(self.fee.pair_preview('ETH-BTC','BUY',now=200200)['verified'])
        self.assertFalse(self.fee.pair_preview('SOL-USDC','BUY',now=200200)['verified'])
        self.assertFalse(self.fee.pair_preview('ETH-BTC','BUY',now=201000)['verified'])

    def test_fills_require_verified_evidence_idempotent_with_fee_asset(self):
        kw=dict(fingerprint='VERIFIED-FAKE-DIGEST-123456789',pair='ETH-BTC',maker_taker='MAKER',
                fee_currency='BTC',fee_qty='.000000000000001',notional_quote='.003')
        with self.assertRaises(FeeEvidenceError):self.fee.record_confirmed_fill(**kw)
        self.assertEqual(self.fee.record_confirmed_fill(**kw,exchange_evidence_verified=True),'RECORDED')
        self.assertEqual(self.fee.record_confirmed_fill(**kw,exchange_evidence_verified=True),'REPLAY_NOOP')
        with self.assertRaises(FeeEvidenceError):
            self.fee.record_confirmed_fill(**dict(kw,fee_qty='.000000002'),exchange_evidence_verified=True)

    def test_report_redacted_no_private_keys_or_id(self):
        self.fee.capture_tier({'fee_tier':{'maker_fee_rate':'.002','taker_fee_rate':'.005'}},now=9000)
        result=self.fee.report(['ETH-USD','ETH-BTC','SOL-USDT','ETH-BTC'],now=9001)
        self.assertIn('Current authenticated spot pair catalog: 3',result)
        self.assertIn('Account tier alone is not proof',result)
        self.assertNotIn('apiKeys',result)
        self.assertNotIn(str(self.path),result)

    def test_neural_features_require_point_in_time_fee_evidence(self):
        self.assertIn('spot_taker_fee_bps_at_entry',FEATURE_NAMES)
        with self.assertRaises(ValueError):_features(1000000,'1','1.01')
        self.assertEqual(_features(1000000,'1','1.01','.006')[-1],60.0)
        self.assertFalse(advisory(self.path/'not-a-model','1','1.01')['affects_live_orders'])

    def test_directional_schema_keeps_unverified_history_out_of_neural_examples(self):
        store=FauxStore(self.path/'forward.sqlite3')
        with store._db() as db:
            db.execute('CREATE TABLE market_quotes(pair TEXT,at_utc INTEGER,bid TEXT,ask TEXT)')
            db.commit()
        lab=DirectionalLab(store,fee_learning=self.fee)
        lab.record('BTC-USD','99','100',now=1000000)
        with store._db() as db:
            row=db.execute('SELECT fee_source_at_entry,fee_taker_at_entry FROM directional_trials').fetchone()
        self.assertEqual(row[0],'UNVERIFIED_ASSUMPTION')
        self.assertIsNone(row[1])
        self.assertEqual(collect_two_way_examples(store.path),[])

if __name__=='__main__':unittest.main()
