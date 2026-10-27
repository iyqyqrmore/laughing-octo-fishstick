"""CoinCat v50.1 currency-neutral, USD-valued FIFO settlement foundation.

Pure SQLite/Decimal accounting; NO exchange client or order submission.
The namespace is deliberately NEW. Existing v50 production inventory/tax tables
are not silently migrated or overwritten. Only confirmed fully corroborated
fills may be supplied; a separate Coinbase evidence adapter is still required.
All quantities and USD bases are TEXT Decimal values. An unknown basis stays NULL.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps
from contextlib import contextmanager
import sqlite3


class UnifiedSettlementError(ValueError):
    pass


def number(raw, *, positive=False):
    if isinstance(raw, (float, bool)) or raw is None:
        raise UnifiedSettlementError('Numeric input must be an exact string/Decimal, never binary float')
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise UnifiedSettlementError('Invalid exact financial amount') from None
    if not v.is_finite() or v < 0 or (positive and v <= 0):
        raise UnifiedSettlementError('Negative, nonfinite or zero financial amount')
    return v


def signed(raw):
    if isinstance(raw, (bool, float)) or raw is None:
        raise UnifiedSettlementError('Invalid exact signed P&L')
    try:
        v = Decimal(str(raw))
    except (TypeError, InvalidOperation, ValueError):
        raise UnifiedSettlementError('Invalid signed P&L') from None
    if not v.is_finite():
        raise UnifiedSettlementError('Invalid signed P&L')
    return v


def f(v):
    return format(v, 'f')


def install(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS unified_v501_wallets (
            asset TEXT PRIMARY KEY, qty TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS unified_v501_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, asset TEXT NOT NULL,
            remaining_qty TEXT NOT NULL, remaining_tax_usd TEXT,
            remaining_performance_usd TEXT, source TEXT NOT NULL,
            source_trade TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS unified_v501_asset_fifo ON unified_v501_lots(asset,id);
        CREATE TABLE IF NOT EXISTS unified_v501_fills (
            trade_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, product TEXT NOT NULL,
            side TEXT NOT NULL, gross_base TEXT NOT NULL,
            gross_quote TEXT NOT NULL, fee_amount TEXT NOT NULL,
            fee_currency TEXT NOT NULL, fee_usd TEXT NOT NULL,
            fingerprint TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS unified_v501_disposals (
            trade_id TEXT NOT NULL, lot_id INTEGER NOT NULL, asset TEXT NOT NULL,
            qty TEXT NOT NULL, tax_basis_usd TEXT, performance_basis_usd TEXT,
            proceeds_usd TEXT NOT NULL, tax_pnl_usd TEXT,
            performance_pnl_usd TEXT,
            PRIMARY KEY(trade_id,lot_id));
    ''')


def opening(db, asset, qty, *, tax_usd=None, performance_usd=None):
    """Synthetic/explicitly authorized opening seed: never fabricates tax USD basis."""
    amt=number(qty,positive=True)
    if not isinstance(asset,str) or not asset.isalnum() or asset.upper()!=asset:
        raise UnifiedSettlementError('Invalid asset')
    if db.execute('SELECT 1 FROM unified_v501_wallets WHERE asset=?',(asset,)).fetchone():
        raise UnifiedSettlementError('Opening quantity is immutable once seeded')
    tv=number(tax_usd) if tax_usd is not None else None
    pv=number(performance_usd) if performance_usd is not None else None
    db.execute('INSERT INTO unified_v501_wallets VALUES (?,?)',(asset,f(amt)))
    db.execute('''INSERT INTO unified_v501_lots(asset,remaining_qty,remaining_tax_usd,
                remaining_performance_usd,source) VALUES (?,?,?,?,?)''',
              (asset,f(amt),f(tv) if tv is not None else None,
               f(pv) if pv is not None else None,'EXPLICIT_OPENING'))


def balance(db,asset):
    row=db.execute('SELECT qty FROM unified_v501_wallets WHERE asset=?',(asset,)).fetchone()
    return number(row[0]) if row else Decimal(0)


def verify(db):
    assets={r[0] for r in db.execute('SELECT asset FROM unified_v501_wallets')}
    assets|={r[0] for r in db.execute('SELECT DISTINCT asset FROM unified_v501_lots')}
    for asset in assets:
        qty=sum((number(row[0]) for row in db.execute(
            'SELECT remaining_qty FROM unified_v501_lots WHERE asset=?',(asset,))),Decimal(0))
        if qty!=balance(db,asset):
            raise UnifiedSettlementError('Wallet versus FIFO quantity mismatch: '+asset)
    return True


def _change(db,asset,delta):
    old=balance(db,asset)
    new=old+delta
    if new<0:
        raise UnifiedSettlementError('Insufficient exact available units: '+asset)
    db.execute('INSERT INTO unified_v501_wallets VALUES (?,?) ON CONFLICT(asset) DO UPDATE SET qty=excluded.qty',
               (asset,f(new)))


def _add_lot(db, asset, amount, tax, performance, trade_id):
    if amount==0:return
    if amount<0:raise UnifiedSettlementError('Acquisition lot cannot be negative')
    db.execute('''INSERT INTO unified_v501_lots(asset,remaining_qty,remaining_tax_usd,
               remaining_performance_usd,source,source_trade) VALUES (?,?,?,?,?,?)''',
               (asset,f(amount),f(tax) if tax is not None else None,
                f(performance) if performance is not None else None,'VERIFIED_ACQUISITION',trade_id))
    _change(db,asset,amount)


def _dispose(db,asset,amount,proceeds_usd,trade_id):
    if amount<=0:raise UnifiedSettlementError('Empty disposal')
    if balance(db,asset)<amount:
        raise UnifiedSettlementError('Unfunded disposal: '+asset)
    left=amount;tax_total=Decimal(0);perf_total=Decimal(0)
    tax_known=True;perf_known=True;consumed=0
    for row in db.execute('''SELECT id,remaining_qty,remaining_tax_usd,remaining_performance_usd
                              FROM unified_v501_lots WHERE asset=? ORDER BY id''',(asset,)).fetchall():
        if left==0:break
        lid,old_qty,raw_tax,raw_perf=row
        available=number(old_qty)
        take=min(available,left)
        if take==0:continue
        frac=take/available
        tax=number(raw_tax)*frac if raw_tax is not None else None
        perf=number(raw_perf)*frac if raw_perf is not None else None
        share=proceeds_usd*take/amount
        if tax is None:tax_known=False
        else:tax_total+=tax
        if perf is None:perf_known=False
        else:perf_total+=perf
        # Preserve all dust and its remaining USD basis, including unknown/null basis.
        db.execute('''UPDATE unified_v501_lots SET remaining_qty=?,remaining_tax_usd=?,
                     remaining_performance_usd=? WHERE id=?''',
                     (f(available-take),f(number(raw_tax)-tax) if tax is not None else None,
                      f(number(raw_perf)-perf) if perf is not None else None,lid))
        db.execute('''INSERT INTO unified_v501_disposals VALUES (?,?,?,?,?,?,?,?,?)''',
                   (trade_id,lid,asset,f(take),f(tax) if tax is not None else None,
                    f(perf) if perf is not None else None,f(share),
                    f(share-tax) if tax is not None else None,
                    f(share-perf) if perf is not None else None))
        left-=take;consumed+=1
    if left!=0:raise UnifiedSettlementError('FIFO disposal incomplete')
    _change(db,asset,-amount)
    return {'tax_basis_usd':tax_total if tax_known else None,
            'performance_basis_usd':perf_total if perf_known else None,'rows':consumed}


def _identity(*,order_id,product,side,qty,price,fee,fee_ccy,at):
    return '|'.join(map(str,(order_id,product,side,f(qty),f(price),f(fee),fee_ccy,at)))


def _apply_one(db, fill):
    from coincat_cross_quote import split_spot
    tid=str(fill.get('trade_id') or '')
    oid=str(fill.get('order_id') or '')
    product=str(fill.get('product_id') or '')
    side=str(fill.get('side') or '').upper()
    if not tid or not oid or side not in ('BUY','SELL'):
        raise UnifiedSettlementError('Missing verified trade/order/side')
    base,quote=split_spot(product)
    qty=number(fill.get('base_qty'),positive=True)
    price=number(fill.get('price'),positive=True)
    fee=number(fill.get('fee_amount'))
    fee_ccy=fill.get('fee_currency')
    if fee_ccy not in (base,quote) and (not isinstance(fee_ccy,str) or not fee_ccy.isalnum()):
        raise UnifiedSettlementError('Unknown explicit fee currency')
    # USD marks must be from independently verified fill-time evidence.
    marks=fill.get('usd_marks')
    if not isinstance(marks,dict):raise UnifiedSettlementError('Missing authenticated USD marks')
    def rate(asset):
        if asset=='USD':return Decimal(1)
        return number(marks.get(asset),positive=True)
    rb,rq,rf=rate(base),rate(quote),rate(fee_ccy)
    gross=qty*price
    fee_usd=fee*rf
    timestamp=fill.get('at_utc')
    if type(timestamp)!=int or timestamp<=0:
        raise UnifiedSettlementError('Missing verified fill timestamp')
    fp=_identity(order_id=oid,product=product,side=side,qty=qty,price=price,fee=fee,fee_ccy=fee_ccy,at=timestamp)
    existing=db.execute('SELECT fingerprint FROM unified_v501_fills WHERE trade_id=?',(tid,)).fetchone()
    if existing:
        if existing[0]!=fp:raise UnifiedSettlementError('Conflicting duplicate Coinbase trade ID')
        return 'REPLAY_SKIPPED'
    # Distinct line item keys prevent collisions if the fee asset is also the source.
    # A fee in RECEIVED currency reduces net acquisition units instead of creating
    # and then disposing an unverified newly-created lot.
    source=quote if side=='BUY' else base
    target=base if side=='BUY' else quote
    source_qty=gross if side=='BUY' else qty
    target_qty=qty if side=='BUY' else gross
    source_usd=source_qty*rate(source)
    target_usd=target_qty*rate(target)
    extra_source_fee=fee if fee_ccy==source else Decimal(0)
    received_fee=fee if fee_ccy==target else Decimal(0)
    if received_fee>target_qty:raise UnifiedSettlementError('Fee exceeds received amount')
    # Source valuation of acquisition is its USD cost plus exchange commission.
    # Disposal of funding asset remains separately taxable; no double-counted lots.
    spent_usd=(source_qty+extra_source_fee)*rate(source)
    disposal=_dispose(db,source,source_qty+extra_source_fee,spent_usd,tid+':source')
    if fee and fee_ccy not in (source,target):
        _dispose(db,fee_ccy,fee,fee_usd,tid+':fee')
    acquired=target_qty-received_fee
    acquired_basis_usd=source_usd+fee_usd
    _add_lot(db,target,acquired,acquired_basis_usd,acquired_basis_usd,tid)
    db.execute('''INSERT INTO unified_v501_fills VALUES (?,?,?,?,?,?,?,?,?,?)''',
               (tid,oid,product,side,f(qty),f(gross),f(fee),fee_ccy,f(fee_usd),fp))
    return 'APPLIED'


def _high_precision(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        with localcontext() as ctx:
            ctx.prec=120
            return fn(*args,**kwargs)
    return wrapper


@_high_precision
def apply_confirmed_batch(db,*,order,fills,product_catalog,fee_currencies,usd_marks,usd_cap):
    """Validate ALL authenticated order evidence then atomically post the batch.

    Caller is responsible for authenticating order/fills, checking complete
    pagination, and obtaining independent UTC-matched USD marks and fee units.
    No Coinbase client calls here. Isolated v501 tables are never allowed to
    represent successful production migration until verified against old lots.
    """
    from coincat_cross_settlement import validate_filled_cross_order, SettlementBlocked
    from coincat_fill_units import normalize_fill
    if not isinstance(order,dict) or not fills:
        raise UnifiedSettlementError('Missing confirmed order and fills')
    try:
        wallet={r[0]:r[1] for r in db.execute('SELECT asset,qty FROM unified_v501_wallets')}
        reviewed=validate_filled_cross_order(order=order,fills=fills,
             available_before=wallet,fee_currency_by_trade=fee_currencies,
             usd_marks_by_trade=usd_marks,catalog=product_catalog,
             usd_per_order_cap=usd_cap)
    except (SettlementBlocked, ValueError) as exc:
        raise UnifiedSettlementError('Coinbase evidence preflight blocked: '+str(exc)) from exc
    prepared=[]
    for raw in fills:
        amount=normalize_fill(raw)
        tid=str(raw['trade_id'])
        fee_ccy=fee_currencies[tid]
        ts=raw['at_utc']
        marks={asset:usd_marks[(tid,asset)][0] for asset in
               set((order['product_id'].split('-')[0],order['product_id'].split('-')[1],fee_ccy))
               if asset!='USD'}
        prepared.append(dict(trade_id=tid,order_id=order['order_id'],
             product_id=order['product_id'],side=order['side'],
             base_qty=f(amount['base_qty']),price=f(amount['price']),
             fee_amount=f(amount['commission']),fee_currency=fee_ccy,
             at_utc=ts,usd_marks=marks))
    # No partial commits; repeated complete batch is a NOOP if all fingerprints agree.
    db.execute('SAVEPOINT v501_confirmed_batch')
    try:
        verify(db)
        statuses=[_apply_one(db,record) for record in prepared]
        verify(db)
        db.execute('RELEASE v501_confirmed_batch')
    except BaseException:
        db.execute('ROLLBACK TO v501_confirmed_batch')
        db.execute('RELEASE v501_confirmed_batch')
        raise
    return {'result':'APPLIED' if 'APPLIED' in statuses else 'REPLAY_NOOP',
            'fills':len(fills),'fee_usd':reviewed['total_fee_usd'],
            'notional_usd':reviewed['gross_notional_usd']}
