"""Independent acquisition lots for verified Coinbase fills and authorized legacy holdings.

Conversion plans are NOT fills. All money movements still require the existing
Coinbase broker and its hard caps. Opening lots retain unknown tax basis.
"""
from decimal import Decimal
EPS = Decimal('0.000000000001')

def D(v):
    n=Decimal(str(v))
    if not n.is_finite() or n<0: raise ValueError('Invalid lot amount')
    return n

def F(v):
    """Format signed P&L without treating a legitimate loss as invalid size.

    Quantity validators use D() and still forbid negative holdings.
    """
    n=Decimal(str(v))
    if not n.is_finite():raise ValueError('Invalid financial amount')
    return format(n,'f')

def install(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS inventory_lots(
      lot_id TEXT PRIMARY KEY,asset TEXT NOT NULL,source TEXT NOT NULL,
      source_trade_id TEXT UNIQUE,opened_at INTEGER NOT NULL,
      initial_qty TEXT NOT NULL,remaining_qty TEXT NOT NULL,
      performance_unit_quote TEXT,tax_unit_quote TEXT,quote_ccy TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_inventory_asset ON inventory_lots(asset,opened_at,lot_id);
    CREATE TABLE IF NOT EXISTS inventory_disposals(
      trade_id TEXT NOT NULL,lot_id TEXT NOT NULL,used_qty TEXT NOT NULL,
      performance_basis_quote TEXT NOT NULL,tax_basis_quote TEXT,
      fee_quote TEXT NOT NULL,performance_realized_quote TEXT NOT NULL,
      tax_realized_quote TEXT,PRIMARY KEY(trade_id,lot_id));
    ''')

def seed_opening(db,asset=None):
    """Only the *remaining* old inventory is migrated; historical fills untouched."""
    q="SELECT * FROM enrollment WHERE asset NOT IN ('USD','USDC')"
    args=()
    if asset:q+=' AND asset=?';args=(asset,)
    for r in db.execute(q,args).fetchall():
        name=r['asset'];qty=D(r['remaining_qty'])
        if qty<=0 or db.execute('SELECT 1 FROM inventory_lots WHERE asset=?',(name,)).fetchone():continue
        bot=r['basis_source']=='BOT_FILL'
        src='LEGACY_BOT_FILL' if bot else 'PERSONAL_OPENING'
        # Never use an old manually typed tax-cost field as a CURRENT USD
        # performance entry. Personal units require a real market snapshot.
        perf=(r['basis_unit_quote'] if bot else r['snapshot_unit_usd'])
        # Legacy personal snapshots use an explicitly captured USD bid.
        # For a legacy BOT_FILL, source quote currency is not always provable.
        # Reuse source currency ONLY if all historic buys are same quote.
        if bot:
            quotes={x[0].split('-')[-1] for x in db.execute("SELECT DISTINCT pair FROM fills WHERE side='BUY' AND substr(pair,1,instr(pair,'-')-1)=?",(name,))}
            quote=next(iter(quotes)) if len(quotes)==1 else 'UNVERIFIED'
        else:quote='USD'
        db.execute('''INSERT INTO inventory_lots VALUES(?,?,?,?,?,?,?,?,?,?)''',(
           'opening:'+name,name,src,None,int(r['approved_at']),F(qty),F(qty),perf,r['basis_unit_quote'],quote))

def sync_personal_basis(db,asset):
    seed_opening(db,asset)
    r=db.execute('SELECT * FROM enrollment WHERE asset=?',(asset,)).fetchone()
    if r:
        db.execute('''UPDATE inventory_lots SET performance_unit_quote=?,tax_unit_quote=?
            WHERE lot_id=? AND source='PERSONAL_OPENING' ''',
            (r['snapshot_unit_usd'],r['basis_unit_quote'],'opening:'+asset))

def verify(db,asset):
    seed_opening(db,asset)
    r=db.execute('SELECT remaining_qty FROM enrollment WHERE asset=?',(asset,)).fetchone()
    if not r:raise ValueError('Missing enrollment record')
    total=sum((D(x['remaining_qty']) for x in db.execute('SELECT remaining_qty FROM inventory_lots WHERE asset=?',(asset,))),Decimal(0))
    if abs(total-D(r['remaining_qty']))>EPS:
        raise ValueError('Lots do not reconcile with authorized balance; do not trade')
    return total

def new_buy(db,trade_id,asset,qty,price,fee,quote,at):
    if db.execute('SELECT 1 FROM enrollment WHERE asset=?',(asset,)).fetchone():verify(db,asset)
    qty=D(qty);price=D(price);fee=D(fee)
    if qty<=0 or price<=0 or quote not in ('USD','USDC'):raise ValueError('Invalid confirmed BUY fill')
    basis=(qty*price+fee)/qty
    db.execute('''INSERT INTO inventory_lots VALUES(?,?,?,?,?,?,?,?,?,?)''',(
      'buy:'+trade_id,asset,'COINBASE_CONFIRMED_BUY',trade_id,int(at),F(qty),F(qty),
      F(basis),F(basis),quote))

def sale_basis(db,asset,qty,quote):
    """FIFO for a specific sell size, not average-cost tax fabrication."""
    verify(db,asset)
    left=D(qty);performance=Decimal(0);tax=Decimal(0);all_tax_known=True;used=[]
    if left<=0:raise ValueError('Empty proposed SELL')
    for r in db.execute("SELECT * FROM inventory_lots WHERE asset=? ORDER BY CASE WHEN source IN ('PERSONAL_OPENING','LEGACY_BOT_FILL') THEN 0 ELSE 1 END,opened_at,lot_id",(asset,)):
        if left<=EPS:break
        available=D(r['remaining_qty']);take=min(left,available)
        if take<=0:continue
        if r['quote_ccy']!=quote:raise ValueError('Unverified USD/USDC cost currency mix')
        if r['performance_unit_quote'] is None:raise ValueError('Unpriced personal lot; require approved market snapshot')
        perf=take*D(r['performance_unit_quote'])
        # Historic PERSONAL_OPENING cost was manually editable and does not
        # constitute verified acquisition evidence, even when non-NULL.
        tbase=(take*D(r['tax_unit_quote']) if r['tax_unit_quote'] is not None
               and r['source']!='PERSONAL_OPENING' else None)
        performance+=perf
        if tbase is None:all_tax_known=False
        else:tax+=tbase
        used.append((r,take,perf,tbase));left-=take
    if left>EPS:raise ValueError('Not enough verified inventory lots for SELL')
    return {'performance_basis':performance,'tax_basis':tax if all_tax_known else None,'lots':used}

def sell_fill(db,trade_id,asset,qty,price,fee,quote):
    info=sale_basis(db,asset,qty,quote);qty=D(qty);price=D(price);fee=D(fee)
    for r,take,perf,tax in info['lots']:
        share=fee*take/qty
        rperf=take*price-share-perf
        rtax=take*price-share-tax if tax is not None else None
        db.execute('UPDATE inventory_lots SET remaining_qty=? WHERE lot_id=?',(F(D(r['remaining_qty'])-take),r['lot_id']))
        db.execute('''INSERT INTO inventory_disposals VALUES(?,?,?,?,?,?,?,?)''',(
          trade_id,r['lot_id'],F(take),F(perf),F(tax) if tax is not None else None,
          F(share),F(rperf),F(rtax) if rtax is not None else None))
    return info

def average_performance(db,asset):
    try:
        qty=verify(db,asset)
        if qty<=EPS:return None
        rows=db.execute('SELECT * FROM inventory_lots WHERE asset=?',(asset,)).fetchall()
        if any(D(r['remaining_qty'])>0 and r['performance_unit_quote'] is None for r in rows):return None
        return F(sum((D(r['remaining_qty'])*D(r['performance_unit_quote']) for r in rows if D(r['remaining_qty'])>0),Decimal(0))/qty)
    except (ValueError,TypeError):return None

def list_lots(db,asset=None):
    q='SELECT * FROM inventory_lots'
    if asset:q+=' WHERE asset=?'
    return [dict(r) for r in db.execute(q+" ORDER BY asset,CASE WHEN source IN ('PERSONAL_OPENING','LEGACY_BOT_FILL') THEN 0 ELSE 1 END,opened_at,lot_id",(asset,) if asset else ())]
