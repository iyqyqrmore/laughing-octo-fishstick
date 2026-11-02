"""v50.2 fee observations: account-verified tier, pair preview, confirmed fills.

Read-only Coinbase SDK GET of transaction summary is optional and rate-limited.
Stored evidence is a compact non-financial RESEARCH database, never the live
broker, tax ledger, ARM authorization, or proof of pair-specific fee schedule.
There are no order POSTs, credentials persisted, or neural training shortcuts.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
import sqlite3
import time

TTL_SECONDS=2*3600
REFRESH_SECONDS=3600
RETRY_SECONDS=600
MAX_OBS=600

class FeeEvidenceError(ValueError):pass

def number(raw,*,negative=False):
    if isinstance(raw,(bool,float)) or raw is None:raise FeeEvidenceError('Exact decimal required')
    try:n=Decimal(str(raw))
    except (InvalidOperation,ValueError,TypeError):raise FeeEvidenceError('Invalid decimal evidence') from None
    if not n.is_finite() or (n<0 and not negative):raise FeeEvidenceError('Negative/nonfinite fee evidence')
    return n

def _rate(raw,*,maker=False):
    x=number(raw,negative=maker)
    if x < Decimal('-.1') or x>=Decimal('.2'):raise FeeEvidenceError('Fee rate outside acceptable percent-fraction range')
    return x

def fmt(x):return format(x,'f')

def _body(response):
    if isinstance(response,dict):return response
    if hasattr(response,'to_dict'):return response.to_dict()
    raise FeeEvidenceError('Unexpected SDK fee response')

class FeeLearning:
    def __init__(self,path,*,ttl=TTL_SECONDS):
        self.path=Path(path)
        self.ttl=int(ttl)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS account_fee_tier(
                rowid INTEGER PRIMARY KEY CHECK(rowid=1), captured_at INTEGER NOT NULL,
                maker_fraction TEXT NOT NULL, taker_fraction TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source='AUTHENTICATED_SPOT_TRANSACTION_SUMMARY'));
            CREATE TABLE IF NOT EXISTS fee_refresh_meta(
                rowid INTEGER PRIMARY KEY CHECK(rowid=1), last_attempt INTEGER NOT NULL,
                last_status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fee_pair_evidence(
                pair TEXT NOT NULL, side TEXT NOT NULL, kind TEXT NOT NULL,
                observed_at INTEGER NOT NULL, fee_fraction TEXT NOT NULL,
                fee_currency TEXT, verified_utc INTEGER,
                PRIMARY KEY(pair,side,kind));
            CREATE TABLE IF NOT EXISTS fee_fill_observations(
                fingerprint TEXT PRIMARY KEY, pair TEXT NOT NULL, maker_taker TEXT NOT NULL,
                fee_currency TEXT NOT NULL, fee_qty TEXT NOT NULL, notional_quote TEXT NOT NULL,
                observed_at INTEGER NOT NULL, source TEXT NOT NULL);
            ''')
            db.commit()

    def _db(self):
        return sqlite3.connect(self.path,timeout=3)

    def latest_tier(self,*,now=None):
        now=int(time.time() if now is None else now)
        with closing(self._db()) as db:
            row=db.execute('SELECT captured_at,maker_fraction,taker_fraction FROM account_fee_tier WHERE rowid=1').fetchone()
        if not row:return {'state':'NO_ACCOUNT_FEE_EVIDENCE','fresh':False,'maker':None,'taker':None}
        ts,maker,taker=row
        age=now-int(ts)
        return {'state':'ACCOUNT_TIER_VERIFIED' if 0<=age<=self.ttl else 'STALE_ACCOUNT_FEE_TIER',
                'fresh':0<=age<=self.ttl,'age_s':age,'captured_at':int(ts),
                'maker':Decimal(maker),'taker':Decimal(taker),
                'source':'AUTHENTICATED_SPOT_TRANSACTION_SUMMARY'}

    def due(self,*,now=None):
        now=int(time.time() if now is None else now)
        with closing(self._db()) as db:
            row=db.execute('SELECT last_attempt,last_status FROM fee_refresh_meta WHERE rowid=1').fetchone()
        if row and now-int(row[0])<(REFRESH_SECONDS if row[1]=='VERIFIED' else RETRY_SECONDS):return False
        return True

    def capture_tier(self, response,*,now=None):
        ts=int(time.time() if now is None else now)
        data=_body(response)
        tier=data.get('fee_tier')
        if not isinstance(tier,dict):raise FeeEvidenceError('Missing recognized Coinbase spot fee_tier')
        maker=_rate(tier.get('maker_fee_rate'),maker=True)
        taker=_rate(tier.get('taker_fee_rate'))
        with closing(self._db()) as db:
            db.execute('INSERT OR REPLACE INTO account_fee_tier VALUES(1,?,?,?,?)',
                       (ts,fmt(maker),fmt(taker),'AUTHENTICATED_SPOT_TRANSACTION_SUMMARY'))
            db.execute('INSERT OR REPLACE INTO fee_refresh_meta VALUES(1,?,?)',(ts,'VERIFIED'))
            db.commit()
        return {'status':'VERIFIED','maker':fmt(maker),'taker':fmt(taker)}

    def refresh_from_client(self,client,*,now=None):
        """Exactly one authenticated GET when due. Never invoke on the GUI thread."""
        now=int(time.time() if now is None else now)
        if not self.due(now=now):return {'status':'NOT_DUE'}
        try:
            if not hasattr(client,'get_transaction_summary'):
                raise FeeEvidenceError('SDK fee summary method unavailable')
            response=client.get_transaction_summary(product_type='SPOT')
            return self.capture_tier(response,now=now)
        except Exception:
            # Don't copy exception messages: they can include response headers / IDs.
            with closing(self._db()) as db:
                db.execute('INSERT OR REPLACE INTO fee_refresh_meta VALUES(1,?,?)',(now,'UNAVAILABLE'))
                db.commit()
            return {'status':'UNAVAILABLE','reason':'READ_ONLY_FEE_TIER_GET_FAILED'}

    def account_cost(self,pair,*,now=None):
        """Non-pair-verified fee screening for any spot market. NOT a live fee quote."""
        snapshot=self.latest_tier(now=now)
        if not snapshot['fresh']:
            return {'source':'NO_VERIFIED_ACCOUNT_FEE','pair_verified':False,'fresh':False,
                    'maker':None,'taker':None,'pair':pair}
        return dict(source='ACCOUNT_TIER_ONLY_PAIR_PREVIEW_REQUIRED',pair_verified=False,
                    fresh=True,pair=pair,maker=snapshot['maker'],taker=snapshot['taker'])

    def capture_pair_preview(self,*,pair,side,rate,observed_at=None):
        """Call only with independently verified authenticated order PREVIEW evidence.

        Product-specific rate can supplement account tier. It NEVER approves an order.
        No actual SDK preview is initiated here (caller owns minimum/quote checks).
        """
        from coincat_cross_quote import split_spot
        split_spot(pair)
        if side not in ('BUY','SELL'):raise FeeEvidenceError('Invalid side')
        fee=_rate(rate)
        ts=int(time.time() if observed_at is None else observed_at)
        with closing(self._db()) as db:
            db.execute('INSERT OR REPLACE INTO fee_pair_evidence VALUES(?,?,?,?,?,?,?)',
                       (pair,side,'AUTHENTICATED_PREVIEW',ts,fmt(fee),None,ts))
            db.commit()

    def pair_preview(self,pair,side,*,now=None,max_age=300):
        now=int(time.time() if now is None else now)
        with closing(self._db()) as db:
            row=db.execute('SELECT fee_fraction,observed_at FROM fee_pair_evidence '
                           'WHERE pair=? AND side=? AND kind=?',
                           (pair,side,'AUTHENTICATED_PREVIEW')).fetchone()
        if not row or now-int(row[1])>max_age:
            return {'verified':False,'source':'NO_FRESH_PAIR_PREVIEW'}
        return {'verified':True,'source':'AUTHENTICATED_PREVIEW','fee_fraction':Decimal(row[0]),'age_s':max(0,now-int(row[1]))}

    def record_confirmed_fill(self,*,fingerprint,pair,maker_taker,fee_currency,fee_qty,
                              notional_quote,observed_at=None,exchange_evidence_verified=False):
        """Record research-only cost evidence after independent live reconciliation.

        Not called automatically from receipts. Caller must explicitly affirm that
        the order/fill, fee asset, timestamp and all pagination have been verified.
        """
        from coincat_cross_quote import split_spot
        split_spot(pair)
        if exchange_evidence_verified is not True:raise FeeEvidenceError('Confirmed Coinbase evidence required')
        if not isinstance(fingerprint,str) or len(fingerprint)<16 or len(fingerprint)>128:
            raise FeeEvidenceError('Invalid fill fingerprint')
        if maker_taker not in ('MAKER','TAKER'):raise FeeEvidenceError('Unproven liquidity classification')
        if not isinstance(fee_currency,str) or not fee_currency.isalnum() or len(fee_currency)>15:
            raise FeeEvidenceError('Unverified fee currency')
        fee=number(fee_qty,negative=True) # genuine rebates possible
        quote=number(notional_quote)
        if quote<=0:raise FeeEvidenceError('Invalid fill notional')
        ts=int(time.time() if observed_at is None else observed_at)
        with closing(self._db()) as db:
            original=db.execute('SELECT pair,maker_taker,fee_currency,fee_qty,notional_quote '
                                'FROM fee_fill_observations WHERE fingerprint=?',(fingerprint,)).fetchone()
            values=(pair,maker_taker,fee_currency,fmt(fee),fmt(quote))
            if original:
                if original!=values:raise FeeEvidenceError('Conflicting fill evidence')
                return 'REPLAY_NOOP'
            db.execute('INSERT INTO fee_fill_observations VALUES(?,?,?,?,?,?,?,?)',
                       (fingerprint,*values,ts,'COINBASE_CONFIRMED_FILL'))
            db.execute('DELETE FROM fee_fill_observations WHERE fingerprint IN ('
                       'SELECT fingerprint FROM fee_fill_observations ORDER BY observed_at DESC LIMIT -1 OFFSET ?)',(MAX_OBS,))
            db.commit()
        return 'RECORDED'

    def research_screen(self,pair,observed_momentum_pct,spread_bps,*,legs=1,now=None):
        """Necessary (not sufficient) cost screen shared by AI and Auto Trader.

        Momentum is NOT a validated future USD return. A passing screen only
        means the observed movement was bigger than a taker-cost estimate.
        One-order conversion is the default for active v60.11.1 research.
        Callers examining a genuine entry plus later exit must explicitly use
        legs=2; this prescreen is NEVER an added charge to route receipts.
        """
        f=self.account_cost(pair,now=now)
        if not f['fresh']:
            return {'state':'FEE_UNVERIFIED','source':f['source'],'trade_authorized':False}
        with localcontext() as ctx:
            ctx.prec=80
            spread=number(spread_bps)
            observed=number(observed_momentum_pct,negative=True)
            if not 1<=legs<=4:raise FeeEvidenceError('Invalid legs')
            # Current signal momentum is mid-price based: include one observed
            # spread plus fee+15bps/slippage per leg as a conservative screening
            # hurdle. Do not ALSO add spread to an actual bid/ask fill calculation.
            hurdle=f['taker']*Decimal('100')*legs+Decimal('.15')*legs+spread/Decimal('100')
            meets=observed>hurdle
            return {'state':'UNVALIDATED_MOMENTUM_ABOVE_COST' if meets else 'MOMENTUM_BELOW_COST',
                    'source':f['source'],'hurdle_pct':hurdle,'observed_pct':observed,
                    'spread_bps':spread,'cost_screen_legs':legs,
                    'fee_hurdle_is_advisory_only':True,
                    'trade_authorized':False,'pair_verified':False}

    def report(self,catalog=(),*,now=None):
        now=int(time.time() if now is None else now)
        snapshot=self.latest_tier(now=now)
        pairs=sorted(set(catalog or ()))
        valid=[]
        from coincat_cross_quote import split_spot
        for pair in pairs:
            try:split_spot(pair)
            except (ValueError,TypeError):continue
            valid.append(pair)
        with closing(self._db()) as db:
            observed=db.execute('SELECT COUNT(*) FROM fee_fill_observations').fetchone()[0]
            preview=db.execute('SELECT COUNT(*) FROM fee_pair_evidence WHERE kind=? AND observed_at>=?',
                               ('AUTHENTICATED_PREVIEW',now-300)).fetchone()[0]
            last=db.execute('SELECT last_status FROM fee_refresh_meta WHERE rowid=1').fetchone()
        lines=['CoinCat v50.5 — VERIFIED FEE EVIDENCE / AI LAB + AUTO TRADER',
               'LOCAL REDACTED RESEARCH CACHE. NO SDK/API REQUESTS FROM DIAGNOSTICS. NO ORDERS.',
               'Fee refresh: at most one authenticated SPOT fee-tier GET/hour (retry after 10 min on failure).',
               'Fee cache source: '+snapshot['state'],
               'Last fee refresh: '+(last[0] if last else 'NONE'),
               'Current authenticated spot pair catalog: '+str(len(valid)),
               'Current fresh pair-specific preview observations: '+str(preview),
               'Previously verified filled-fee observations: '+str(observed),
               'Pair-specific fee exceptions: UNKNOWN unless independently previewed.',
               'Account tier alone is not proof of the fee for any particular spot pair.',
               'The 15bps per-leg research slippage reserve remains a stress input, never verified fill slippage.']
        if snapshot['fresh']:
            lines+=['Authenticated maker tier (percent): '+fmt(snapshot['maker']*100),
                    'Authenticated taker tier (percent): '+fmt(snapshot['taker']*100),
                    'Two-leg taker fees alone (percent): '+fmt(snapshot['taker']*200)]
        else:
            lines.append('[NOT VERIFIED] Authenticated fee tier missing or stale: research routes WAIT; no fixed 1% fallback.')
        lines.extend(['AI Lab forward labels require point-in-time authenticated tier evidence; past unverified labels excluded from fee-aware model.',
                      'Auto Trader receives the SAME AI Lab fee-screened cross-pair routes; no new execution permission.',
                      '[BLOCKED] For actual orders, verify product preview, real fees per fill, independent USD FX and FIFO.',
                      '[BLOCKED] Neural profitability training must use out-of-sample net-USD outcomes vs HOLD, not fee estimates.',
                      'END VERIFIED FEE EVIDENCE AUDIT'])
        return '\n'.join(lines)+'\n'
