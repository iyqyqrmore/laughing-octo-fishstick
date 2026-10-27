"""Read-only, exact-USD daily realized-loss BUY pause for CoinCat.

This rule is distinct from the unimplemented whole-portfolio loss floor. Only
locally confirmed USD-quoted SELLs can contribute to verified historical daily
realized performance. Unverified denominations/basis fail closed on BUYs.
No network, ARM, trade, or writes occur in this module.
"""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
import time

MIN_LIMIT = Decimal('0.01')
MAX_LIMIT = Decimal('10000.00')
DEFAULT_LIMIT = Decimal('5.00')

class LossEvidenceUnavailable(ValueError):
    pass

def daily_loss_limit(value):
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount < MIN_LIMIT or amount > MAX_LIMIT:
            raise ValueError()
        if amount.as_tuple().exponent < -2:
            raise ValueError()
        return amount
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('Daily realized-loss BUY pause must be $0.01–$10,000.00 with at most 2 decimals') from None

def confirmed_daily_usd(ledger_path, now=None):
    """Returns signed, verified USD SELL P&L for UTC day. Fails closed on uncertainty.

    Historical quote-denominated USDC and crypto-quoted results are NOT asserted
    to be dollars without an authenticated contemporaneous USD conversion.
    Unknown cost basis/partial order histories are not counted as a zero loss.
    """
    now = int(time.time() if now is None else now)
    midnight = int(datetime.fromtimestamp(now,timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())
    path = Path(ledger_path)
    if not path.is_file():
        raise LossEvidenceUnavailable('Verified financial ledger missing')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA query_only=ON')
            # Do not silently ignore orphan fills, which indicate incomplete journal linkage.
            orphan=c.execute('''SELECT COUNT(*) FROM fills f LEFT JOIN orders o ON f.cid=o.cid AND f.order_id=o.order_id
                WHERE f.at_utc>=? AND o.cid IS NULL''',(midnight,)).fetchone()[0]
            if orphan:
                raise LossEvidenceUnavailable('Unmatched confirmed fills require reconciliation')
            entries=c.execute('''SELECT f.pair, o.pair AS order_pair, f.side AS fill_side, o.side AS order_side,
                o.state, f.performance_realized_quote, f.net_realized_quote
                FROM fills f JOIN orders o ON f.cid=o.cid AND f.order_id=o.order_id
                WHERE f.at_utc>=? AND f.at_utc<=? ORDER BY f.trade_id''',(midnight,now)).fetchall()
    except (sqlite3.Error, OSError) as ex:
        raise LossEvidenceUnavailable('Unable to verify current UTC-day financial fills') from ex
    total = Decimal(0)
    sells = 0
    for r in entries:
        if r['fill_side'] != 'SELL':
            continue
        if r['order_side'] != 'SELL' or r['order_pair'] != r['pair'] or r['state'] not in ('FILLED','COMPLETED'):
            raise LossEvidenceUnavailable('Incomplete or inconsistent SELL settlement')
        pair=r['pair'] or ''
        if not pair.endswith('-USD'):
            raise LossEvidenceUnavailable('Daily SELL results lack verified USD fee/FX conversion')
        result=r['performance_realized_quote']
        if result is None:
            result=r['net_realized_quote']
        if result is None:
            raise LossEvidenceUnavailable('Confirmed SELL is missing verified cost/performance basis')
        try:
            pnl=Decimal(str(result))
            if not pnl.is_finite():raise InvalidOperation
        except (ValueError,TypeError,InvalidOperation) as ex:
            raise LossEvidenceUnavailable('Confirmed SELL has invalid USD performance') from ex
        total += pnl
        sells += 1
    return {'pnl_usd':total, 'sell_fills':sells, 'utc_day_start':midnight}

def loss_decision(ledger_path, limit, now=None):
    cap=daily_loss_limit(limit)
    evidence=confirmed_daily_usd(ledger_path,now)
    return {**evidence, 'limit_usd':cap,
            'new_buys_allowed':evidence['pnl_usd'] > -cap,
            'remaining_loss_room_usd':max(Decimal(0),cap+evidence['pnl_usd'])}


def reversible_rehearsal():
    """Disposable demonstration that later verified SELL P&L reverses BUY pause.

    No Coinbase calls, no production database reads/writes, no trading authorization.
    """
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='CoinCatDailyRiskFake_') as tmp:
        path=Path(tmp)/'daily_risk_fake.sqlite3'
        now=1761235200  # fixed offline UTC timestamp
        with closing(sqlite3.connect(path)) as c:
            c.executescript('CREATE TABLE orders(cid TEXT PRIMARY KEY,order_id TEXT, pair TEXT,side TEXT,state TEXT);\n                  CREATE TABLE fills(trade_id TEXT,cid TEXT,order_id TEXT,pair TEXT,side TEXT,at_utc INTEGER,\n                      performance_realized_quote TEXT,net_realized_quote TEXT);')
            c.execute('INSERT INTO orders VALUES (?,?,?,?,?)',('a','id1','SOL-USD','SELL','FILLED'))
            c.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)',
                      ('t1','a','id1','SOL-USD','SELL',now-60,'-5.50',None))
            c.commit()
        before=loss_decision(path,'5.00',now)
        with closing(sqlite3.connect(path)) as c:
            c.execute('INSERT INTO orders VALUES (?,?,?,?,?)',('b','id2','ETH-USD','SELL','FILLED'))
            c.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)',
                      ('t2','b','id2','ETH-USD','SELL',now-30,'0.75',None))
            c.commit()
        after=loss_decision(path,'5.00',now)
        assert not before['new_buys_allowed'] and after['new_buys_allowed']
        assert before['pnl_usd']==Decimal('-5.50') and after['pnl_usd']==Decimal('-4.75')
        return {'synthetic_pause':True,'synthetic_resume':True,
                'live_orders':0,'production_writes':0}
