"""Synthetic, disposable SQLite and no Coinbase POSTs: reversible daily BUY pause."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import time

from coincat_daily_risk import daily_loss_limit, loss_decision, LossEvidenceUnavailable
from coincat_live import LiveLedger, LiveBroker, LiveBlocked

T = int(datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc).timestamp())

class NullClient:
    """Any network method invocation must fail the test."""
    def __getattr__(self, name):
        raise AssertionError('No exchange calls allowed in fake daily-loss tests: '+name)

class DailyLossReversibleTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'mock_ledger.sqlite3'
        self.ledger = LiveLedger(self.path)
        self.broker = LiveBroker(self.ledger, NullClient(), per_order_max='10',daily_buy_cap='40',exposure_cap='50',max_orders_day=12)
        # Synthetic armed flag only, avoids .arm(), which correctly blocks all actual live POSTs.
        self.broker.armed = True
        self.broker.daily_realized_loss_limit_usd = Decimal('5.00')
    def sell(self, trade_id, profit, t=None, state='FILLED', pair='SOL-USD', net=True):
        when=T-1000 + (int(trade_id.replace('fill','')) * 100 if t is None else 0) if t is None else t
        cid='cid-'+trade_id
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('''INSERT INTO orders(cid,order_id,pair,side,requested_size,preview_fee,state,created_at,purpose)
                         VALUES (?,?,?,?,?,?,?,?,?)''',(cid,'order-'+trade_id,pair,'SELL','1','0.01',state,when-30,'AUTOTRADE'))
            c.execute('''INSERT INTO fills(trade_id,cid,order_id,pair,side,base_qty,price,fee_quote,at_utc,
                         performance_realized_quote,net_realized_quote)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (trade_id,cid,'order-'+trade_id,pair,'SELL','1','10','0.01',when,
                 str(profit) if net else None, str(profit) if net else None))
            c.commit()
    def test_repeated_buy_evaluation_auto_resumes_after_confirmed_profitable_sell(self):
        self.sell('fill1','-5.50')
        pause=loss_decision(self.path,'5.00',T)
        self.assertEqual(pause['pnl_usd'], Decimal('-5.50'))
        self.assertFalse(pause['new_buys_allowed'])
        with patch('coincat_capacity.validate_limits'), patch.object(self.broker,'permissions',return_value={}):
            with self.assertRaisesRegex(LiveBlocked,'daily USD realized-loss BUY pause'):
                self.broker.risk_check('BUY','SOL-USD','2',T)
            self.sell('fill2','0.75')
            resume=loss_decision(self.path,'5.00',T)
            self.assertEqual(resume['pnl_usd'], Decimal('-4.75'))
            self.assertTrue(resume['new_buys_allowed'])
            self.assertTrue(self.broker.armed, 'daily loss must never automatically disarm')
            self.broker.risk_check('BUY','SOL-USD','2',T)  # no manual re-ARM
            self.sell('fill3','-0.25')
            self.assertEqual(loss_decision(self.path,'5.00',T)['pnl_usd'],Decimal('-5.00'))
            with self.assertRaisesRegex(LiveBlocked,'daily USD realized-loss BUY pause'):
                self.broker.risk_check('BUY','SOL-USD','2',T)
    def test_stop_latch_cannot_auto_clear_on_sell(self):
        self.sell('fill1','-5.60')
        self.sell('fill2','1.00')
        self.assertTrue(loss_decision(self.path,'5',T)['new_buys_allowed'])
        self.ledger.set_setting('halted','1')
        with self.assertRaisesRegex(LiveBlocked,'not been armed'):
            self.broker.risk_check('BUY','SOL-USD','2',T)
        self.assertEqual(self.ledger.setting('halted'),'1')
    def test_unconfirmed_or_non_usd_sells_fail_closed(self):
        self.sell('fill1','2',state='SUBMISSION_PENDING')
        with self.assertRaises(LossEvidenceUnavailable): loss_decision(self.path,'5',T)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("UPDATE orders SET state='FILLED'")
            c.execute("UPDATE fills SET pair='ETH-BTC'")
            c.commit()
        with self.assertRaises(LossEvidenceUnavailable): loss_decision(self.path,'5',T)
    def test_missing_basis_cannot_release_pause(self):
        self.sell('fill1',None,net=False)
        with self.assertRaises(LossEvidenceUnavailable): loss_decision(self.path,'5',T)
    def test_no_fill_does_not_create_spurious_loss(self):
        result=loss_decision(self.path,'5',T)
        self.assertEqual(result['pnl_usd'], Decimal(0))
        self.assertTrue(result['new_buys_allowed'])
    def test_limit_is_adjustable_but_requires_valid_decimal_input(self):
        for amt in ('0.01','5','10000.00'):
            self.assertEqual(daily_loss_limit(amt),Decimal(amt))
        for amt in ('0','-1','10000.01','5.001','NaN','Infinity',''):
            with self.assertRaises(ValueError):daily_loss_limit(amt)
    def test_disarmed_state_does_not_rearm_even_if_sell_restores_eligibility(self):
        self.sell('fill1','-5.50')
        self.sell('fill2','0.75')
        self.broker.armed = False
        with self.assertRaisesRegex(LiveBlocked,'not been armed'):
            self.broker.risk_check('BUY','SOL-USD','2',T)
        self.assertFalse(self.broker.armed)
    def test_all_spot_submission_still_cannot_be_armed(self):
        self.broker.armed=False
        with self.assertRaisesRegex(LiveBlocked,'Unified all-spot POST disabled'):
            self.broker.arm()
        self.assertFalse(self.broker.armed)
    def test_previous_day_losses_not_misreported_today(self):
        self.sell('fill1','-1000',t=T-86400)
        self.assertEqual(loss_decision(self.path,'5',T)['pnl_usd'],Decimal(0))
