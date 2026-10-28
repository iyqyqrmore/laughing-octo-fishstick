"""Windows/Linux offline v50.6 guardrail tests, zero Coinbase SDK connectivity."""
import unittest
from datetime import date
from decimal import Decimal
from contextlib import closing
import sqlite3
from coincat_v506_capital import reserve_view,size_advice,CapitalBlocked,capital_rehearsal
from coincat_v506_coinbase_evidence import fetch_authenticated_order_and_fills,ExchangeEvidenceBlocked,evidence_rehearsal
from coincat_v506_reconciliation import integrated_12_order_rehearsal,_settle_fake_verified,IntegrationBlocked
from coincat_v506_readiness import report
from coincat_version import DISPLAY

class ReservePolicyTests(unittest.TestCase):
    def test_full_available_portfolio_is_not_arbitrarily_locked(self):
        v=reserve_view(enrolled_usd='1000',verified_liquid_usd='1000',starting_capital_usd='400',
                       day=date(2026,10,24),protect_original_after_doubling=False)
        r=size_advice(view=v,verified_order_funding_usd='1000',proposed_notional_usd='975',
              worst_case_fees_spread_slippage_usd='20',expected_incremental_net_usd='6',
              confidence_validated=True,manual_per_order_limit_usd='1000',
              manual_daily_remaining_usd='1000',independent_portfolio_floor_headroom_usd='1000')
        self.assertEqual(r['maximum_gross_usd'],'980')
        self.assertTrue(r['research_qualified'])
        self.assertFalse(r['order_allowed'])
    def test_unsegregated_reserve_blocks_research_capital(self):
        v=reserve_view(enrolled_usd='200',verified_liquid_usd='200',starting_capital_usd='100',
              day=date(2026,10,24),protect_original_after_doubling=True)
        self.assertEqual(v.remaining_available_usd,0)
    def test_reserve_double_counts_are_rejected(self):
        with self.assertRaises(CapitalBlocked):
            reserve_view(enrolled_usd='200',verified_liquid_usd='200',starting_capital_usd='100',
              verified_reserve_usd='100',day=date(2026,10,24),protect_original_after_doubling=True)
    def test_deposit_is_not_doubling_trade_profit(self):
        v=reserve_view(enrolled_usd='200',verified_liquid_usd='200',starting_capital_usd='100',
            net_external_contributions_usd='100',day=date(2026,10,24),protect_original_after_doubling=True)
        self.assertFalse(v.doubling_reached)
    def test_float_and_nonfinite_blocked(self):
        with self.assertRaises(CapitalBlocked):
            reserve_view(enrolled_usd=100.0,verified_liquid_usd='90',starting_capital_usd='80',day=date.today())
    def test_capital_rehearsal(self):
        self.assertTrue(all(capital_rehearsal().values()))

class SDKReadOnlyEvidenceTests(unittest.TestCase):
    def test_paginated_no_post(self):
        self.assertEqual(evidence_rehearsal()['mock_fills'],2)
    def test_repeated_cursor_refused(self):
        class Fake:
            def get_order(self,oid):return {'order':{'order_id':oid}}
            def get_fills(self,**kwargs):return {'fills':[],'has_next':True,'cursor':'REPEAT'}
        with self.assertRaises(ExchangeEvidenceBlocked):
            fetch_authenticated_order_and_fills(Fake(),'O1')
    def test_cross_order_response_refused(self):
        class Fake:
            def get_order(self,oid):return {'order':{'order_id':oid}}
            def get_fills(self,**kwargs):return {'fills':[{'order_id':'OTHER','trade_id':'1'}],'has_next':False}
        with self.assertRaises(ExchangeEvidenceBlocked):fetch_authenticated_order_and_fills(Fake(),'O1')
    def test_sdk_methods_required(self):
        with self.assertRaises(ExchangeEvidenceBlocked):fetch_authenticated_order_and_fills(object(),'O1')

class AtomicJournalTests(unittest.TestCase):
    def test_twelve_reconciled_in_same_fake_ledger(self):
        r=integrated_12_order_rehearsal()
        self.assertEqual((r['fake_orders'],r['fake_split_fills'],r['fee_quote_assets']),(12,24,7))
        self.assertEqual(r['double_settlement_refusals'],12)
        self.assertEqual(r['coinbase_posts'],0)
    def test_production_path_cannot_be_settled_by_test_helper(self):
        with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
            db.execute("ATTACH DATABASE ':memory:' AS production")
            with self.assertRaises(IntegrationBlocked):
                _settle_fake_verified(db,client_id='MOCK',order={'order_id':'MOCK'},fills=[],fee_currencies={},usd_marks={})
    def test_combined_diagnostics_label_and_no_live_grant(self):
        out=report(None)
        self.assertIn('CoinCat v50.6',out)
        self.assertIn('24 split fills',out)
        self.assertIn('NOT CONNECTED',out)
        self.assertIn('NOT APPROVED',out)
    def test_runtime_version_bumped(self):
        self.assertEqual(DISPLAY,'CoinCat v70.2')

if __name__=='__main__':unittest.main()
