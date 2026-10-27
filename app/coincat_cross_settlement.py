"""v30.6 verified multi-currency fill ACCOUNTING PREFLIGHT, offline and non-mutating.

This module never imports a Coinbase client or updates the production ledger.
It records how actual order/fill data *would* debit/credit crypto wallets, with
explicit fee currencies and timestamp-matched USD marks. It is not approval for
LIVE submission, historical tax basis or portfolio performance.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from coincat_cross_quote import split_spot
from coincat_fill_units import normalize_fill, summarize_fills, verify_order_totals, FillUnitError

class SettlementBlocked(ValueError):
    pass

def money(raw, *, positive=False):
    if raw is None or isinstance(raw, bool):
        raise SettlementBlocked('Missing settlement amount')
    try: val=Decimal(str(raw))
    except (ValueError,TypeError,InvalidOperation):raise SettlementBlocked('Invalid settlement amount') from None
    if not val.is_finite() or val<0 or (positive and val<=0):
        raise SettlementBlocked('Invalid nonpositive or negative settlement amount')
    return val

def validate_filled_cross_order(*, order, fills, available_before, fee_currency_by_trade,
                                usd_marks_by_trade, catalog, excluded=(), usd_per_order_cap='10',
                                known_trade_fingerprints=None):
    """Atomic READ-ONLY evidence check for one confirmed spot order.

    order is the authenticated get_order payload; fills are authenticated and
    complete (pagination verified by the caller). fee_currency_by_trade maps
    trade ID to independently verified fee currency. usd_marks_by_trade maps
    (trade ID, currency) to (usd_per_unit, observed_timestamp), where timestamps
    must be within 60s of the exact Coinbase fill-time second; no implied peg.

    Returns an *uncommitted* settlement plan and SHA-compatible fingerprints;
    does not modify provided holdings, Coinbase accounts, inventory or lots.
    A separate durable FIFO USD tax/performance ledger must be built/audited
    before this plan is ever allowed into live execution.
    """
    if not isinstance(order,dict) or str(order.get('status','')).upper() not in ('FILLED','COMPLETED'):
        raise SettlementBlocked('Order not terminal confirmed FILLED')
    oid=str(order.get('order_id') or '')
    pair=order.get('product_id')
    side=str(order.get('side') or '').upper()
    if not oid or pair not in set(catalog or ()) or side not in ('BUY','SELL'):
        raise SettlementBlocked('Missing verified Coinbase order identity or spot product')
    base,quote=split_spot(pair)
    if base in excluded or quote in excluded:
        raise SettlementBlocked('Excluded asset in spot product')
    if not isinstance(fills,list) or not fills:
        raise SettlementBlocked('Missing completed Coinbase fills')
    try:
        totals=summarize_fills(fills,order_id=oid,pair=pair,side=side)
        verify_order_totals(order,totals)
    except FillUnitError as exc:
        raise SettlementBlocked(str(exc)) from exc
    # The legacy aggregate verifier allows fixed absolute differences
    # (1e-9 base and 1e-6 quote/fees). Those can swallow a meaningful
    # fraction of a dust-sized trade. For cross-currency accounting preflight,
    # reject *any* discrepancy, even below that old fixed tolerance. Legitimate
    # exchange summary rounding must be independently resolved before the
    # production ledger is changed. USD/USDC legacy broker is unaffected.
    for field, total in (('filled_size', totals['base_qty']),
                         ('filled_value', totals['quote_qty']),
                         ('total_fees', totals['fees'])):
        raw = order.get(field)
        if raw is None or isinstance(raw, float):
            raise SettlementBlocked('Missing or unsafe float Coinbase order '+field)
        if money(raw) != total:
            raise SettlementBlocked('Exact Coinbase order/fill '+field+' mismatch (dust protected)')
    for f in fills:
        for field in ('price','size','commission'):
            if isinstance(f.get(field), float):
                raise SettlementBlocked('Unsafe floating-point Coinbase fill '+field)
    source=quote if side=='BUY' else base
    wallets={k:money(v) for k,v in available_before.items()}
    rows=[];gross_usd=Decimal(0);fee_usd=Decimal(0)
    existing=known_trade_fingerprints or {}
    for f in fills:
        tid=str(f['trade_id'])
        ts=f.get('at_utc')
        if type(ts) is not int or ts<=0:
            raise SettlementBlocked('Fill has no trusted integer UTC trade time')
        fee_ccy=(fee_currency_by_trade or {}).get(tid)
        if not isinstance(fee_ccy,str) or not fee_ccy or fee_ccy in excluded:
            raise SettlementBlocked('Unverified or excluded fee currency')
        n=normalize_fill(f)
        qty,price,fee=n['base_qty'],n['price'],n['commission']
        identity=(oid,pair,side,str(qty),str(price),str(fee),fee_ccy,ts)
        if tid in existing:
            if tuple(existing[tid])!=identity:
                raise SettlementBlocked('Conflicting duplicate real Coinbase trade ID')
            # Replay is not silently re-applied. Caller must reconcile its
            # durable ledger; this preflight always refuses duplicate batches.
            raise SettlementBlocked('Previously accounted trade ID: reconciliation required')
        rates={}
        for asset in (base,quote,fee_ccy):
            if asset=='USD':
                rates[asset]=Decimal(1);continue
            snap=(usd_marks_by_trade or {}).get((tid,asset))
            if not isinstance(snap,(tuple,list)) or len(snap)!=2:
                raise SettlementBlocked('Missing fill-time USD conversion for '+asset)
            rate,mark_ts=snap
            if type(mark_ts) is not int or abs(mark_ts-ts)>60:
                raise SettlementBlocked('Stale or unverifiable fill-time USD conversion for '+asset)
            rates[asset]=money(rate,positive=True)
        # Source/receive are ALWAYS denominated in the named currency.
        gross_quote=qty*price
        deltas={base:qty if side=='BUY' else -qty,
                quote:-gross_quote if side=='BUY' else gross_quote}
        deltas[fee_ccy]=deltas.get(fee_ccy,Decimal(0))-fee
        for asset,delta in deltas.items():
            candidate=wallets.get(asset,Decimal(0))+delta
            if candidate < 0:
                raise SettlementBlocked('Settlement overdraw in '+asset)
            wallets[asset]=candidate
        gross_usd+=gross_quote*rates[quote]
        fee_usd+=fee*rates[fee_ccy]
        rows.append(dict(trade_id=tid,identity=identity,fee_currency=fee_ccy,
                         fee_amount=str(fee),fee_usd=str(fee*rates[fee_ccy]),
                         gross_quote=str(gross_quote),gross_usd=str(gross_quote*rates[quote]),
                         basis_usd=None,tax_realized_usd=None,performance_realized_usd=None))
    if gross_usd>money(usd_per_order_cap,positive=True):
        raise SettlementBlocked('Confirmed gross notional exceeds USD order cap; halt and reconcile')
    if source not in available_before:
        raise SettlementBlocked('Funding inventory missing from verified Coinbase snapshot')
    return {'status':'ACCOUNTING_PREFLIGHT_ONLY', 'ready_for_live_post':False,
            'pair':pair,'side':side,'order_id':oid,'fill_count':len(rows),
            'gross_notional_usd':str(gross_usd),'total_fee_usd':str(fee_usd),
            'verified_units_after':{k:str(v) for k,v in wallets.items()},
            'fills':rows,'realized_tax_pnl_usd':None,'realized_performance_usd':None,
            'next_gate':'Durable double-entry USD FIFO disposal/acquisition lots, partial-fill recovery, and real Coinbase tests required'}
