"""CoinCat v50: real Coinbase order pathway with fail-closed enrollment and execution.

No exchange orders are placed on import. The explicit `arm()` operation is RAM-only;
all live activity requires enrolled liquid balances, current Coinbase permission,
fresh public quotes, a real Coinbase preview, and hard spending/loss caps.

No withdrawals, transfers, margin, perps, leverage, or Coinbase Convert.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN
from pathlib import Path
import csv, os, sqlite3, time, uuid, re, json

from coinbase_account import as_dict, aggregate_balances
from coincat_fill_units import normalize_fill, summarize_fills, verify_order_totals, FillUnitError
from coincat_cross_quote import SPOT_PAIR_RE
import coincat_inventory_lots as lots
def D(value):
    value=Decimal(str(value))
    if not value.is_finite():raise ValueError('Expected finite decimal')
    return value

def minimum_exit_price(entry,buy_fee,sell_fee,net_target,expected_sell_slippage_bps=0):
    return D(entry)*(1+D(buy_fee))*(1+D(net_target))/((1-D(sell_fee))*(1-D(expected_sell_slippage_bps)/10000))

# Original dollar-quoted journal is retained for historical fill reconciliation ONLY.
HISTORICAL_FILL_PAIR_RE=re.compile(r'^[A-Z0-9]{2,20}-(USD|USDC)$')
TERMINAL={'FILLED','COMPLETED','REJECTED','CANCELLED','EXPIRED','FAILED'}
PENDING={'SUBMISSION_PENDING','ACKNOWLEDGED','OPEN','UNKNOWN','PARTIALLY_FILLED','RECONCILE_ERROR','PENDING','PARTIAL'}

class LiveBlocked(Exception):pass

def dec(v):
    try: n=D(v)
    except Exception as ex:raise LiveBlocked('Non-numeric or invalid Coinbase amount') from ex
    if n<0:raise LiveBlocked('Negative Coinbase value')
    return n

def fmt(v):return format(D(v),'f')

def floor_to(value,increment):
    step=dec(increment)
    if step<=0:raise LiveBlocked('No valid Coinbase market increment')
    return (D(value)/step).to_integral_value(rounding=ROUND_DOWN)*step

def client_from_credentials(creds):
    from coinbase.rest import RESTClient
    return RESTClient(api_key=creds['name'],api_secret=creds['privateKey'],timeout=15,verbose=False)

@contextmanager
def sql(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30)
    try:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=30000')
        db.row_factory=sqlite3.Row
        with db:yield db
    finally:db.close()

class LiveLedger:
    def __init__(self,path):
        self.path=Path(path)
        with sql(path) as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS enrollment(asset TEXT PRIMARY KEY, authorized_qty TEXT NOT NULL,
                remaining_qty TEXT NOT NULL, basis_unit_quote TEXT, approved_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(cid TEXT PRIMARY KEY, order_id TEXT UNIQUE,pair TEXT NOT NULL,
                side TEXT NOT NULL,requested_size TEXT NOT NULL,preview_fee TEXT NOT NULL,
                state TEXT NOT NULL, created_at INTEGER NOT NULL, checked_at INTEGER, detail TEXT);
            CREATE TABLE IF NOT EXISTS fills(trade_id TEXT PRIMARY KEY, cid TEXT NOT NULL,order_id TEXT NOT NULL,
                pair TEXT NOT NULL,side TEXT NOT NULL,base_qty TEXT NOT NULL,price TEXT NOT NULL,
                fee_quote TEXT NOT NULL,at_utc INTEGER NOT NULL, cost_basis_quote TEXT,net_realized_quote TEXT);
            CREATE TABLE IF NOT EXISTS risk(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at_utc INTEGER,event TEXT,detail TEXT);
            CREATE INDEX IF NOT EXISTS idx_fills_time ON fills(at_utc);
            CREATE TABLE IF NOT EXISTS signal_audit(id INTEGER PRIMARY KEY,at_utc INTEGER NOT NULL,
                pair TEXT NOT NULL,entry_ask TEXT NOT NULL,spread_bps TEXT NOT NULL,
                momentum_pct TEXT NOT NULL,state TEXT NOT NULL,detail TEXT,client_order_id TEXT);
            ''')
            cols={row[1] for row in c.execute('PRAGMA table_info(enrollment)')}
            if 'enabled' not in cols:
                c.execute('ALTER TABLE enrollment ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
            # Separate the trading mark from ORIGINAL purchase cost. Existing NULL
            # original bases stay NULL; no backfilled estimates are invented.
            for name,typ in (
                ('snapshot_unit_usd','TEXT'),('snapshot_qty','TEXT'),
                ('snapshot_at','INTEGER'),('snapshot_pair','TEXT'),
                ('basis_source',"TEXT NOT NULL DEFAULT 'LEGACY'"),
            ):
                if name not in cols:c.execute(f'ALTER TABLE enrollment ADD COLUMN {name} {typ}')
            # Legacy bot-acquired positions should always retain exact cost from
            # fills; identify them WITHOUT mutating their existing basis.
            c.execute('''UPDATE enrollment SET basis_source='BOT_FILL'
                WHERE asset IN (SELECT DISTINCT substr(pair,1,instr(pair,'-')-1)
                                FROM fills WHERE side='BUY')
                  AND basis_unit_quote IS NOT NULL AND snapshot_unit_usd IS NULL
                  AND basis_source='LEGACY' ''')
            fcols={row[1] for row in c.execute('PRAGMA table_info(fills)')}
            for name,typ in (('performance_basis_quote','TEXT'),
                             ('performance_realized_quote','TEXT'),
                             ('basis_provenance','TEXT')):
                if name not in fcols:c.execute(f'ALTER TABLE fills ADD COLUMN {name} {typ}')
            ocols={row[1] for row in c.execute('PRAGMA table_info(orders)')}
            if 'purpose' not in ocols:
                c.execute("ALTER TABLE orders ADD COLUMN purpose TEXT NOT NULL DEFAULT 'AUTOTRADE'")
            c.execute('''CREATE TABLE IF NOT EXISTS enrollment_snapshots(
                id INTEGER PRIMARY KEY,asset TEXT NOT NULL,quantity TEXT NOT NULL,
                bid_usd TEXT NOT NULL,at_utc INTEGER NOT NULL,pair TEXT NOT NULL,
                authorization_text TEXT NOT NULL)''')
            lots.install(c)
            from coincat_v601_baseline import install as install_performance_periods
            install_performance_periods(c)
            # Isolated, append-only evidence for future verified cross-currency
            # settlement. Does not alter existing fills, approval or tax lots.
            from coincat_verified_cross_fills import install_cross_audit
            install_cross_audit(c)
            lots.seed_opening(c)  # additive one-time migration of REMAINING legacy holdings
    def log(self,event,detail=''):
        with sql(self.path) as c:c.execute('INSERT INTO events(at_utc,event,detail) VALUES(?,?,?)',(int(time.time()),event,str(detail)[:300]))
    def setting(self,key,default=None):
        with sql(self.path) as c:
            r=c.execute('SELECT value FROM risk WHERE key=?',(key,)).fetchone()
            return r['value'] if r else default
    def set_setting(self,key,value):
        with sql(self.path) as c:c.execute('INSERT INTO risk(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
    def approve_all(self,available):
        """Fresh complete Coinbase snapshot verified by caller; approval from user in GUI.
        Replaces remaining allocation only before ANY orders, to avoid replenishing spent funds.
        Never changes already approved base lots without explicit review.
        """
        with sql(self.path) as c:
            if c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]:
                raise LiveBlocked('Existing live order history: no blanket re-enrollment. Manual reconciliation required.')
            if not available:raise LiveBlocked('No eligible available balances to enroll')
            c.execute('DELETE FROM enrollment')
            now=int(time.time())
            for asset,qty in available.items():
                qty=dec(qty)
                if qty>0:
                    c.execute('INSERT INTO enrollment(asset,authorized_qty,remaining_qty,basis_unit_quote,approved_at) VALUES(?,?,?,?,?)',(asset,fmt(qty),fmt(qty),
                        '1' if asset in ('USD','USDC') else None,now))
        with sql(self.path) as c:
            c.execute('DELETE FROM inventory_lots')  # allowed only before ANY real order history
            lots.seed_opening(c)
        self.log('ASSET_ENROLL_APPROVED',','.join(sorted(available)))
    def initial_auto_enroll_if_empty(self,available):
        """One-time user-requested enrollment of current liquid balances.

        Never resets an existing enrollment, un-excludes a deliberately excluded
        asset, replenishes traded funds, changes existing inventory lots, or
        imports old version holdings. A real order history also forbids bootstrap.
        This method is transactionally idempotent across restarts/refreshes.
        """
        if not available:
            return {'created':False,'count':0}
        now=int(time.time())
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM enrollment LIMIT 1').fetchone():
                return {'created':False,'count':0}
            if c.execute('SELECT 1 FROM orders LIMIT 1').fetchone():
                raise LiveBlocked('Existing order history prevents automatic initial enrollment')
            if c.execute('SELECT 1 FROM inventory_lots LIMIT 1').fetchone():
                raise LiveBlocked('Existing inventory lots prevent automatic initial enrollment')
            count=0
            for asset,raw in sorted(available.items()):
                quantity=dec(raw)
                if quantity<=0:continue
                c.execute("INSERT INTO enrollment(asset,authorized_qty,remaining_qty,basis_unit_quote,approved_at,enabled) VALUES(?,?,?,?,?,1)",
                    (asset,fmt(quantity),fmt(quantity), '1' if asset in ('USD','USDC') else None,now))
                count+=1
            if count<=0:raise LiveBlocked('No positive eligible available balances')
            lots.seed_opening(c)
            c.execute('INSERT INTO events(at_utc,event,detail) VALUES(?,?,?)',
                (now,'INITIAL_AUTO_ENROLL','authorized initial liquid portfolio; assets='+str(count)))
        return {'created':True,'count':count}

    def auto_enroll_new_spot_available(self, balances, valid_assets):
        '''Explicit user-opted continuing enrollment of NEW available spot assets.

        Authenticated AVAILABLE amounts are eligible trading inventory, but a
        balance alone does NOT establish purchase history or taxable basis.
        Existing and EXCLUDED rows are never replenished or re-enabled.
        Idempotent BEGIN IMMEDIATE protects against concurrent refreshes.
        Only called after independent balance reconciliation is safe; NEVER
        called to fix existing shortfalls or ambiguous/unsettled live orders.
        '''
        if not isinstance(balances,dict) or not isinstance(valid_assets,(set,list,tuple)):
            raise LiveBlocked('Missing verified spot account/catalog inputs')
        verified=set(valid_assets);now=int(time.time());created=[]
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM orders WHERE state NOT IN (%s) LIMIT 1' % ','.join('?'*len(TERMINAL)),tuple(TERMINAL)).fetchone():
                return {'created':0,'deferred':'UNRESOLVED_ORDER','assets':[]}
            existing={row['asset'] for row in c.execute('SELECT asset FROM enrollment')}
            for asset,raw in sorted(balances.items()):
                if not isinstance(asset,str) or asset not in verified or asset in existing:continue
                try:qty=dec(raw)
                except (LiveBlocked,ValueError,TypeError):continue
                if not qty.is_finite() or qty<=0:continue
                # UNKNOWN original cost is deliberate: outside purchases and
                # transfers cannot be inferred from a balance observation.
                c.execute('''INSERT INTO enrollment(asset,authorized_qty,remaining_qty,
                    basis_unit_quote,approved_at,enabled,basis_source)
                    VALUES(?,?,?,?,?,1,'EXTERNAL_AVAILABLE_UNVERIFIED_BASIS')''',
                    (asset,fmt(qty),fmt(qty),None,now))
                existing.add(asset);created.append(asset)
            for asset in created:lots.seed_opening(c,asset)
            if created:
                c.execute('INSERT INTO events(at_utc,event,detail) VALUES(?,?,?)',
                    (now,'AUTO_ENROLL_NEW_AVAILABLE',f'new_spot_assets={len(created)}; cost_basis=UNKNOWN'))
        return {'created':len(created),'deferred':None,'assets':created}

    def snapshot_market_basis(self,asset,price_usd,*,pair,available_qty,
                              authorization,now=None):
        """Explicitly approved liquid inventory gets a frozen market-performance mark.

        NEVER fill missing original tax basis or change verified bot-fill basis.
        A quote is provided by the broker AFTER a fresh authenticated exchange
        market lookup and account balance re-check. Revalidate under transaction.
        """
        asset=asset.upper();price=dec(price_usd);available=dec(available_qty)
        now=int(time.time() if now is None else now)
        if asset in ('USD','USDC') or price<=0:
            raise LiveBlocked('Market snapshots are only for approved crypto with a positive USD bid')
        if pair not in (asset+'-USD',asset+'-USDC'):
            raise LiveBlocked('Snapshot source must match the enrolled Coinbase asset')
        if authorization not in ('SNAPSHOT '+asset,'SNAPSHOT APPROVED','V21 INITIAL AUTO','V40 INITIAL AUTO','V50 INITIAL AUTO'):
            raise LiveBlocked('Explicit snapshot authorization was not provided')
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM orders WHERE state IN (%s)' % ','.join('?'*len(PENDING)),tuple(PENDING)).fetchone()[0]:
                raise LiveBlocked('Cannot establish a market basis while a Coinbase order is unresolved')
            row=c.execute('SELECT * FROM enrollment WHERE asset=?',(asset,)).fetchone()
            if not row or not row['enabled']:
                raise LiveBlocked('Asset is not currently approved for CoinCat management')
            qty=dec(row['remaining_qty'])
            if qty<=0 or available<qty:
                raise LiveBlocked('Coinbase liquid balance is below approved quantity; refresh/review first')
            if row['snapshot_unit_usd'] is not None:
                raise LiveBlocked('Snapshot already frozen; do not reset performance baseline')
            if row['basis_source']=='BOT_FILL' or c.execute('''
                SELECT 1 FROM fills WHERE side='BUY'
                AND substr(pair,1,instr(pair,'-')-1)=? LIMIT 1''',(asset,)).fetchone():
                raise LiveBlocked('Verified CoinCat-purchased inventory must retain actual fill cost basis')
            c.execute('''UPDATE enrollment SET snapshot_unit_usd=?,snapshot_qty=?,
                snapshot_at=?,snapshot_pair=? WHERE asset=?''',
                (fmt(price),fmt(qty),now,pair,asset))
            lots.sync_personal_basis(c,asset)
            c.execute('''INSERT INTO enrollment_snapshots(
                asset,quantity,bid_usd,at_utc,pair,authorization_text)
                VALUES(?,?,?,?,?,?)''',(asset,fmt(qty),fmt(price),now,pair,authorization))
        self.log('PERFORMANCE_SNAPSHOT_AUTHORIZED',f'{asset}: {fmt(qty)} @ {fmt(price)} {pair} | original cost unchanged')
        return {'asset':asset,'qty':fmt(qty),'bid_usd':fmt(price),'at_utc':now,'pair':pair}

    def set_asset_enabled(self,asset,enabled):
        """User-controlled approval toggle. Always disarm separately; never silently top up."""
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM orders WHERE state IN (%s)' % ','.join('?'*len(PENDING)),tuple(PENDING)).fetchone()[0]:
                raise LiveBlocked('Cannot modify enrollment with a pending or uncertain real Coinbase order')
            row=c.execute('SELECT remaining_qty FROM enrollment WHERE asset=?',(asset,)).fetchone()
            if not row:raise LiveBlocked('Not previously enrolled; select ENROLLED in the asset Status dropdown first')
            if not enabled:
                # A bot-bought position cannot be orphaned by disabling management.
                fills=c.execute('SELECT side,base_qty FROM fills WHERE substr(pair,1,instr(pair,"-")-1)=?',(asset,)).fetchall()
                net=sum((D(x['base_qty'])*(1 if x['side']=='BUY' else -1) for x in fills),Decimal(0))
                if net>Decimal('0.000000000001') and D(row['remaining_qty'])>0:
                    raise LiveBlocked('Open bot-acquired inventory: close/reconcile it before excluding this coin')
            c.execute('UPDATE enrollment SET enabled=? WHERE asset=?',(1 if enabled else 0,asset))
        self.log('ASSET_ENABLED' if enabled else 'ASSET_EXCLUDED',asset)

    def approve_one(self,asset,quantity):
        """Requires separate typed per-asset approval and live Coinbase re-check by broker."""
        qty=dec(quantity)
        if qty<=0:raise LiveBlocked('No available liquid quantity')
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM orders WHERE state IN (%s)' % ','.join('?'*len(PENDING)),tuple(PENDING)).fetchone()[0]:
                raise LiveBlocked('Pending/uncertain order prevents adding managed assets')
            existing=c.execute('SELECT asset FROM enrollment WHERE asset=?',(asset,)).fetchone()
            if existing:raise LiveBlocked('This coin is already enrolled or excluded; use the toggle instead')
            c.execute('INSERT INTO enrollment(asset,authorized_qty,remaining_qty,basis_unit_quote,approved_at,enabled) VALUES(?,?,?,?,?,1)',
                      (asset,fmt(qty),fmt(qty),'1' if asset in ('USD','USDC') else None,int(time.time())))
        with sql(self.path) as c:lots.seed_opening(c,asset)
        self.log('SINGLE_ASSET_APPROVED',asset)

    def log_signal(self,pair,ask,spread_bps,momentum_pct,state='QUALIFIED',detail=''):
        with sql(self.path) as c:
            cur=c.execute('INSERT INTO signal_audit(at_utc,pair,entry_ask,spread_bps,momentum_pct,state,detail) VALUES(?,?,?,?,?,?,?)',
                          (int(time.time()),pair,fmt(ask),fmt(spread_bps),fmt(momentum_pct),state,str(detail)[:250]))
            return cur.lastrowid

    def signal_state(self,signal_id,state,detail='',cid=None):
        with sql(self.path) as c:
            c.execute('UPDATE signal_audit SET state=?,detail=?,client_order_id=? WHERE id=?',
                      (state,str(detail)[:250],cid,signal_id))

    def set_basis(self,asset,basis):
        """v60.1: reject manual tax cost edits; existing historical rows untouched."""
        raise LiveBlocked("Manual original purchase-cost editing was retired. Today's verified USD price is a performance starting point, NOT tax basis; use authenticated exchange acquisition records for tax lots.")

    def snapshot_history(self,asset=None):
        with sql(self.path) as c:
            query='SELECT * FROM enrollment_snapshots'
            args=()
            if asset:query+=' WHERE asset=?';args=(asset,)
            return [dict(x) for x in c.execute(query+' ORDER BY at_utc,id',args)]
    def assets(self):
        with sql(self.path) as c:
            lots.seed_opening(c)
            out=[]
            for r in c.execute('SELECT * FROM enrollment ORDER BY asset'):
                item=dict(r)
                if r['asset'] not in ('USD','USDC'):
                    item['trading_basis_unit_quote']=lots.average_performance(c,r['asset'])
                out.append(item)
            return out
    def asset(self,asset):
        with sql(self.path) as c:
            lots.seed_opening(c,asset)
            row=c.execute('SELECT * FROM enrollment WHERE asset=? AND enabled=1',(asset,)).fetchone()
            if row:
                item=dict(row)
                if asset not in ('USD','USDC'):
                    item['trading_basis_unit_quote']=lots.average_performance(c,asset)
                return item
            return None
    def inventory_lots(self,asset=None):
        with sql(self.path) as c:
            lots.seed_opening(c,asset)
            return lots.list_lots(c,asset)
    def sale_basis(self,asset,size,quote):
        with sql(self.path) as c:return lots.sale_basis(c,asset,size,quote)

    def pending(self):
        with sql(self.path) as c:
            row=c.execute('SELECT * FROM orders WHERE state NOT IN (%s) ORDER BY created_at DESC LIMIT 1' % ','.join('?'*len(TERMINAL)),tuple(TERMINAL)).fetchone()
            return dict(row) if row else None
    def most_recent(self):
        with sql(self.path) as c:
            row=c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 1').fetchone()
            return dict(row) if row else None
    def update_order(self,cid,**kw):
        safe={k:v for k,v in kw.items() if k in ('order_id','state','checked_at','detail')}
        if not safe:return
        with sql(self.path) as c:
            c.execute('UPDATE orders SET '+','.join(k+'=?' for k in safe)+' WHERE cid=?',tuple(safe.values())+(cid,))
    def stage(self,pair,side,size,preview_fee,now=None,*,purpose='AUTOTRADE'):
        now=int(time.time() if now is None else now)
        cid=str(uuid.uuid4())
        with sql(self.path) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT value FROM risk WHERE key='halted'").fetchone()
            if row and row['value']=='1':raise LiveBlocked('Emergency STOP active before submission')
            if c.execute('SELECT COUNT(*) FROM orders WHERE state IN (%s)' % ','.join('?'*len(PENDING)),tuple(PENDING)).fetchone()[0]:
                raise LiveBlocked('Pending/uncertain Coinbase order; reconciliation required first')
            c.execute('INSERT INTO orders(cid,pair,side,requested_size,preview_fee,state,created_at,purpose) VALUES(?,?,?,?,?,?,?,?)',
                (cid,pair,side,fmt(size),fmt(preview_fee),'SUBMISSION_PENDING',now,purpose))
        return cid
    def today_stats(self,now=None):
        now=int(now or time.time())
        day=int(datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        with sql(self.path) as c:
            r=c.execute('SELECT COALESCE(SUM(CAST(COALESCE(performance_realized_quote,net_realized_quote) AS REAL)),0) pnl FROM fills WHERE at_utc>=?',(day,)).fetchone()
            n=c.execute('SELECT COUNT(*) n FROM orders WHERE created_at>=?',(now-86400,)).fetchone()['n']
            spend=c.execute("SELECT COALESCE(SUM(CAST(base_qty AS REAL)*CAST(price AS REAL)+CAST(fee_quote AS REAL)),0) v FROM fills WHERE side='BUY' AND at_utc>=?",(day,)).fetchone()['v']
            fees=c.execute('SELECT COALESCE(SUM(CAST(fee_quote AS REAL)),0) v FROM fills').fetchone()['v']
            gross_buy=c.execute("SELECT COALESCE(SUM(CAST(base_qty AS REAL)*CAST(price AS REAL)),0) v FROM fills WHERE side='BUY'").fetchone()['v']
            total_pnl=c.execute('SELECT COALESCE(SUM(CAST(COALESCE(performance_realized_quote,net_realized_quote) AS REAL)),0) v FROM fills').fetchone()['v']
            # Count completed SELL *orders*, not individual fill rows. One Coinbase
            # order can settle in multiple fills; each order is one win/loss.
            # Ignore orders with any missing performance result to avoid claiming
            # an unverified monetary outcome. BUY fills are never wins/losses.
            sell_rows=c.execute("""SELECT o.cid, f.performance_realized_quote, f.net_realized_quote
                FROM orders o JOIN fills f ON f.cid=o.cid AND f.order_id=o.order_id
                WHERE o.side='SELL' AND f.side='SELL' AND o.state='FILLED'
                AND o.purpose='AUTOTRADE' ORDER BY o.cid, f.trade_id""").fetchall()
            grouped={}
            for entry in sell_rows:
                cid=entry['cid']
                value=entry['performance_realized_quote']
                if value is None:value=entry['net_realized_quote']
                if cid not in grouped:grouped[cid]=[]
                grouped[cid].append(None if value is None else D(value))
            complete=[sum(vals,Decimal(0)) for vals in grouped.values()
                      if vals and all(v is not None for v in vals)]
            wins=sum(1 for result in complete if result>0)
            losses=sum(1 for result in complete if result<=0)
            return dict(day_pnl=D(r['pnl']),order_count=n,day_spend=D(spend),fees=D(fees),buy_spend=D(gross_buy),realized=D(total_pnl),wins=wins,losses=losses)
    def pair_performance(self,pair):
        with sql(self.path) as c:
            rows=c.execute("SELECT COALESCE(f.performance_realized_quote,f.net_realized_quote) AS net_realized_quote FROM fills f JOIN orders o ON f.cid=o.cid WHERE f.pair=? AND o.purpose='AUTOTRADE' AND COALESCE(f.performance_realized_quote,f.net_realized_quote) IS NOT NULL ORDER BY f.at_utc,f.trade_id",(pair,)).fetchall()
        return [D(r[0]) for r in rows]
    def fills(self):
        with sql(self.path) as c:return [dict(x) for x in c.execute("SELECT f.*,COALESCE(o.purpose,'AUTOTRADE') AS order_purpose FROM fills f LEFT JOIN orders o ON f.cid=o.cid ORDER BY f.at_utc DESC LIMIT 2000")]
    def orders(self):
        with sql(self.path) as c:return [dict(x) for x in c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 2000')]
    def apply_fills(self,cid,order_id,pair,side,fills,now=None):
        """Transactionally book actual Coinbase fill quantities and commissions once.
        Partial/unsupported fee-currency snapshots fail closed before any mutation.
        """
        # The historical settlement journal stores dollar-quoted records. The isolated cross-audit is
        # NOT a drop-in replacement for taxable USD FIFO settlement.
        if not HISTORICAL_FILL_PAIR_RE.fullmatch(pair):
            raise LiveBlocked('Historical fill reader cannot post new multi-currency fills; unified production settlement not certified')
        now=int(time.time() if now is None else now)
        base,quote=pair.split('-')
        normalized=[]
        for f in fills:
            if str(f.get('order_id') or '')!=order_id:raise LiveBlocked('Fill order ID mismatch')
            trade_id=str(f.get('trade_id') or '')
            if not trade_id:raise LiveBlocked('Coinbase fill lacks unique trade_id')
            if f.get('product_id') not in (None,pair) or str(f.get('side',side)).upper()!=side:
                raise LiveBlocked('Coinbase fill product/side does not match requested order')
            try:
                amounts=normalize_fill(f)
            except FillUnitError as exc:
                raise LiveBlocked(str(exc)) from exc
            qty=amounts['base_qty'];price=amounts['price'];fee=amounts['commission']
            if qty<=0 or price<=0:raise LiveBlocked('Empty/invalid fill; reconciliation halted')
            # commission field on Coinbase Advanced spot fills is quote-denominated.
            detail=f.get('commission_detail_total') or {}
            if isinstance(detail,dict):
                for curr,v in detail.items():
                    # SDK may report total_commission and tax breakdown amounts,
                    # not currency codes. Honor explicit currency keys only.
                    if curr.upper() in ('CURRENCY','FEE_CURRENCY','COMMISSION_CURRENCY') and str(v).upper()!=quote:
                        raise LiveBlocked('Non-quote Coinbase commission cannot be valued safely')
            normalized.append((trade_id,qty,price,fee))
        if not normalized:raise LiveBlocked('No Coinbase fill records to reconcile')
        with sql(self.path) as c:
            order=c.execute('SELECT state FROM orders WHERE cid=? AND order_id=?',(cid,order_id)).fetchone()
            if not order:raise LiveBlocked('Local order ID missing during reconciliation')
            c.execute('BEGIN IMMEDIATE')
            for trade_id,qty,price,fee in normalized:
                existing=c.execute('SELECT 1 FROM fills WHERE trade_id=?',(trade_id,)).fetchone()
                if existing:continue
                b=c.execute('SELECT remaining_qty,basis_unit_quote,snapshot_unit_usd,basis_source FROM enrollment WHERE asset=?',(base,)).fetchone()
                q=c.execute('SELECT remaining_qty FROM enrollment WHERE asset=?',(quote,)).fetchone()
                if side=='BUY':
                    if not q:raise LiveBlocked('Quote wallet was not authorized')
                    cost=qty*price+fee
                    remaining=D(q['remaining_qty'])-cost
                    if remaining<Decimal('-0.0000001'):raise LiveBlocked('Actual purchase exceeded approved quote budget; reconcile manually')
                    c.execute('UPDATE enrollment SET remaining_qty=? WHERE asset=?',(fmt(max(Decimal(0),remaining)),quote))
                    # Verify the prior balance is represented as distinct lots
                    # BEFORE adding a new acquisition lot. No old tax basis changed.
                    if b:lots.verify(c,base)
                    lots.new_buy(c,trade_id,base,qty,price,fee,quote,now)
                    if b:
                        old_qty=D(b['remaining_qty'])
                        # Mixed old/new inventory MUST NOT be represented by one
                        # fabricated acquisition price. FIFO lot records own basis.
                        if old_qty>0 and b['basis_source']=='BOT_FILL' and b['basis_unit_quote'] is not None:
                            # Multiple verified fills of the same bot-owned asset
                            # can show an informational aggregate acquisition cost.
                            new_basis=(old_qty*D(b['basis_unit_quote'])+cost)/(old_qty+qty)
                            new_source='BOT_FILL'
                        elif old_qty>0:
                            new_basis=None;new_source='MIXED_LOTS'
                        else:
                            new_basis=cost/qty;new_source='BOT_FILL'
                        c.execute('UPDATE enrollment SET remaining_qty=?,basis_unit_quote=?,basis_source=? WHERE asset=?',
                                  (fmt(old_qty+qty),fmt(new_basis) if new_basis is not None else None,new_source,base))
                    else:
                        c.execute('INSERT INTO enrollment(asset,authorized_qty,remaining_qty,basis_unit_quote,approved_at,basis_source) VALUES(?,?,?,?,?,?)',(base,fmt(qty),fmt(qty),fmt(cost/qty),now,'BOT_FILL'))
                    basis=None;net=None;perf_basis=None;perf_net=None;basis_provenance='BUY_VERIFIED'
                else:
                    if not b:raise LiveBlocked('SELL has no approved base inventory')
                    old_qty=D(b['remaining_qty'])
                    if qty>old_qty+Decimal('0.0000000000001'):raise LiveBlocked('Sell exceeds local bot-managed base quantity')
                    # A separate FIFO lot disposal row is retained for every
                    # affected acquisition lot. Unknown original tax cost stays NULL.
                    try:
                        used=lots.sell_fill(c,trade_id,base,qty,price,fee,quote)
                    except ValueError as ex:raise LiveBlocked(str(ex)) from ex
                    basis=used['tax_basis']
                    net=qty*price-fee-basis if basis is not None else None
                    perf_basis=used['performance_basis']
                    perf_net=qty*price-fee-perf_basis
                    basis_provenance=('MIXED_LOTS' if len(used['lots'])>1 else
                                     'ENROLLMENT_MARK' if b['snapshot_unit_usd'] is not None else b['basis_source'])
                    c.execute('UPDATE enrollment SET remaining_qty=? WHERE asset=?',(fmt(max(Decimal(0),old_qty-qty)),base))
                    if q:
                        c.execute('UPDATE enrollment SET remaining_qty=? WHERE asset=?',(fmt(D(q['remaining_qty'])+qty*price-fee),quote))
                    else:
                        c.execute('INSERT INTO enrollment(asset,authorized_qty,remaining_qty,basis_unit_quote,approved_at) VALUES(?,?,?,?,?)',(quote,'0',fmt(qty*price-fee),'1',now))
                c.execute('''INSERT INTO fills(trade_id,cid,order_id,pair,side,base_qty,price,fee_quote,
                    at_utc,cost_basis_quote,net_realized_quote,performance_basis_quote,
                    performance_realized_quote,basis_provenance)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (trade_id,cid,order_id,pair,side,fmt(qty),fmt(price),fmt(fee),now,
                     fmt(basis) if basis is not None else None,fmt(net) if net is not None else None,
                     fmt(perf_basis) if perf_basis is not None else None,
                     fmt(perf_net) if perf_net is not None else None,basis_provenance))

class LiveBroker:
    def __init__(self,ledger,client,*,per_order_max='5',daily_buy_cap='20',exposure_cap='30',max_orders_day=8):
        self.ledger=ledger;self.client=client
        self.per_order_max=dec(per_order_max);self.daily_buy_cap=dec(daily_buy_cap)
        self.exposure_cap=dec(exposure_cap);self.max_orders_day=int(max_orders_day)
        self.armed=False
        from coincat_daily_risk import DEFAULT_LIMIT
        self.daily_realized_loss_limit_usd=DEFAULT_LIMIT  # Manual, session-only, exact-decimal; protects new BUYs only.
        self.portfolio_ceiling_usd=None  # optional, explicit session authorization
        self.portfolio_ceiling_seen_at=0.0
    def permissions(self):
        perms=as_dict(self.client.get_api_key_permissions())
        if perms.get('can_trade') is not True:raise LiveBlocked('Key must explicitly report can_trade=True')
        if perms.get('can_transfer') is not False:raise LiveBlocked('Cannot verify transfers are DISABLED on this CDP key')
        if perms.get('can_view') is False:raise LiveBlocked('View permission required')
        return perms
    def balances(self,progress=None):
        rows=[];cursor=None;seen=set()
        for page in range(30):
            r=as_dict(self.client.get_accounts(limit=250,**({'cursor':cursor} if cursor else {})))
            if not isinstance(r.get('accounts'),list):raise LiveBlocked('Invalid Coinbase account snapshot')
            rows.extend(a for a in r['accounts'] if a.get('active') is not False and a.get('ready') is not False and not any(term in str(a.get('type','')).upper() for term in ('VAULT','STAKE','LOCK','EARN')))
            if progress:progress(page+1,len(rows))
            if not r.get('has_next'):
                balances=aggregate_balances(rows)
                return {k:v['available'] for k,v in balances.items() if v['available']>0}
            cursor=r.get('cursor')
            if not cursor or cursor in seen:break
            seen.add(cursor)
        raise LiveBlocked('Incomplete account pagination; cannot authorize or trade')
    def catalog(self,progress=None):
        # Advanced Trade lists spot products by offset. Do not confuse an absent
        # has_next with proof of a complete account-specific catalog.
        rows=[];seen=set();complete=False
        for page in range(20):
            resp=as_dict(self.client.get_products(limit=250,offset=250*page,
                         product_type='SPOT',get_tradability_status=True))
            products=resp.get('products')
            if not isinstance(products,list):raise LiveBlocked('Coinbase product list unavailable')
            if products:
                signature=(products[0].get('product_id'),products[-1].get('product_id'))
                if signature in seen:raise LiveBlocked('Coinbase catalog repeated page; pagination failed')
                seen.add(signature)
            rows.extend(products)
            if progress:progress(page+1,len(rows))
            if len(products)<250:
                complete=True;break
        if not complete:raise LiveBlocked('Coinbase product catalog pagination incomplete')
        # Read-only authenticated product rules for FUTURE multi-currency
        # planning. Catalog still returns the original list of IDs. Never
        # use cached rules as submission-time product validation.
        from coincat_v6010_registry import spot_registry
        ids,self.catalog_product_rules,self.catalog_registry_audit=spot_registry(rows)
        # Keep the original complete product snapshot only in memory; the
        # one-order registry is the sole active research/trading candidate set.
        self.catalog_registry_audit['complete_pages']=page+1
        self.catalog_registry_audit['status']='AUTHENTICATED_COMPLETE'
        return ids
    def enrol_from_balances(self,balances,valid_assets):
        self.permissions()
        current=self.balances()
        approved={k:min(dec(v),current.get(k,Decimal(0))) for k,v in balances.items() if k in valid_assets and dec(v)>0}
        if approved!={k:dec(v) for k,v in balances.items()}:
            raise LiveBlocked('Balance/eligibility changed since review. Refresh and reapprove.')
        self.ledger.approve_all(approved)
    def enrol_first_connection(self,balances,valid_assets):
        """Bootstrap only a truly empty ledger with fresh verified AVAILABLE balances.

        Called on first authenticated connection, not on trading arm. A user
        exclusion or pre-existing approved quantity is never changed on restart.
        """
        if self.ledger.assets():
            return {'created':False,'count':0}
        self.permissions()
        live=self.balances()
        expected={k:dec(v) for k,v in balances.items() if k in valid_assets and dec(v)>0}
        if not expected:return {'created':False,'count':0}
        if any(live.get(k,Decimal(0))<v for k,v in expected.items()):
            raise LiveBlocked('Available Coinbase balances changed during enrollment; refresh before trading')
        return self.ledger.initial_auto_enroll_if_empty(expected)

    def enrol_one_from_current(self,asset,requested_qty,valid_assets):
        """Refresh exchange-side available balance before honoring explicit single-row approval."""
        self.permissions()
        if asset not in valid_assets:raise LiveBlocked('Asset is not Coinbase spot eligible')
        live=self.balances()
        qty=dec(requested_qty)
        if qty<=0 or qty>live.get(asset,Decimal(0)):
            raise LiveBlocked('Balance changed or asset unavailable. Refresh and review.')
        self.ledger.approve_one(asset,qty)

    def snapshot_approved_inventory(self,assets,valid_pairs,*,authorization):
        """Read-only Coinbase market/account lookups followed by an explicitly
        authorized ledger snapshot. No trade submissions, and never arms trading.
        Any unquotable coin remains without an enrollment-performance basis.
        """
        if self.armed:
            raise LiveBlocked('Disarm live trading before changing performance marks')
        self.permissions()
        if self.ledger.pending():
            raise LiveBlocked('Unresolved exchange order; do not mark inventory')
        live=self.balances()  # available (not held or staked)
        requested=list(dict.fromkeys(str(x).upper() for x in assets))
        result={'marked':[],'skipped':[]}
        for asset in requested:
            row=self.ledger.asset(asset)
            if not row or asset in ('USD','USDC'):
                result['skipped'].append((asset,'not currently approved crypto'));continue
            if row.get('snapshot_unit_usd') is not None:
                result['skipped'].append((asset,'already snapshotted (frozen)'));continue
            if row.get('basis_source')=='BOT_FILL':
                result['skipped'].append((asset,'verified CoinCat fill basis preserved'));continue
            if dec(row['remaining_qty'])>live.get(asset,Decimal(0)):
                result['skipped'].append((asset,'less available on Coinbase than enrolled'));continue
            # USD-only market quotes here. USDC conversions would need a fresh
            # USDC/USD rate; never silently treat a USDC price as a dollar price.
            pair=asset+'-USD'
            if pair not in valid_pairs:
                result['skipped'].append((asset,'no authenticated USD spot market; USD conversion unavailable'));continue
            try:
                tick=as_dict(self.client.get_market_trades(product_id=pair,limit=1))
                bid=dec(tick.get('best_bid'));ask=dec(tick.get('best_ask'))
                if bid<=0 or ask<bid or (ask-bid)/ask>Decimal('0.05'):
                    raise LiveBlocked('invalid or excessively wide current bid/ask')
                marked=self.ledger.snapshot_market_basis(asset,bid,pair=pair,
                    available_qty=live[asset],authorization=authorization)
                result['marked'].append(marked)
            except Exception as ex:
                result['skipped'].append((asset,str(ex)[:150]))
        return result

    def arm(self):
        raise LiveBlocked('Unified all-spot POST disabled: production currency FIFO/recovery and bounded 12-order authorization not certified')
        self.permissions()
        if self.ledger.setting('halted','0')=='1':raise LiveBlocked('Emergency stop is latched; cannot arm')
        if self.ledger.pending():raise LiveBlocked('Pending order; reconcile before arming')
        if not self.ledger.assets():raise LiveBlocked('No balances have been enrolled and approved')
        if self.per_order_max<=0 or self.daily_buy_cap<=0 or self.exposure_cap<=0:
            raise LiveBlocked('Risk limits must be positive')
        # Recheck durable user-authorized capacity stage every time; source
        # edits to the GUI cannot silently bypass the exchange-risk ceiling.
        from coincat_capacity import validate_limits
        validate_limits(self.ledger,self.per_order_max,self.daily_buy_cap,self.exposure_cap,self.max_orders_day,
                        portfolio_cap=self.portfolio_ceiling_usd)
        if self.portfolio_ceiling_usd is not None and (not self.portfolio_ceiling_seen_at or
                time.monotonic()-self.portfolio_ceiling_seen_at>300):
            raise LiveBlocked('Verified portfolio budget estimate expired: refresh Coinbase books and recheck budgets')
        self.armed=True
    def disarm(self,emergency=False):
        self.armed=False
        if emergency:
            self.ledger.set_setting('halted','1');self.ledger.log('EMERGENCY_STOP','No automated Coinbase order cancellation; inspect Coinbase')
    def release_stop(self):
        if self.ledger.pending():raise LiveBlocked('Reconcile pending order before clearing stop')
        self.ledger.set_setting('halted','0')
    def risk_check(self,side,pair,usd_value,now=None):
        if not self.armed or self.ledger.setting('halted','0')=='1':raise LiveBlocked('Live trading has not been armed')
        from coincat_capacity import validate_limits
        validate_limits(self.ledger,self.per_order_max,self.daily_buy_cap,self.exposure_cap,self.max_orders_day,
                        portfolio_cap=self.portfolio_ceiling_usd)
        if self.portfolio_ceiling_usd is not None and (not self.portfolio_ceiling_seen_at or
                time.monotonic()-self.portfolio_ceiling_seen_at>300):
            raise LiveBlocked('Verified portfolio budget estimate expired: refresh Coinbase books and recheck budgets')
        self.permissions()
        if self.ledger.pending():raise LiveBlocked('Pending Coinbase order exists')
        if not SPOT_PAIR_RE.fullmatch(pair):raise LiveBlocked('Pair not recognized as an eligible spot identifier')
        value=dec(usd_value)
        if value<Decimal('1') or value>self.per_order_max:raise LiveBlocked('Outside authorized per-order pilot cap')
        stats=self.ledger.today_stats(now)
        # New purchases cease on drawdown, but risk-reducing sells remain possible.
        if side=='BUY' and stats['order_count']>=self.max_orders_day:
            raise LiveBlocked('Daily new-order budget reached')
        if side=='BUY':
            from coincat_daily_risk import loss_decision, LossEvidenceUnavailable
            try:
                evidence=loss_decision(self.ledger.path,self.daily_realized_loss_limit_usd,now)
            except (LossEvidenceUnavailable,ValueError) as ex:
                raise LiveBlocked(f'Daily realized USD loss evidence unavailable; new BUY blocked: {ex}') from ex
            if not evidence['new_buys_allowed']:
                raise LiveBlocked('Confirmed UTC daily USD realized-loss BUY pause reached authorized '+
                    f'${evidence["limit_usd"]:.2f}; SELL and read-only research remain available')
        if side=='BUY' and stats['day_spend']+value>self.daily_buy_cap:raise LiveBlocked('Daily purchase budget reached')
        recent=self.ledger.most_recent()
        if recent and (now or time.time())-int(recent['created_at'])<120:raise LiveBlocked('Wait at least 120s between real orders')
    def product(self,pair):
        data=as_dict(self.client.get_product(pair))
        if data.get('product_id',pair)!=pair or data.get('product_type','SPOT')!='SPOT' or any(data.get(f) for f in ('trading_disabled','is_disabled','cancel_only','limit_only','view_only')):
            raise LiveBlocked('Pair is not an executable spot market')
        if pair not in self.catalog():raise LiveBlocked('Pair not in current eligible authenticated catalog')
        return data
    def review_spot_candidate(self, *, pair, side, catalog, quotes, verified,
                              balance_age_s, usd_order_cap, now, fee_reserve_bps=None):
        """Accept ANY authenticated Coinbase spot product for *read-only* broker review.

        This is deliberately separate from submit() and the legacy financial
        ledger. It never talks to Coinbase or stages/sends an order. Until
        quote-specific USD fills/tax lots/risk are verified, non-dollar order
        submission still rejects before creating any order ID.
        """
        from coincat_unified_broker import plan_spot_intent
        rows=self.ledger.assets()
        auth={r['asset']:r['remaining_qty'] for r in rows if r.get('enabled',1)}
        exclusions={r['asset'] for r in rows if not r.get('enabled',1)}
        return plan_spot_intent(pair=pair,side=side,catalog=catalog,
            product_rules=getattr(self,'catalog_product_rules',{}),
            quotes=quotes,now=now,authorized=auth,verified=verified,
            balance_age_s=balance_age_s,usd_order_cap=usd_order_cap,
            fee_reserve_bps=fee_reserve_bps,excluded=exclusions)

    def preview_cross_spot_candidate(self, *, pair, side, catalog, quotes,
                                     balance_age_s, usd_order_cap, now):
        """READ-ONLY authenticated Coinbase order preview for crypto-quote candidates.

        Unlike a signal, a real preview supplies estimated costs. A preview is
        NOT an order, not a durable fill, and cannot authorize cross-quote live
        execution. Caller must pass current *authenticated* REST quotes plus USD
        conversion quotes. Public WebSocket last trade is never sufficient.
        """
        from coincat_broker_pair_review import inspect_pair
        from coincat_cross_quote import split_spot, usd_conversion, USD_QUOTES
        side=str(side).upper()
        res={'pair':str(pair),'side':side,'state':'BLOCKED',
             'reason':'No verified preview', 'live_eligible':False,
             'order_submitted':False}
        try:
            base,quote=split_spot(pair)
            if quote in USD_QUOTES:
                raise LiveBlocked('Read-only cross-quote preview helper only; standard spot review covers every listed quote')
            if self.armed:
                raise LiveBlocked('Cross-quote preview requires DISARMED mode')
            if self.ledger.pending() or self.ledger.setting('halted','0')=='1':
                raise LiveBlocked('Pending Coinbase order or emergency STOP; cannot preview')
            self.permissions()
            live=self.balances()
            p=self.product(pair)  # fresh authenticated product, never saved rules
            auth={r['asset']:r['remaining_qty'] for r in self.ledger.assets()
                  if r.get('enabled',1)}
            exclusions={r['asset'] for r in self.ledger.assets()
                        if not r.get('enabled',1)}
            candidate=inspect_pair(pair=pair,side=side,catalog=catalog,
                product_rules={pair:p},quotes=quotes,now=now,authorized=auth,
                verified=live,balance_age_s=balance_age_s,
                usd_order_cap=min(dec(usd_order_cap),self.per_order_max)*Decimal('.93'),
                excluded=exclusions)
            if not candidate['candidate']:
                raise LiveBlocked(candidate['reason'])
            fx=usd_conversion(quote,quotes,now=now,max_age=120,max_legs=3)
            if not fx or fx['rate']<=0:
                raise LiveBlocked('Missing verified USD FX mark for quoted currency')
            if side=='BUY':
                size=candidate['quote_notional_estimate']
                preview=as_dict(self.client.preview_market_order_buy(product_id=pair,quote_size=size))
            else:
                size=candidate['base_size_estimate']
                preview=as_dict(self.client.preview_market_order_sell(product_id=pair,base_size=size))
            if preview.get('success') is False or any(preview.get(k) for k in ('errs','errors','error_response')):
                raise LiveBlocked('Coinbase rejected authenticated cross-spot preview')
            raw_fee=preview.get('commission_total',preview.get('fee'))
            if raw_fee is None:
                raise LiveBlocked('Preview missing fee amount')
            fee=dec(raw_fee)
            ccy=preview.get('commission_currency') or preview.get('fee_currency')
            if not ccy:
                raise LiveBlocked('Preview lacks explicit fee currency; no assumptions about fee units')
            ccy=str(ccy).upper()
            if ccy in exclusions:
                raise LiveBlocked('Coinbase preview charges excluded fee asset')
            fee_fx=usd_conversion(ccy,quotes,now=now,max_age=120,max_legs=3)
            if not fee_fx or fee_fx['rate']<=0:
                raise LiveBlocked('Fee currency lacks fresh Coinbase USD valuation')
            usd_notional=dec(candidate['usd_estimated'])
            fee_usd=fee*fee_fx['rate']
            from coincat_v40_1_safety import rehearse_cross_preview
            funding_asset=quote if side=='BUY' else base
            authorized_wallet=min(dec(auth.get(funding_asset,'0')),
                                  dec(live.get(funding_asset,'0')))
            rehearsal=rehearse_cross_preview(
                side=side,quote_currency=quote,funding_asset=funding_asset,
                funding_available=authorized_wallet,estimated_gross_usd=usd_notional,
                fee_amount=fee,fee_currency=ccy,usd_per_fee=fee_fx['rate'],
                usd_limit=min(dec(usd_order_cap),self.per_order_max),
                quoted_funding_units=dec(candidate['quote_notional_estimate']),
                proposed_base_units=dec(candidate['base_size_estimate']))
            # Capture a preview-rate observation only when Coinbase itself
            # supplies an explicit quote notional in the fee's same currency.
            # Never derive a fee rate from estimated conversion marks.
            preview_rate=None
            if ccy==quote and preview.get('quote_size') is not None:
                try:
                    preview_quote=dec(preview['quote_size'])
                    if preview_quote>0:
                        preview_rate=fmt(fee/preview_quote)
                except (ValueError,TypeError,ZeroDivisionError):
                    pass
            res.update(state='PREVIEW_VALIDATED_RESEARCH',
                reason='Coinbase preview and USD stress rehearsal passed; live cross-quote settlement remains blocked',
                preview_fee_fraction=preview_rate,
                fee_currency=ccy,preview_fee_usd=fmt(fee_usd),
                estimated_notional_usd=fmt(usd_notional),
                stressed_commitment_usd=rehearsal['stressed_commitment_usd'],
                proposed_size=str(size),usd_fx_path=candidate['usd_fx_path'],
                live_eligible=False,order_submitted=False)
        except (LiveBlocked,KeyError,TypeError,ValueError,OverflowError) as exc:
            res['reason']=str(exc)[:200]
        return res

    def review_verified_cross_fills(self, *, order, fills, pair, side, books,
                                    books_source, max_usd_notional=None):
        """NO-ORDERS verified-fill accounting check for a future broker.

        Caller must supply Coinbase-verified terminal order and its exact
        fills along with time-matched authenticated quote books. Neither
        the production ledger nor broker wallet allocations are mutated.
        """
        from coincat_verified_cross_fills import verified_cross_order
        return verified_cross_order(order=order,fills=fills,pair=pair,side=side,
             books=books,source=books_source,max_usd_notional=max_usd_notional)

    def submit(self,side,pair,usd_value,expected_quote=None,*,profit_target_usd=None,protective_exit=False):
        raise LiveBlocked('Unified all-spot order submission not certified; no legacy-only pilot or live POST allowed')
        """Fresh recheck + Coinbase preview, durable stage before EXACTLY ONE POST.
        No retries on ambiguous POST response. Does not assume successful create = fill.
        """
        side=side.upper();pair=pair.upper()
        if side not in ('BUY','SELL'):raise LiveBlocked('Only BUY/SELL spot orders')
        # Ordinary fee/spread limits ONLY; retired manual ETH conversion has no order path.
        fee_limit=Decimal('.05');spread_limit=Decimal('.0025')
        self.risk_check(side,pair,usd_value)
        p=self.product(pair)
        base,quote=pair.split('-')
        live=self.balances()
        ticker=as_dict(self.client.get_market_trades(product_id=pair,limit=1))
        bid=dec(ticker.get('best_bid'));ask=dec(ticker.get('best_ask'))
        if not 0<bid<=ask:raise LiveBlocked('No valid fresh Coinbase bid/ask')
        price=ask if side=='BUY' else bid
        if expected_quote is not None:
            prev=D(expected_quote)
            if prev<=0 or abs(price/prev-1)>Decimal('0.003'):
                raise LiveBlocked('Market moved over 0.30% since forward signal; no chase')
        if (ask-bid)/ask>spread_limit:raise LiveBlocked('Bid/ask spread exceeds authorized tolerance')
        amount=dec(usd_value)
        if amount<dec(p.get('quote_min_size') or '0'):raise LiveBlocked('Below Coinbase quote minimum for '+pair)
        if p.get('quote_max_size') and amount>dec(p['quote_max_size']):raise LiveBlocked('Above Coinbase quote maximum for '+pair)
        inc=p.get('base_increment')
        base_size=floor_to(amount/price,inc)
        if base_size<dec(p.get('base_min_size') or '0') or base_size<=0:raise LiveBlocked('Below Coinbase base minimum for '+pair)
        if p.get('base_max_size') and base_size>dec(p['base_max_size']):raise LiveBlocked('Above Coinbase base maximum for '+pair)
        # Rounding SELL base size down may push its actual quote proceeds under
        # Coinbase's advertised pair minimum even when planned USD was enough.
        if side=='SELL' and base_size*bid<dec(p.get('quote_min_size') or '0'):
            raise LiveBlocked('Rounded SELL proceeds below Coinbase quote minimum for '+pair)
        managed=self.ledger.asset(quote if side=='BUY' else base)
        if not managed:raise LiveBlocked('Asset not in approved managed pool')
        if side=='BUY':
            existing_base=self.ledger.asset(base)
            if existing_base and dec(existing_base['remaining_qty'])>0:
                try:
                    with sql(self.ledger.path) as conn:
                        lots.verify(conn,base)
                except ValueError as ex:raise LiveBlocked(str(ex)) from ex
                # Unknown original basis remains unknown in its separate legacy lot.
                # New bot fills get their own true acquisition-cost lot.
            if min(D(managed['remaining_qty']),live.get(quote,Decimal(0)))<amount*Decimal('1.10'):
                raise LiveBlocked('Insufficient enrolled/current quote funds plus reserve')
            # cash-only portfolio risk: local invested notional at current midpoint for newly acquired coins.
            # Never assumes personal non-managed holdings are available.
            # Exposure cap applies to *additional automated acquisitions*.
            # Pre-existing individually approved holdings remain available to
            # sell after basis approval, but do not consume the new-buy budget.
            with sql(self.ledger.path) as conn:
                bought=conn.execute("SELECT base_qty,price FROM fills WHERE side='BUY'").fetchall()
                sold=conn.execute("SELECT base_qty,price FROM fills WHERE side='SELL'").fetchall()
            added_exposure=max(Decimal(0),sum((D(r['base_qty'])*D(r['price']) for r in bought),Decimal(0))-
                           sum((D(r['base_qty'])*D(r['price']) for r in sold),Decimal(0)))
            if added_exposure+amount>self.exposure_cap:
                raise LiveBlocked('Maximum new-buy exposure reached')
            preview=as_dict(self.client.preview_market_order_buy(product_id=pair,quote_size=fmt(amount)))
            request_size=fmt(amount)
        else:
            if managed.get('trading_basis_unit_quote') is None:
                raise LiveBlocked('No complete verified lot performance basis; cannot sell')
            if managed.get('snapshot_unit_usd') is not None and quote!='USD':
                raise LiveBlocked('USD performance snapshot requires a USD-denominated sell pair; no implicit USDC=USD conversion')
            if min(D(managed['remaining_qty']),live.get(base,Decimal(0)))<base_size:
                raise LiveBlocked('Sell exceeds approved/current available quantity')
            preview=as_dict(self.client.preview_market_order_sell(product_id=pair,base_size=fmt(base_size)))
            request_size=fmt(base_size)
        if preview.get('success') is False or preview.get('errs') or preview.get('errors') or preview.get('error_response'):
            raise LiveBlocked('Coinbase rejected order preview')
        fee_v=preview.get('commission_total',preview.get('fee'))
        if fee_v is None:raise LiveBlocked('Coinbase preview missing commission; blocked')
        fee=dec(fee_v)
        if fee>amount*fee_limit:raise LiveBlocked('Coinbase preview commission exceeds authorized fee tolerance')
        # For an ordinary targeted SELL, check Coinbase's latest preview fees plus
        # a slippage allowance against the per-order dollar target. Protective
        # exits must remain possible when the requested profit is unattainable.
        if side=='SELL' and profit_target_usd is not None and not protective_exit:
            expected_proceeds=base_size*bid*(1-Decimal('0.0015'))
            try:lot_cost=self.ledger.sale_basis(base,base_size,quote)['performance_basis']
            except ValueError as ex:raise LiveBlocked(str(ex)) from ex
            est_net=expected_proceeds-fee-lot_cost
            if est_net<dec(profit_target_usd):
                raise LiveBlocked(f'Expected net sell ${est_net:.3f} after Coinbase preview fee and 15bps reserve is below ${dec(profit_target_usd):.2f}; no profit-taking sell')
        # Explicit net-cost gate: exit would need at least target net after TWO costs.
        if side=='BUY':
            buy_rate=fee/amount
            min_exit=minimum_exit_price(ask,buy_rate,max(buy_rate,Decimal('0.006')),
                                         Decimal('0.0075'),expected_sell_slippage_bps=15)
            if min_exit/ask-1>Decimal('0.05'):
                raise LiveBlocked('Fee/spread means target would require >5% appreciation')
        # Refresh risk/STOP immediately before durable staging.
        self.risk_check(side,pair,amount)
        cid=self.ledger.stage(pair,side,request_size,fee,purpose='AUTOTRADE')
        # STOP may arrive after staging but before the network POST. In that case
        # preserve the record, do NOT transmit, and require review/reconciliation.
        if not self.armed or self.ledger.setting('halted','0')=='1':
            self.ledger.update_order(cid,state='REJECTED',detail='Local pre-POST stop: confirmed not sent')
            self.disarm()
            return {'cid':cid,'state':'REJECTED','message':'Disarmed BEFORE Coinbase submission. No POST attempted.'}
        # After POST, DO NOT allow automatic retries regardless of error, including timeout.
        try:
            if side=='BUY':
                response=as_dict(self.client.market_order_buy(client_order_id=cid,product_id=pair,quote_size=request_size))
            else:
                response=as_dict(self.client.market_order_sell(client_order_id=cid,product_id=pair,base_size=request_size))
        except Exception:
            self.ledger.update_order(cid,state='UNKNOWN',checked_at=int(time.time()),detail='Submit response uncertain; investigate on Coinbase')
            self.disarm()
            return {'cid':cid,'state':'UNKNOWN','message':'Coinbase response uncertain; NO retry. Inspect orders directly.'}
        oid=(response.get('success_response') or {}).get('order_id') or response.get('order_id')
        if not oid:
            self.ledger.update_order(cid,state='REJECTED' if response.get('success') is False else 'UNKNOWN',checked_at=int(time.time()))
            self.disarm()
            return {'cid':cid,'state':'UNKNOWN' if response.get('success') is not False else 'REJECTED','message':'No verified order ID; auto trading stopped'}
        self.ledger.update_order(cid,order_id=str(oid),state='ACKNOWLEDGED',checked_at=int(time.time()))
        return {'cid':cid,'state':'ACKNOWLEDGED','order_id':str(oid),'message':'Exchange accepted request; awaiting confirmed fills'}
    def recover_receipt(self,order):
        """READ-ONLY lookup for an ambiguous POST, matching exact client_order_id.
        Never infers that absence of an order means the POST was not executed.
        """
        cursor=None;seen=set();found=[]
        for _ in range(10):
            data=as_dict(self.client.list_orders(limit=100,product_ids=[order['pair']],
                                  **({'cursor':cursor} if cursor else {})))
            for row in data.get('orders',[]):
                if row.get('client_order_id')==order['cid'] and row.get('order_id'):
                    found.append(str(row['order_id']))
            if not data.get('has_next'):break
            cursor=data.get('cursor')
            if not cursor or cursor in seen:break
            seen.add(cursor)
        unique=set(found)
        if len(unique)!=1:return None
        oid=unique.pop()
        self.ledger.update_order(order['cid'],order_id=oid,state='ACKNOWLEDGED',detail='Recovered exact client_order_id read-only')
        return oid

    def reconcile(self):
        """Read order and exact fills; only count real settled fills; halt on uncertainty."""
        pending=self.ledger.pending()
        if not pending:return {'state':'CLEAR'}
        oid=pending.get('order_id');cid=pending['cid']
        if not oid:
            try:oid=self.recover_receipt(pending)
            except Exception:oid=None
            if not oid:
                self.disarm();raise LiveBlocked('Unknown submission without exchange order ID. Check Coinbase by client_order_id; NEVER resubmit.')
        try:
            data=as_dict(self.client.get_order(order_id=oid)).get('order') or {}
            # Reject a mismatched exchange response before inspecting any fills.
            if (data.get('order_id') and str(data['order_id']) != str(oid)) or \
               (data.get('product_id') and data['product_id'] != pending['pair']) or \
               (data.get('side') and str(data['side']).upper() != pending['side']):
                raise LiveBlocked('Coinbase order identity differs from pending local order')
            state=str(data.get('status','')).upper()
            filled=dec(data.get('filled_size') or '0')
            if state not in TERMINAL or state=='FILLED' and filled<=0:
                self.ledger.update_order(cid,state='PARTIALLY_FILLED' if filled else 'OPEN',checked_at=int(time.time()))
                return {'state':'WAITING','exchange_status':state,'filled':fmt(filled)}
            if state not in ('FILLED','COMPLETED'):
                if filled>0:
                    self.ledger.update_order(cid,state='RECONCILE_ERROR',detail='Partially filled terminal order; manual review')
                    self.disarm();raise LiveBlocked('Terminal order has partial fills. Manual reconciliation required.')
                self.ledger.update_order(cid,state=state,checked_at=int(time.time()))
                return {'state':state}
            fills=[];cursor=None;seen=set()
            for _ in range(20):
                result=as_dict(self.client.get_fills(order_ids=[oid],limit=100,**({'cursor':cursor} if cursor else {})))
                if not isinstance(result.get('fills'),list):raise LiveBlocked('Invalid Coinbase fill page')
                fills.extend(result['fills'])
                if not result.get('has_next'):break
                cursor=result.get('cursor')
                if not cursor or cursor in seen:raise LiveBlocked('Incomplete fill pagination')
                seen.add(cursor)
            else:raise LiveBlocked('Too many fill pages; manual reconciliation required')
            try:
                totals=summarize_fills(fills,order_id=oid,pair=pending['pair'],side=pending['side'])
                verify_order_totals(data,totals)
            except FillUnitError as exc:
                raise LiveBlocked('Order reconciliation still uncertain: '+str(exc)) from exc
            # The fill table stores BASE quantities even if Coinbase reports a
            # quote-denominated fill.size. Ledger normalizes each fill itself.
            self.ledger.apply_fills(cid,oid,pending['pair'],pending['side'],fills)
            self.ledger.update_order(cid,state='FILLED',checked_at=int(time.time()))
            return {'state':'FILLED','count':len(fills)}
        except LiveBlocked:
            self.disarm();raise
        except Exception:
            self.disarm();raise LiveBlocked('Order/fills lookup failed; auto trading stopped. Retry reconciliation, NEVER order submission.')
    def adaptive_size(self,pair,available_quote,*,target_net_pct=Decimal('0.75')):
        """Conservative fee-aware bounded online sizing. Profits never raise hard cap."""
        vals=self.ledger.pair_performance(pair)
        recent=vals[-30:]
        if len(recent)<5:
            fraction=Decimal('0.5')   # limited fill history => small pilot
        else:
            wins=sum(1 for v in recent if v>0)
            average=sum(recent,Decimal(0))/len(recent)
            rate=Decimal(wins)/len(recent)
            fraction=(Decimal('1') if len(recent)>=10 and rate>=Decimal('.75') and average>0
                      else Decimal('0.8') if rate>=Decimal('.60') and average>0
                      else Decimal('0.3') if average<0 else Decimal('0.5'))
        size=min(self.per_order_max*fraction,dec(available_quote)*Decimal('0.70'))
        return floor_to(size,Decimal('0.01'))
    def export(self,kind,path):
        rows={'orders':self.ledger.orders,'fills':self.ledger.fills,'snapshots':self.ledger.snapshot_history}[kind]()
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else (['no_records']))
            writer.writeheader()
            if rows:writer.writerows(rows)
        return len(rows)
