"""Bounded discovery -> deep-study scheduling. RESEARCH ONLY.

Scouting does not create approved positions, order authorizations, forward labels,
or execution-quality quotes. Cohorts stay fixed 45min for 12-min quote maturity
and later 30-min observations. A candidate's score is heuristic, NOT a forecast.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import json,time,math

FOCUS_DWELL=45*60
FOCUS_KEY='focus_cohort_v40_portfolio_neutral'
HISTORICAL_FOCUS_KEY='focus_cohort_v21_5_portfolio_neutral'  # Read historical DB rows only

def rank_scouts(store,eligible,exclude=(),now=None,max_spread_bps=25):
    now=int(time.time() if now is None else now)
    universe=set(eligible)-set(exclude)
    if not universe:return []
    with store._db() as db:
        records=db.execute('SELECT pair,at_utc,bid,ask,prior_at_utc,prior_mid,samples FROM catalog_discovery_latest WHERE at_utc>=?',(now-6*3600,)).fetchall()
    ranked=[]
    for pair,ts,bid,ask,pt,pm,samples in records:
        if pair not in universe or not pt or int(samples)<2 or ts-pt<60:continue
        try:
            bid,ask=Decimal(bid),Decimal(ask);old=Decimal(pm)
            if not (0<old and 0<bid<=ask):continue
            spread=float((ask-bid)/ask*10000)
            move=float(((bid+ask)/2/old-1)*100)
            if not all(map(math.isfinite,(spread,move))):continue
            if spread>max_spread_bps or abs(move)<.06 or abs(move)>15:continue
            age=max(0,now-int(ts))
            # Momentum/range are for RESEARCH PRIORITY only, never a BUY signal.
            score=abs(move)/(1+spread/10) * math.exp(-age/7200)
            # Rank rising destinations first. Negative price moves remain
            # visible for SELL/range research; this is not an order signal.
            if move > 0:score*=1.5
            ranked.append({'pair':pair,'score':round(score,6),'move_pct':round(move,4),
                           'spread_bps':round(spread,2),'age_secs':age,'samples':int(samples)})
        except (InvalidOperation,ValueError,TypeError,OverflowError,ZeroDivisionError):continue
    return sorted(ranked,key=lambda x:(x['move_pct']<=0,-x['score'],x['pair']))


def balanced_scout_priority(ranked,limit):
    """Prefer ascending market prices, reserve up to 25% for falling markets.

    Uses authenticated REST scout bids/asks only. No portfolio holdings,
    executable quote, artificial history, order authorization or new calls.
    """
    count=max(0,int(limit))
    rising=[x for x in ranked if x.get('move_pct',0)>0]
    falling=[x for x in ranked if x.get('move_pct',0)<=0]
    if not rising or not falling:
        return [x['pair'] for x in ranked[:count]]
    up_count=min(len(rising),count-max(1,count//4)) if count>1 else min(1,len(rising))
    down_count=min(len(falling),count-up_count)
    selected=rising[:up_count]+falling[:down_count]
    present={x['pair'] for x in selected}
    selected.extend(x for x in ranked if x['pair'] not in present)
    return [x['pair'] for x in selected[:count]]

class FocusPlanner:
    """Persist cohort selection in the same bounded market-research DB."""
    def __init__(self,store,hold_seconds=FOCUS_DWELL,promotions=12,urgent_per_cycle=4):
        self.store=store;self.hold_seconds=int(hold_seconds);self.promotions=int(promotions);self.urgent_per_cycle=max(0,min(8,int(urgent_per_cycle)))
    def select(self,priority,eligible,capacity=64,now=None):
        now=int(time.time() if now is None else now)
        eligible=list(dict.fromkeys(eligible));valid=set(eligible)
        priority=[p for p in dict.fromkeys(priority) if p in valid]
        limit=max(int(capacity),len(priority))
        slots=max(0,limit-len(priority))
        prior=set(priority)
        ranked=rank_scouts(self.store,eligible,prior,now)
        with self.store._db() as db:
            row=db.execute('SELECT value FROM live_store_state WHERE key=?',(FOCUS_KEY,)).fetchone()
            if row is None:
                row=db.execute('SELECT value FROM live_store_state WHERE key=?',(HISTORICAL_FOCUS_KEY,)).fetchone()
        try:cached=json.loads(row[0]) if row else {}
        except (ValueError,TypeError):cached={}
        effective=[p for p in cached.get('pairs',[]) if p in valid and p not in prior]
        renewed=(now-int(cached.get('updated',0))>=self.hold_seconds or not effective)
        if renewed:
            top=balanced_scout_priority(ranked,min(slots,self.promotions))
            # Stable diversified fallback. No unqualified discovery becomes a signal.
            rest=[p for p in eligible if p not in prior and p not in top]
            idx=(now//self.hold_seconds * max(1,slots-len(top)))%max(1,len(rest))
            fill=(rest[idx:]+rest[:idx])[:max(0,slots-len(top))]
            effective=top+fill
            with self.store._db() as db:
                db.execute('INSERT OR REPLACE INTO live_store_state(key,value) VALUES(?,?)',
                           (FOCUS_KEY,json.dumps({'updated':now,'pairs':effective,'promoted':top})))
        urgent_added=[]
        if not renewed and slots > 0:
            # An unusual cross-pair should not wait until the entire 45-min
            # cohort expires just to START a 12-min deep-study window. Only
            # REAL verified REST scout changes qualify. Existing promoted
            # markets stay pinned; replace unqualified fallback slots only.
            pinned=[p for p in cached.get('promoted',[]) if p in effective]
            room=min(self.urgent_per_cycle,max(0,self.promotions-len(pinned)))
            incoming=balanced_scout_priority(
                [x for x in ranked if x['pair'] not in effective and x['pair'] not in prior],room)
            if incoming:
                urgent_added=list(incoming)
                free=[p for p in effective if p not in pinned and p not in incoming]
                effective=(pinned+incoming+free)[:slots]
                pinned=pinned+[p for p in incoming if p in effective]
                cached['pairs']=effective
                cached['promoted']=pinned
                # Preserve original cohort epoch. An alert cannot silently
                # reset every existing market's maturity or unlock trading.
                with self.store._db() as db:
                    db.execute('INSERT OR REPLACE INTO live_store_state(key,value) VALUES(?,?)',
                               (FOCUS_KEY,json.dumps(cached)))
        candidates=[x for x in dict.fromkeys(effective) if x not in prior][:slots]
        if len(candidates)<slots:
            candidates += [p for p in eligible if p not in prior and p not in candidates][:slots-len(candidates)]
        promoted=[p for p in cached.get('promoted',[]) if p in candidates] if not renewed else [p for p in [x['pair'] for x in ranked[:self.promotions]] if p in candidates]
        return {'watch':priority+candidates,'promoted':promoted,'eligible_scouts':len(ranked),
                'cohort_age_s':0 if renewed else max(0,now-int(cached.get('updated',now))),
                'min_dwell_s':self.hold_seconds,'urgent_added':urgent_added,
                'ranking':ranked[:8],
                'rising_scouts':sum(x['move_pct']>0 for x in ranked),
                'falling_scouts':sum(x['move_pct']<=0 for x in ranked),
                'rising_promoted':sum(p in set(x['pair'] for x in ranked if x['move_pct']>0) for p in promoted),
                'research_note':'Rising REST-scout movers prioritized; negative movers retained for SELL/range research. Only fresh REST order books qualify routes; no trades authorized'}
