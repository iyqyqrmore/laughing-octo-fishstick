"""New v50.1 trading-transition offline acceptance tests (NO Coinbase client)."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import inspect
import unittest
from coincat_v501_pilot_diagnostics import pilot_rehearsal,diagnostic_section
from coincat_unified_broker import plan_spot_intent


class TwelveTradePilot(unittest.TestCase):
    def test_exactly_twelve_mock_orders_and_replays(self):
        result=pilot_rehearsal()
        self.assertEqual(result['orders'],12)
        self.assertEqual(result['split_fills'],24)
        self.assertEqual(result['replay_noops'],12)
        self.assertEqual(result['quote_assets'],7)

    def test_diagnostic_releases_no_private_balances(self):
        app=SimpleNamespace(catalog=['BTC-USD','ETH-BTC','ADA-USDT','SOL-ETH'])
        txt=diagnostic_section(app)
        self.assertIn('Non-USD/USDC quoted catalog products: 3',txt)
        self.assertIn('[BLOCKED] 12 REAL ORDER pilot:',txt)
        self.assertNotIn('trade_id:',txt)
        self.assertNotIn('account_id:',txt)

    def test_cross_crypto_intent_reaches_same_currency_neutral_contract(self):
        rules={'ETH-BTC':dict(product_id='ETH-BTC',product_type='SPOT',
            base_increment='0.000001',base_min_size='0.000001',quote_min_size='0.000001')}
        q={'ETH-BTC':('0.03499','0.035',1000),'BTC-USD':('85000','85020',1000)}
        result=plan_spot_intent(pair='ETH-BTC',side='BUY',catalog=['ETH-BTC'],
            product_rules=rules,quotes=q,now=1001,authorized={'BTC':'0.05'},
            verified={'BTC':'0.05'},balance_age_s=2,usd_order_cap='10',
            fee_reserve_bps='30')  # invented offline fee evidence, not Coinbase authorization
        self.assertTrue(result['candidate'])
        self.assertEqual(result['spend_asset'],'BTC')
        self.assertEqual(result['state'],'UNIFIED_RESEARCH_INTENT')
        self.assertEqual(result['settlement_mode'],'UNIFIED_CURRENCY_TAGGED_PREFLIGHT')
        self.assertLessEqual(float(result['stressed_usd_risk']),10)
        self.assertFalse(result['order_submitted'])

    def test_auto_trader_all_pair_review_and_no_old_execution_fast_lane(self):
        from coincat_app import CoinCatApp
        source=inspect.getsource(CoinCatApp._cycle)
        self.assertIn('self.broker.review_spot_candidate',source)
        self.assertIn('relative_evidence=self.relative_lab.paired_outcomes',source)
        self.assertIn('Unified all-spot execution Handoff',source)
        self.assertNotIn('self.broker.submit(',source)

    def test_old_usd_live_route_retired_from_active_submit(self):
        from coincat_live import HISTORICAL_FILL_PAIR_RE, LiveBroker,LiveBlocked
        self.assertTrue(HISTORICAL_FILL_PAIR_RE.fullmatch('ETH-USD'))
        self.assertFalse(HISTORICAL_FILL_PAIR_RE.fullmatch('ETH-BTC'))
        # The historical restriction is not a separate available live fast lane.
        source=inspect.getsource(LiveBroker.submit)
        self.assertIn('no legacy-only pilot or live POST allowed',source)
        self.assertIn('raise LiveBlocked',source.split('\n')[1])

if __name__=='__main__': unittest.main()
