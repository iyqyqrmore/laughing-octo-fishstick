"""Verified cross-quote fill accounting groundwork (NOT an order-submission path).

Amounts below have explicit units. USD marks come from caller-supplied,
authenticated REST bid/ask books, matched to Coinbase trade time. They are
not historical tax cost, projected gains, or actual wallet authorizations.

This module intentionally does not change existing orders/fills, inventory_lots,
enrollment or risk tables. The legacy live broker may NOT submit cross quotes.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import json

from coincat_cross_quote import split_spot, usd_conversion
from coincat_fill_units import normalize_fill, summarize_fills, verify_order_totals, FillUnitError


class CrossAccountingBlocked(ValueError):
    pass


def _d(x):
    try:
        n=Decimal(str(x))
        if not n.is_finite() or n < 0: raise ValueError()
        return n
    except (TypeError, ValueError, InvalidOperation):
        raise CrossAccountingBlocked('Invalid nonnegative financial amount') from None


def _at(x):
    if isinstance(x, bool): raise CrossAccountingBlocked('Invalid fill timestamp')
    if isinstance(x, (int, float)):
        if not 0 < float(x) < 4102444800: raise CrossAccountingBlocked('Invalid fill time range')
        return float(x)
    if isinstance(x, str) and x:
        try:
            dt=datetime.fromisoformat(x.replace('Z','+00:00'))
            if dt.tzinfo is None: raise ValueError()
            return dt.timestamp()
        except ValueError: pass
    raise CrossAccountingBlocked('Missing timezone-aware Coinbase fill timestamp')


def verified_cross_order(*, order, fills, pair, side, books, source,
                         max_fx_age_s=90, max_usd_notional=None):
    """Pure verified-fill computation; requires a terminal Coinbase order.

    For a market BUY: base increases, quote decreases by gross quote + fees.
    For a market SELL: base decreases, quote increases by gross quote - fees.
    Coinbase commissions are only accepted as quote-currency fees. Fees in
    other assets require a separate supported reconciliation extension.
    Does NOT infer a USD tax basis or create any realized P&L.
    """
    base, quote=split_spot(pair)
    side=str(side).upper()
    if side not in ('BUY','SELL'): raise CrossAccountingBlocked('Not a BUY/SELL spot fill')
    if str(source)!='AUTHENTICATED_REST_BID_ASK':
        raise CrossAccountingBlocked('USD FX requires authenticated REST bid/ask evidence')
    if not isinstance(order,dict) or not order.get('order_id'):
        raise CrossAccountingBlocked('Coinbase order ID required')
    if order.get('product_id')!=pair or str(order.get('side','')).upper()!=side:
        raise CrossAccountingBlocked('Coinbase order identity mismatch')
    if str(order.get('status','')).upper() not in ('FILLED','COMPLETED'):
        raise CrossAccountingBlocked('Only verified terminal filled orders can be valued')
    if not isinstance(fills,list) or not fills:raise CrossAccountingBlocked('No verified Coinbase fills')
    try:
        totals=summarize_fills(fills,order_id=str(order['order_id']),pair=pair,side=side)
        verify_order_totals(order,totals)
    except FillUnitError as exc:raise CrossAccountingBlocked(str(exc)) from exc
    records=[]
    total_usd=Decimal(0);total_fee_usd=Decimal(0);usd_spent=Decimal(0)
    for row in fills:
        # Guard both explicit Coinbase fee_currency encodings and SDK variants.
        for key in ('fee_currency','commission_currency'):
            if row.get(key) is not None and str(row[key]).upper()!=quote:
                raise CrossAccountingBlocked('Non-quote fee requires separate currency-specific settlement')
        details=row.get('commission_detail_total')
        if isinstance(details,dict):
            for key in ('currency','fee_currency','commission_currency'):
                if details.get(key) is not None and str(details[key]).upper()!=quote:
                    raise CrossAccountingBlocked('Non-quote fee in Coinbase commission details')
        at=_at(row.get('trade_time') or row.get('at_utc'))
        fx=usd_conversion(quote,books,now=at,max_age=max_fx_age_s,max_legs=3)
        if fx is None or fx['rate']<=0:
            raise CrossAccountingBlocked('No contemporaneous authenticated quote-to-USD conversion')
        normalized=normalize_fill(row)
        qty, gross, fee=normalized['base_qty'],normalized['quote_qty'],normalized['commission']
        if side=='SELL' and fee>gross:
            raise CrossAccountingBlocked('Coinbase SELL fee exceeds gross proceeds')
        usd=gross*fx['rate'];fee_usd=fee*fx['rate']
        total_usd+=usd;total_fee_usd+=fee_usd
        if side=='BUY': usd_spent+=usd+fee_usd
        tid=str(row.get('trade_id') or '')
        records.append(dict(trade_id=tid,order_id=str(order['order_id']),pair=pair,
            side=side,base=base,quote=quote,base_qty=str(qty),gross_quote=str(gross),
            fee_quote=str(fee),fill_at_utc=str(at),fx_usd_per_quote=str(fx['rate']),
            fx_path=list(fx['path']),gross_usd=str(usd),fee_usd=str(fee_usd),
            base_change=str(qty if side=='BUY' else -qty),
            quote_change=str(-(gross+fee) if side=='BUY' else gross-fee),
            tax_basis_usd=None,realized_tax_gain_usd=None))
    if max_usd_notional is not None:
        cap=_d(max_usd_notional)
        charge=usd_spent if side=='BUY' else total_usd
        if charge>cap:raise CrossAccountingBlocked('Confirmed cross-quote USD notional exceeds stage cap; stop and reconcile')
    return dict(order_id=str(order['order_id']),pair=pair,side=side,
        total_base=str(totals['base_qty']),total_gross_quote=str(totals['quote_qty']),
        quote_currency=quote,total_gross_usd=str(total_usd),
        total_fee_quote=str(totals['fees']),total_fee_usd=str(total_fee_usd),
        tax_profit_usd=None,performance_profit_usd=None,
        basis_state='UNKNOWN_UNTIL_VERIFIED_FIFO_USD_LOTS',records=records)


def install_cross_audit(db):
    """Additive isolated audit schema; neither modifies legacy lots nor permits orders."""
    db.execute('''CREATE TABLE IF NOT EXISTS cross_verified_fill_audit(
      trade_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, pair TEXT NOT NULL,
      side TEXT NOT NULL, fill_at_utc TEXT NOT NULL,
      base_qty TEXT NOT NULL, gross_quote TEXT NOT NULL, fee_quote TEXT NOT NULL,
      quote_currency TEXT NOT NULL, fx_usd_per_quote TEXT NOT NULL,
      gross_usd TEXT NOT NULL, fee_usd TEXT NOT NULL,
      base_change TEXT NOT NULL, quote_change TEXT NOT NULL,
      fx_path_json TEXT NOT NULL, tax_basis_usd TEXT, tax_gain_usd TEXT,
      audit_schema INTEGER NOT NULL DEFAULT 1)''')


def audit_confirmed_cross_order(db, verified):
    """Durable idempotent audit of *already verified* fills; NOT wallet settlement.

    Must run inside a caller-controlled SQLite transaction. On repeated
    identical events returns zero; conflicting trade_id aborts atomically.
    This is NOT an executable ledger or substitute for available balances.
    """
    rows=verified['records']
    if not rows:raise CrossAccountingBlocked('No verified fill rows')
    db.execute("SAVEPOINT coincat_cross_audit")
    try:
        inserted=0
        for r in rows:
            vals=(r['trade_id'],r['order_id'],r['pair'],r['side'],r['fill_at_utc'],
                  r['base_qty'],r['gross_quote'],r['fee_quote'],r['quote'],
                  r['fx_usd_per_quote'],r['gross_usd'],r['fee_usd'],
                  r['base_change'],r['quote_change'],json.dumps(r['fx_path']))
            existing=db.execute('''SELECT trade_id,order_id,pair,side,fill_at_utc,base_qty,
                gross_quote,fee_quote,quote_currency,fx_usd_per_quote,gross_usd,fee_usd,
                base_change,quote_change,fx_path_json FROM cross_verified_fill_audit
                WHERE trade_id=?''',(r['trade_id'],)).fetchone()
            if existing is not None:
                if tuple(existing)!=vals:raise CrossAccountingBlocked('Conflicting Coinbase trade_id in immutable cross-fill audit')
                continue
            db.execute('''INSERT INTO cross_verified_fill_audit(trade_id,order_id,pair,side,
              fill_at_utc,base_qty,gross_quote,fee_quote,quote_currency,fx_usd_per_quote,
              gross_usd,fee_usd,base_change,quote_change,fx_path_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',vals)
            inserted+=1
        db.execute("RELEASE SAVEPOINT coincat_cross_audit")
        return inserted
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT coincat_cross_audit")
        db.execute("RELEASE SAVEPOINT coincat_cross_audit")
        raise
