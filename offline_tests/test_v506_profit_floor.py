"""v50.6R: USD target sensitivity, non-actionability, full-precision comparisons."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from coincat_v506_profit_sensitivity import (compare_observations,read_forward_evidence,
                                                 report,NEW_TARGET,PREVIOUS_TARGET)
from coincat_v506_capital import reserve_view,size_advice
from datetime import date

class TargetResearchTests(unittest.TestCase):
    def test_adjustable_targets_and_intermediate_outcomes(self):
        r=compare_observations([('ETH-USD',1,'0.80','ACCOUNT_TIER_NOT_PAIR_PREVIEW'),
                                ('BTC-USD',2,'1.30','ACCOUNT_TIER_NOT_PAIR_PREVIEW'),
                                ('SOL-BTC',3,'-0.90','ACCOUNT_TIER_NOT_PAIR_PREVIEW')],
                                notionals=('100',),slip='0')
        self.assertEqual((r['comparisons'][0]['target_055'],r['comparisons'][0]['target_098']), (2,1))
        self.assertFalse(r['execution_verified']);self.assertFalse(r['predictive_edge_verified'])
    def test_slippage_makes_some_observed_outcomes_no_longer_clear(self):
        rows=[('ETH-BTC',1,'0.80','ACCOUNT_TIER_NOT_PAIR_PREVIEW')]
        r=compare_observations(rows,notionals=('100',))
        self.assertEqual((r['comparisons'][0]['target_055'],r['comparisons'][0]['target_098']), (0,0))
    def test_missing_fees_replay_not_counted(self):
        r=compare_observations([('A-B',1,'2','UNVERIFIED'),('A-B',1,'2','ACCOUNT_TIER_NOT_PAIR_PREVIEW')])
        self.assertEqual(r['compared'],0)
        self.assertEqual(r['excluded'],2)
    def test_nonfinite_cannot_qualify(self):
        r=compare_observations([('A-B',1,'NaN','ACCOUNT_TIER_NOT_PAIR_PREVIEW'),('A-B',2,'Infinity','ACCOUNT_TIER_NOT_PAIR_PREVIEW')])
        self.assertEqual(r['compared'],0)
    def test_realized_and_portfolio_budgets_not_changed(self):
        from coincat_app import CoinCatApp
        # Static code boundaries: no executable Coinbase POST in sensitivity module.
        import coincat_v506_profit_sensitivity as model
        from pathlib import Path
        txt=Path(model.__file__).read_text()
        for token in ('.create_order(','.market_order_buy(','.market_order_sell(','set_setting(','UPDATE fills'):
            self.assertNotIn(token,txt)
        v=reserve_view(enrolled_usd='100',verified_liquid_usd='100',starting_capital_usd='100',day=date(2026,10,24))
        r=size_advice(view=v,verified_order_funding_usd='100',proposed_notional_usd='90',
                      worst_case_fees_spread_slippage_usd='2',expected_incremental_net_usd='0.70',
                      confidence_validated=True,manual_per_order_limit_usd='100',
                      manual_daily_remaining_usd='100',independent_portfolio_floor_headroom_usd='100')
        self.assertTrue(r['research_qualified']);self.assertFalse(r['order_allowed'])
    def test_read_only_report_from_real_schema_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'research.sqlite3'
            con=sqlite3.connect(path)
            try:
                con.execute('CREATE TABLE forward_signals(pair TEXT,at_utc INT,observed_return_pct TEXT,fee_evidence_source TEXT,outcome_state TEXT)')
                con.execute("INSERT INTO forward_signals VALUES ('ETH-USD',123,'1.1','ACCOUNT_TIER_NOT_PAIR_PREVIEW','OBSERVED')")
                con.commit()
            finally:con.close()
            before=path.read_bytes()
            text=report(path)
            self.assertIn('$0.55',text);self.assertIn('$0.98',text)
            self.assertIn('NOT executable',text)
            self.assertEqual(before,path.read_bytes())
    def test_missing_table_marked_not_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'empty.sqlite3'
            # sqlite3.Connection.__exit__ does NOT close the handle on Windows.
            # Ensure the disposable database is released before TempDirectory cleanup.
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('PRAGMA user_version').fetchone()
            self.assertIn('[NOT VERIFIED]',report(path))

if __name__=='__main__':unittest.main()
