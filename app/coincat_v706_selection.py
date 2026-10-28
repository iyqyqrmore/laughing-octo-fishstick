"""Experimental cost-aware selection from passive, causal market observations.

One canonical public quote store; no wallet quantities, keys, broker, orders or
financial-ledger access. These empirical scenarios do not certify a forecast.
"""
from contextlib import contextmanager
from decimal import Decimal,InvalidOperation
import math,sqlite3,time

from coincat_multicurrency import RotationContext
from coincat_cross_quote import split_spot

MODEL='forward-cost-v1'
HORIZON_S=300
GRACE_S=120
MIN_WINDOWS=8
LOOKBACK_S=6*3600
KEEP_S=3*86400
MAX_MARK_AGE=30
MAX_SKEW=12
MAX_FEATURE_AGE=30
MAX_EVIDENCE_AGE=30


def decimal(raw):
    try:
        if isinstance(raw,bool):return None
        value=Decimal(str(raw))
        return value if value.is_finite() else None
    except (TypeError,ValueError,InvalidOperation):return None


def feature_bucket(pct):
    value=decimal(pct)
    if value is None:return None
    if value<Decimal('-2'):return 'DOWN_STRONG'
    if value<Decimal('-.5'):return 'DOWN'
    if value<Decimal('.5'):return 'FLAT'
    if value<Decimal('2'):return 'UP'
    return 'UP_STRONG'


def features(snapshot,now):
    out={}
    for row in (snapshot or {}).get('rows',()):
        pct=decimal(row.get('change_30s_pct'))
        age=decimal(row.get('age_ms'))
        if pct is None or pct<=-100 or age is None or not 0<=age<=MAX_FEATURE_AGE*1000:continue
        pair=row.get('pair')
        try:split_spot(pair)
        except (TypeError,ValueError):continue
        inverse=(1/(1+pct/100)-1)*100
        out[pair]={'BUY':feature_bucket(pct),'SELL':feature_bucket(inverse),
                   'observed_at':float(now)-float(age)/1000}
    return out


def receipt_values(idea):
    steps=idea.get('shadow_fifo_steps') or ()
    if idea.get('sends_live_orders') is not False or len(steps)!=1 or idea.get('source')=='MULTI':return None
    step=steps[0]
    inp=decimal(step.get('approx_usd_notional'))
    out=decimal(step.get('output_usd_mark'))
    fee=decimal(step.get('fee_rate_used'))
    if inp is None or out is None or min(inp,out)<=0 or fee is None or not 0<=fee<Decimal('.05'):return None
    try:
        base,quote=split_spot(step['pair']);side=step['side']
        src,dst=(quote,base) if side=='BUY' else (base,quote) if side=='SELL' else ('','')
    except (KeyError,TypeError,ValueError):return None
    if (src,dst)!=(idea.get('source'),idea.get('target')):return None
    return step['pair'],side,inp,out


def assess(idea,*,now):
    result={'state':'HOLD_NO_FORWARD_EDGE','score_usd':None,'basis':None,'evidence_key':None,
            'reason':'NO_MATCHED_FORWARD_EVIDENCE'}
    values=receipt_values(idea)
    if values is None:return dict(result,reason='INVALID_COSTED_RECEIPT')
    pair,side,inp,out=values
    # Require improvement in the actual wallet mark as well as the comparable
    # hypothetical liquidation estimate. Never buy a merely cheaper exit model.
    instant=decimal(idea.get('snowball_immediate_usd'))
    if idea.get('snowball_state')=='IMMEDIATE_ESTIMATE' and instant is not None and min(instant,out-inp)>0:
        return dict(result,state='ELIGIBLE',score_usd=min(instant,out-inp),
                    basis='IMMEDIATE_AFTER_COST',reason='POSITIVE_SYNCHRONIZED_RECEIPT')
    evidence=idea.get('forward_edge_evidence') or {}
    if evidence.get('model')!=MODEL or evidence.get('state')!='READY_EXPERIMENTAL':
        return dict(result,reason=str(evidence.get('state') or 'NO_MATCHED_FORWARD_EVIDENCE'))
    try:
        asof=float(evidence['asof']);last=float(evidence['last_label_at'])
        first=float(evidence['first_opened_at']);observed=int(evidence['observed_windows'])
        missing=int(evidence['missing_windows']);feature_at=float(evidence['feature_at'])
        mean=decimal(evidence['mean_relative_growth']);low=decimal(evidence['p25_relative_growth'])
        if (not all(math.isfinite(t) for t in (now,asof,last,first,feature_at)) or
                evidence['context'] not in ('DOWN_STRONG','DOWN','FLAT','UP','UP_STRONG') or
                (evidence['pair'],evidence['side'])!=(pair,side) or
                not 0<=now-asof<=MAX_EVIDENCE_AGE or not 0<=asof-feature_at<=MAX_FEATURE_AGE or
                not 0<=now-feature_at<=MAX_FEATURE_AGE or
                not 0<=asof-last<=2*HORIZON_S+GRACE_S or not 0<=now-last<=2*HORIZON_S+GRACE_S or
                last-first<MIN_WINDOWS*HORIZON_S or
                evidence['horizon_s']!=HORIZON_S or observed<MIN_WINDOWS or missing<0 or
                evidence.get('nonoverlap_verified') is not True or
                Decimal(observed)/max(1,observed+missing)<Decimal('.8') or
                mean is None or low is None or min(mean,low)<=-1):
            return dict(result,reason='INVALID_STALE_OR_MISMATCHED_FORWARD_EVIDENCE')
    except (KeyError,ValueError,TypeError,OverflowError,InvalidOperation):
        return dict(result,reason='INVALID_STALE_OR_MISMATCHED_FORWARD_EVIDENCE')
    # The current receipt ALREADY contains fee, spread, assumed slippage and
    # rounding. Historical observations contain gross relative growth only.
    net_mean=out*(1+mean)-inp;net_low=out*(1+low)-inp
    if min(net_mean,net_low)<=0:return dict(result,reason='CURRENT_COSTS_EXCEED_FORWARD_EDGE')
    return dict(result,state='ELIGIBLE',score_usd=min(net_mean,net_low),basis='FORWARD_COST_SCENARIO',
        evidence_key=(pair,side,str(evidence['context']),last,
            str(decimal(idea['shadow_fifo_steps'][0]['fee_rate_used']).normalize())),
        reason='POSITIVE_EMPIRICAL_COST_SCENARIO')


class ForwardCostLearner:
    """Public, unit-normalized research in the existing market SQLite file."""
    def __init__(self,path):
        self.path=path;self.last_summary={};self.last_prune=0
        with sqlite3.connect(str(path),timeout=10) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'market_quotes' not in tables or {'enrollment','fills','inventory_lots'}&tables:
                raise ValueError('Selection research requires the canonical public market database')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS v706_forward_cost(
                pair TEXT NOT NULL,opened_at REAL NOT NULL,due_at REAL NOT NULL,
                closed_at REAL,buy_context TEXT NOT NULL,sell_context TEXT NOT NULL,
                entry_ratio TEXT NOT NULL,growth_buy TEXT,state TEXT NOT NULL,
                PRIMARY KEY(pair,opened_at));
            CREATE INDEX IF NOT EXISTS v706_due ON v706_forward_cost(state,due_at);
            CREATE INDEX IF NOT EXISTS v706_pair_time ON v706_forward_cost(pair,opened_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS v706_one_pending ON v706_forward_cost(pair) WHERE state='PENDING';
            ''')

    @contextmanager
    def _db(self):
        start=time.monotonic()
        db=sqlite3.connect(str(self.path),timeout=.05)
        db.row_factory=sqlite3.Row
        db.set_progress_handler(lambda:int(time.monotonic()-start>.15),1000)
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def _frame(pair,context):
        book=context.books.get(pair)
        if book is None:return None
        base,quote=split_spot(pair)
        a=context.usd(base);b=context.usd(quote)
        if a is None or b is None:return None
        stamps=[book[2]]+[context.books[p][2] for p in a['path']+b['path']]
        if max(stamps)-min(stamps)>MAX_SKEW:return None
        return a['rate']/b['rate']

    def observe(self,*,catalog,quotes,snapshot,now,observed_pairs=()):
        now=float(now);listed=set(catalog)
        context=RotationContext(catalog,quotes,now,quote_age_s=MAX_MARK_AGE)
        feature=features(snapshot,now);frames={}
        def frame(pair):
            if pair not in frames:frames[pair]=self._frame(pair,context)
            return frames[pair]
        stats={'state':'OBSERVING','recorded':0,'matured':0,'missed':0,'pending':0}
        try:
            with self._db() as db:
                due=db.execute("SELECT * FROM v706_forward_cost WHERE state='PENDING' AND due_at<=? ORDER BY due_at LIMIT 32",(now,)).fetchall()
                for row in due:
                    if now>row['due_at']+GRACE_S:
                        db.execute("UPDATE v706_forward_cost SET state='MISSED',closed_at=? WHERE pair=? AND opened_at=?",(now,row['pair'],row['opened_at']))
                        stats['missed']+=1;continue
                    ratio=frame(row['pair']) if row['pair'] in listed else None
                    if ratio is None:continue
                    entry=decimal(row['entry_ratio'])
                    if entry is None or entry<=0:
                        db.execute("UPDATE v706_forward_cost SET state='MISSED',closed_at=? WHERE pair=? AND opened_at=?",(now,row['pair'],row['opened_at']))
                        stats['missed']+=1;continue
                    growth=ratio/entry-1
                    db.execute("UPDATE v706_forward_cost SET state='OBSERVED',closed_at=?,growth_buy=? WHERE pair=? AND opened_at=?",
                               (now,str(growth),row['pair'],row['opened_at']))
                    stats['matured']+=1
                # Inspect the bounded fetched batch, rather than letting its
                # already-pending prefix starve later products of observations.
                for pair in list(dict.fromkeys(observed_pairs))[:128]:
                    if stats['recorded']>=32:break
                    if pair not in listed or pair not in feature:continue
                    old=db.execute('SELECT opened_at,closed_at,state FROM v706_forward_cost WHERE pair=? ORDER BY opened_at DESC LIMIT 1',(pair,)).fetchone()
                    if old and (old['state']=='PENDING' or now<old['opened_at']+HORIZON_S or (old['closed_at'] or 0)>now):continue
                    ratio=frame(pair)
                    if ratio is None:continue
                    db.execute("INSERT OR IGNORE INTO v706_forward_cost VALUES(?,?,?,NULL,?,?,?,NULL,'PENDING')",
                               (pair,now,now+HORIZON_S,feature[pair]['BUY'],feature[pair]['SELL'],str(ratio)))
                    stats['recorded']+=1
                if now-self.last_prune>=3600:
                    db.execute('DELETE FROM v706_forward_cost WHERE opened_at<?',(now-KEEP_S,))
                stats['pending']=db.execute("SELECT COUNT(*) FROM v706_forward_cost WHERE state='PENDING'").fetchone()[0]
            if now-self.last_prune>=3600:self.last_prune=now
        except sqlite3.Error:
            stats={'state':'DEFERRED_MODEL_BUSY','recorded':0,'matured':0,'missed':0,'pending':None}
        self.last_summary=stats
        return dict(stats)

    def forecasts(self,*,pairs,snapshot,now):
        """Bounded prior-data lookup, once per actual pair, never per size."""
        feature=features(snapshot,now);result={}
        try:
            with self._db() as db:
                for pair in sorted(set(pairs)):
                    if pair not in feature:continue
                    rows=db.execute('''SELECT * FROM v706_forward_cost
                        WHERE pair=? AND opened_at>=? AND
                        (closed_at<=? OR (state='PENDING' AND due_at+?<?))
                        ORDER BY opened_at DESC LIMIT 96''',
                        (pair,float(now)-LOOKBACK_S,float(now),GRACE_S,float(now))).fetchall()
                    for side,field in (('BUY','buy_context'),('SELL','sell_context')):
                        bucket=feature[pair][side]
                        matched=[r for r in rows if r[field]==bucket]
                        points=[];missing=0
                        last_closed=-1
                        for row in sorted(matched,key=lambda r:r['opened_at']):
                            if row['state'] in ('MISSED','PENDING'):missing+=1;continue
                            if row['state']!='OBSERVED':continue
                            growth=decimal(row['growth_buy'])
                            if (growth is None or growth<=-1 or row['due_at']!=row['opened_at']+HORIZON_S or
                                    row['closed_at']<row['due_at'] or
                                    row['closed_at']>row['due_at']+GRACE_S or row['opened_at']<last_closed):
                                missing+=1;continue
                            if side=='SELL':growth=1/(1+growth)-1
                            points.append((row['opened_at'],row['closed_at'],growth))
                            last_closed=row['closed_at']
                        evidence={'model':MODEL,'pair':pair,'side':side,'context':bucket,'asof':float(now),
                            'feature_at':feature[pair]['observed_at'],'horizon_s':HORIZON_S,
                            'nonoverlap_verified':True,
                            'observed_windows':len(points),'missing_windows':missing,'state':'WAIT_FORWARD_OBSERVATIONS'}
                        if len(points)>=MIN_WINDOWS:
                            values=sorted(p[2] for p in points)
                            evidence.update(state='READY_EXPERIMENTAL',
                                first_opened_at=min(p[0] for p in points),last_label_at=max(p[1] for p in points),
                                mean_relative_growth=str(sum(values,Decimal(0))/len(values)),
                                p25_relative_growth=str(values[(len(values)-1)//4]))
                        result[pair,side]=evidence
        except sqlite3.Error:return {}
        return result

    def summary(self):
        try:
            with self._db() as db:
                counts=dict(db.execute('SELECT state,COUNT(*) FROM v706_forward_cost GROUP BY state').fetchall())
            return {'model':MODEL,'horizon_s':HORIZON_S,'minimum_windows':MIN_WINDOWS,
                    'observations':counts,'last_update':dict(self.last_summary),'execution_certified':False}
        except sqlite3.Error:return {'model':MODEL,'state':'DEFERRED_MODEL_BUSY','execution_certified':False}
