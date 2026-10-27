"""v60.11 callback privacy, monotonic WS freshness and research-only handoff."""
import unittest
import json
from unittest.mock import patch
from coincat_v6011_observation import safe_callback_breadcrumb,annotate_study
from coincat_market_stream import PublicTickerTape
from coincat_rotation_autopilot import auto_rotation_screen

NOW=1800000000
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'.01'}

class Callback(unittest.TestCase):
    def test_file_error_exposes_no_path_or_exception_message(self):
        try:
            raise FileNotFoundError('C:/Users/private/coinbase-secret.key')
        except FileNotFoundError as e:
            clue=safe_callback_breadcrumb(e)
        self.assertNotIn('C:/Users',clue)
        self.assertNotIn('secret',clue)
        self.assertIn('EXTERNAL_FRAME_REDACTED',clue)

class Ticker(unittest.TestCase):
    def test_real_monotonic_event_ages_survive_wall_clock_offset(self):
        tape=PublicTickerTape()
        tape.set_pairs(['ADA-USD'])
        tape._connected=True
        raw=json.dumps({'channel':'ticker_batch','events':[{'tickers':[{'product_id':'ADA-USD','price':'0.80'}]}]})
        tape._receive(raw)
        a=tape.status(now=0)
        b=tape.status(now=2**34)
        for status in (a,b):
            self.assertEqual(status['observed'],1)
            self.assertEqual(status['fresh'],1)
            self.assertGreaterEqual(status['last_message_age'],0)
            self.assertEqual(status['requested'],0)
            self.assertIn('changed trades',status['freshness_definition'])
    def test_stale_tick_can_never_be_resuscitated_by_time_clock(self):
        tape=PublicTickerTape()
        tape.set_pairs(['ADA-USD'])
        tape._connected=True
        with tape._lock:
            tape._prices['ADA-USD']=('1',-1.0)
        self.assertEqual(tape.status(now=2**55)['fresh'],0)

class Handoff(unittest.TestCase):
    def test_positive_pair_learning_remains_non_authorizing(self):
        candidates=annotate_study([{'strategy':'BREAKOUT','pair':'BTC-USD','action':'EXPLORE_ONLY',
              'sends_orders':False,'observed_pct':'1'}],{'BREAKOUT:60m':{'OBSERVED':200,
                 'positive_cash_after_cost':150,'maturity':'HISTORY_MATURED_NOT_PORTFOLIO_VALIDATED'}})
        self.assertEqual(candidates[0]['forward_observed_hourly'],200)
        self.assertEqual(candidates[0]['forward_positive_cash_after_cost'],150)
        self.assertIs(candidates[0]['oos_validated'],False)
        out=auto_rotation_screen(buy_signals=[],strategy_candidates=candidates,
            holdings=[{'asset':'USD','remaining_qty':'150','enabled':1}],
            verified_balances={'USD':'150'},balance_age_s=10,
            catalog=['BTC-USD','USDC-USD'],
            quotes={'BTC-USD':('49990','50000',NOW),'USDC-USD':('1','1',NOW)},
            product_rules={p:RULE for p in ['BTC-USD','USDC-USD']},
            usd_per_order_cap='150',now=NOW,
            fee_rates_by_pair={'BTC-USD':'.009','USDC-USD':'.009'},
            minimum_net_advantage_usd='.10',direct_only=True)
        self.assertGreater(out['strategy_route_reviews'],0)
        self.assertTrue(out['ideas'])
        for idea in out['ideas']:
            self.assertFalse(idea['oos_validated'])
            self.assertEqual(idea['strategy_forward_observations']['observed_hourly'],200)
            self.assertFalse(idea['sends_live_orders'])
        self.assertEqual(out['threshold_research']['qualified_predictions'],0)

if __name__=='__main__':unittest.main()
