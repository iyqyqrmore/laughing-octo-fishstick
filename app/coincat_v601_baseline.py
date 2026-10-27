"""Immutable dated USD performance baselines, never historical tax cost.

Baseline is recorded only on a user's explicit request using contemporaneous,
complete verified enrolled quantities and USD marks. No Coinbase API or broker
calls occur here. Old baselines and historical acquisition/disposal lots survive.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import sqlite3
import time

class BaselineBlocked(ValueError):
    pass

def exact(value, *, positive=False):
    if isinstance(value, (float, bool)):
        raise BaselineBlocked('Only exact decimal values are permitted')
    try:
        v=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):
        raise BaselineBlocked('Missing or invalid verified holding or USD mark') from None
    if not v.is_finite() or v<0 or (positive and v<=0):
        raise BaselineBlocked('Nonpositive or invalid verified balance or USD mark')
    return v

def install(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS v601_performance_periods (
      period_id INTEGER PRIMARY KEY, captured_at_utc INTEGER NOT NULL,
      basis_kind TEXT NOT NULL CHECK(basis_kind='CURRENT_USD_PERFORMANCE_NOT_TAX'),
      total_usd TEXT NOT NULL, source TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS v601_performance_holdings (
      period_id INTEGER NOT NULL REFERENCES v601_performance_periods(period_id),
      asset TEXT NOT NULL, quantity TEXT NOT NULL, usd_per_unit TEXT NOT NULL,
      PRIMARY KEY(period_id,asset))''')

def latest(conn):
    install(conn)
    row=conn.execute('''SELECT p.period_id,p.captured_at_utc,p.total_usd,
       (SELECT COUNT(*) FROM v601_performance_holdings h WHERE h.period_id=p.period_id) AS assets
       FROM v601_performance_periods p ORDER BY period_id DESC LIMIT 1''').fetchone()
    if row is None:return None
    return {'id':int(row[0]),'at_utc':int(row[1]),'total_usd':str(row[2]),'assets':int(row[3]),
            'date_utc':datetime.fromtimestamp(int(row[1]),timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

def capture(conn, *, enrollments, available, usd_rates, now=None, source='COINBASE_READONLY_BOOKS'):
    """Atomic append-only frozen-HOLD quantities and USD marks; no tax-lot writes.

    All positively enrolled quantities MUST be independently available and USD
    priced. A deposit, excluded or unavailable holding cannot be silently added.
    The caller must separately verify quote age and authenticated Coinbase source.
    """
    stamp=int(time.time() if now is None else now)
    if stamp<=0:raise BaselineBlocked('Invalid current snapshot time')
    rows=[]
    for entry in enrollments:
        if not entry.get('enabled',1):continue
        asset=str(entry['asset']).strip().upper()
        if not asset or not asset.replace('_','').isalnum():raise BaselineBlocked('Invalid asset symbol')
        remaining=exact(entry.get('remaining_qty'))
        if not remaining:continue
        if asset not in available or asset not in usd_rates:
            raise BaselineBlocked('Every enrolled holding must have a verified balance and USD mark')
        owned=exact(available[asset])
        if owned<remaining:raise BaselineBlocked('Coinbase available quantity is below enrolled quantity')
        mark=exact(usd_rates[asset],positive=True)
        rows.append((asset,remaining,mark))
    if not rows:raise BaselineBlocked('No verified positive enrolled holdings')
    total=sum((q*p for _,q,p in rows),Decimal(0))
    if total<=0:raise BaselineBlocked('Empty starting portfolio USD value')
    # The caller owns the connection. BEGIN/rollback are explicit so a half
    # baseline never becomes visible. Nothing touches historical basis tables.
    conn.execute('BEGIN IMMEDIATE')
    try:
        install(conn)
        cur=conn.execute('''INSERT INTO v601_performance_periods(
            captured_at_utc,basis_kind,total_usd,source) VALUES(?,?,?,?)''',
            (stamp,'CURRENT_USD_PERFORMANCE_NOT_TAX',format(total,'f'),source))
        conn.executemany('''INSERT INTO v601_performance_holdings(
            period_id,asset,quantity,usd_per_unit) VALUES(?,?,?,?)''',
            [(cur.lastrowid,a,format(q,'f'),format(p,'f')) for a,q,p in rows])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {'id':int(cur.lastrowid),'at_utc':stamp,'assets':len(rows),'total_usd':format(total,'f')}

def hold_mark(conn, usd_rates):
    """Price frozen quantities at *today's* rates; no assumed trading alpha.

    Return None on a missing baseline quote instead of inventing a profit.
    External cash flows need separate verification before comparing a traded
    portfolio with this frozen-HOLD counterfactual.
    """
    state=latest(conn)
    if not state:return None
    rows=conn.execute('SELECT asset,quantity FROM v601_performance_holdings WHERE period_id=?',(state['id'],)).fetchall()
    total=Decimal(0)
    for asset,qty in rows:
        if asset not in usd_rates:return None
        total+=exact(qty)*exact(usd_rates[asset],positive=True)
    return total
