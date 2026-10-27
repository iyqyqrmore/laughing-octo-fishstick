"""Cross-currency USD HOLD-vs-SWITCH observations (research only).

All observations are market book valuations independent of account inventory.
No API access or order submission. Never infer a future return from one recent
momentum number; pair outcomes use strictly prior nonoverlapping intervals.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, time
from coincat_cross_quote import split_spot, usd_conversion

BUCKET_S=300
HORIZON_S=3600
KEEP_DAYS=10
MIN_WINDOWS=35
MIN_SPAN_S=7*86400

def _positive(value):
    try:
        x=Decimal(str(value))
        return x if x.is_finite() and x>0 else None
    except (ValueError,InvalidOperation,TypeError):
        return None

class RelativeUSDLab:
    """Small, reproducible public asset-USD research journal, not a tax ledger."""
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("""CREATE TABLE IF NOT EXISTS public_marks(
                bucket INTEGER NOT NULL, asset TEXT NOT NULL, usd_per_unit TEXT NOT NULL,
                fee_tier_source TEXT NOT NULL, PRIMARY KEY(bucket,asset))""")
            db.execute('CREATE INDEX IF NOT EXISTS mark_asset_time ON public_marks(asset,bucket)')
            db.commit()

    def observe(self,*,catalog,quotes,now,fee_verified=False,max_assets=4096):
        """Capture public USD marks for a market-derived research cohort.

        We do not use enrolled balances, asset quantities or holdings to pick
        markets; no personal wallet information is written to this journal.
        """
        now=int(now)
        bucket=(now//BUCKET_S)*BUCKET_S
        assets={'USD'}
        for pair in catalog or ():
            try:
                base,quote=split_spot(pair)
                assets.add(base);assets.add(quote)
            except (ValueError,TypeError):continue
        rows=[]
        # Authenticated spot universe, not current holdings or alphabetical top-160;
        # only assets with fresh independently priced USD conversion enter marks.
        for asset in sorted(assets)[:max_assets]:
            fx=usd_conversion(asset,quotes,now=now,max_age=120,max_legs=2)
            if fx and (rate:=_positive(fx.get('rate'))) is not None:
                rows.append((bucket,asset,format(rate,'f'),'VERIFIED_ACCOUNT_TIER' if fee_verified else 'FEE_UNVERIFIED'))
        if rows:
            with closing(sqlite3.connect(self.path,timeout=10)) as db:
                db.executemany('INSERT OR IGNORE INTO public_marks VALUES(?,?,?,?)',rows)
                db.execute('DELETE FROM public_marks WHERE bucket < ?',(now-KEEP_DAYS*86400,))
                db.commit()
        return len(rows)

    def maintenance(self, *, now=None):
        """Keep public USD marks bounded. Never operate on financial lots.

        Standard: keep 10 days of synchronized USD marks for week-spanning
        experiments. Under overall research-directory space pressure, first
        shrink to 8 days; if still above cap, to 7 days (minimum needed for
        seven-day forward-evidence maturity). If that is insufficient, storage
        status remains over-limit and any live authorization stays blocked.
        """
        from coincat_storage import RESEARCH_LIMIT_MIB, research_sqlite_bytes
        now=int(time.time() if now is None else now)
        limit=RESEARCH_LIMIT_MIB*1024*1024
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            count=db.execute('DELETE FROM public_marks WHERE bucket<?',
                             (now-KEEP_DAYS*86400,)).rowcount
            db.commit()
        used=research_sqlite_bytes(self.path.parent)
        if used >= limit:
            with closing(sqlite3.connect(self.path,timeout=10)) as db:
                count+=db.execute('DELETE FROM public_marks WHERE bucket<?',
                                  (now-8*86400,)).rowcount
                db.commit()
        used=research_sqlite_bytes(self.path.parent)
        if used >= limit:
            with closing(sqlite3.connect(self.path,timeout=10)) as db:
                count+=db.execute('DELETE FROM public_marks WHERE bucket<?',
                                  (now-7*86400,)).rowcount
                db.commit()
        # WAL checkpoint reclaims old pages without changing observed results;
        # VACUUM is intentionally deferred to quiet maintenance time, rather
        # than pause the minute-by-minute AI Lab scan.
        if count:
            with closing(sqlite3.connect(self.path,timeout=10)) as db:
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return {'pruned':count,'aggregate_mb':round(research_sqlite_bytes(self.path.parent)/1048576,3),
                'limit_mb':RESEARCH_LIMIT_MIB}

    def paired_outcomes(self,source,target,*,now,min_windows=MIN_WINDOWS,min_span_s=MIN_SPAN_S):
        """1h realized relative USD returns, using only nonoverlapping past windows.

        The result does not claim forecasts or net after-cost profits. The
        caller adds the actual route's estimated entry drag separately.
        """
        fallback={'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0,'span_days':0,
                  'mean_relative_return':None,'p10_relative_return':None,
                  'positive_windows':0,'hold_mean_return':None,'switch_mean_return':None}
        if source==target:return dict(fallback,state='SAME_ASSET')
        now=int(now)
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            db.row_factory=sqlite3.Row
            source_rows=db.execute('SELECT bucket,usd_per_unit FROM public_marks WHERE asset=? AND bucket<=? ORDER BY bucket',
                (source,now-HORIZON_S)).fetchall()
            target_rows=db.execute('SELECT bucket,usd_per_unit FROM public_marks WHERE asset=? AND bucket<=? ORDER BY bucket',
                (target,now-HORIZON_S)).fetchall()
            all_rows=db.execute('SELECT bucket,asset,usd_per_unit FROM public_marks WHERE asset IN (?,?) AND bucket<=? ORDER BY bucket',
                (source,target,now)).fetchall()
        # Require exact synchronized marks at both endpoints. A missing interval
        # is NOT approximated with adjacent stale prices or ticker last trades.
        paired={}
        for r in all_rows:
            paired.setdefault(int(r['bucket']),{})[r['asset']]=_positive(r['usd_per_unit'])
        points=[];end_last=-10**30
        for t in sorted(paired):
            if t<end_last or t+HORIZON_S>now:continue
            a=paired[t].get(source);b=paired[t].get(target)
            end=paired.get(t+HORIZON_S,{})
            aa=end.get(source);bb=end.get(target)
            if None in (a,b,aa,bb):continue
            hold=aa/a-Decimal(1);switch=bb/b-Decimal(1)
            if abs(hold)>Decimal('2') or abs(switch)>Decimal('2'):continue
            points.append((t,hold,switch,switch-hold))
            end_last=t+HORIZON_S+BUCKET_S
        n=len(points)
        span=(points[-1][0]-points[0][0]) if n>1 else 0
        if not n:return fallback
        with localcontext() as ctx:
            ctx.prec=50
            hold_mean=sum((p[1] for p in points),Decimal(0))/n
            switch_mean=sum((p[2] for p in points),Decimal(0))/n
            relative=sorted(p[3] for p in points)
            mean=sum(relative,Decimal(0))/n
            p10=relative[max(0,(n-1)//10)]
        ready=(n>=min_windows and span>=min_span_s)
        # Fixed chronological 75% training / 25% forward-test split with a
        # whole nonoverlapping observed window embargo across the boundary.
        # Forecast = training-only mean relative return, compared against the
        # naive HOLD baseline of 0 in UNSEEN later observed windows.
        split=int(n*Decimal('0.75'))
        train=points[:max(0,split-1)]
        test=points[split:] if split<n else []
        out={'oos_validated':False,'oos_state':'WAIT','oos_train_windows':len(train),
             'oos_test_windows':len(test),'oos_improvement':None,
             'oos_predicted_relative':None,'oos_actual_relative':None,
             'oos_p10_relative':None}
        if ready and len(train)>=24 and len(test)>=8:
            prediction=sum((x[3] for x in train),Decimal(0))/len(train)
            actual=sum((x[3] for x in test),Decimal(0))/len(test)
            ranked=sorted(x[3] for x in test)
            low=ranked[max(0,(len(ranked)-1)//10)]
            baseline=sum((x[3]**2 for x in test),Decimal(0))/len(test)
            model=sum(((x[3]-prediction)**2 for x in test),Decimal(0))/len(test)
            improvement=(baseline-model)/baseline if baseline>0 else Decimal('-1')
            passed=bool(prediction>0 and actual>0 and improvement>=Decimal('.05'))
            out.update(oos_validated=passed,
                oos_state='HELD_OUT_SIGNAL_PASS_RESEARCH_ONLY' if passed else 'HELD_OUT_BASELINE_NOT_BEAT',
                oos_improvement=improvement,oos_predicted_relative=prediction,
                oos_actual_relative=actual,oos_p10_relative=low)
        return {'state':'OBSERVED_WINDOWS_READY_NOT_PREDICTIVE' if ready else 'INSUFFICIENT_FORWARD_USD_EVIDENCE',
            'n':n,'span_days':Decimal(span)/Decimal(86400),
            'mean_relative_return':mean,'p10_relative_return':p10,
            'positive_windows':sum(p[3]>0 for p in points),
            'hold_mean_return':hold_mean,'switch_mean_return':switch_mean,**out}

    def public_stats(self,now=None):
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            total,assets,first,last=db.execute('SELECT count(*),count(DISTINCT asset),min(bucket),max(bucket) FROM public_marks').fetchone()
        return dict(rows=total,assets=assets or 0,first=first,last=last)

def evaluate_hold_switch(idea,evidence,minimum_net_advantage_usd='0.10'):
    """Compare a capped funded conversion against keeping the original units.

    Forward relative evidence compares source/target USD unit returns; the
    existing evaluated route's immediate after-cost mark is preserved. Only
    previously observed historical outcomes enter this research calculation.
    """
    try:
        minimum = Decimal(str(minimum_net_advantage_usd))
        if not minimum.is_finite() or not Decimal('0.01') <= minimum <= Decimal('10000'):
            raise ValueError('Invalid minimum net USD preference')
    except (InvalidOperation, TypeError, ValueError):
        minimum = None  # Invalid user preference must never create a passing idea.
    base={'research_decision':'HOLD_UNTIL_VERIFIED',
          'minimum_net_advantage_usd':minimum,
          'minimum_satisfied':False,
          'net_mean_usd':None,'net_p10_usd':None,
          'evidence_windows':int(evidence.get('n',0)),
          'evidence_span_days':evidence.get('span_days'),
          'evidence_state':evidence.get('state','UNAVAILABLE'),
          'oos_validated':evidence.get('oos_validated') is True,
          'oos_state':evidence.get('oos_state','WAIT'),
          'oos_train_windows':int(evidence.get('oos_train_windows',0)),
          'oos_test_windows':int(evidence.get('oos_test_windows',0)),
          'oos_improvement':evidence.get('oos_improvement')}
    if evidence.get('state')!='OBSERVED_WINDOWS_READY_NOT_PREDICTIVE':return base
    try:
        before=Decimal(str(idea['initial_wallet_usd_mark']))
        after=Decimal(str(idea['post_route_wallet_usd_mark']))
        input_qty=Decimal(str(idea['input_units_planned']))
        source_units=Decimal(str(idea['source_units']))
        mean=Decimal(str(evidence['mean_relative_return']))
        tail=Decimal(str(evidence['p10_relative_return']))
        if min(before,after,input_qty,source_units)<=0 or input_qty>source_units:return base
        allocated=before*(input_qty/source_units)
        net_mean=(after-before)+(allocated*mean)
        net_p10=(after-before)+(allocated*tail)
        # Threshold is for full source->target projected *portfolio* advantage,
        # not a quote-currency gain, immediate P&L, or a SELL-only exit.
        # Historical evidence below the threshold is still valid learning data.
        qualifies = bool(minimum is not None and net_mean >= minimum and net_p10 >= minimum)
        decision = ('SWITCH_WORTH_RESEARCH' if qualifies and evidence.get('oos_validated') is True
                    else 'HOLD_UNTIL_VERIFIED' if qualifies else 'HOLD_PREFERRED')
        return dict(base,research_decision=decision,net_mean_usd=net_mean,
                    net_p10_usd=net_p10,minimum_satisfied=qualifies)

    except (InvalidOperation,ValueError,TypeError,KeyError):return base
