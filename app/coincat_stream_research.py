"""Subsecond event-driven trade-ticker telemetry ONLY; no orders or signals.

Network events supply last-trade prices, NOT executable bid/ask. Aggregates
are in-memory and bounded, with no raw streaming-event database growth.
"""
from collections import defaultdict,deque
from decimal import Decimal,InvalidOperation
from threading import Lock
import time,math

class StreamResearch:
    def __init__(self,max_pairs=3500,events_per_pair=64,max_age_s=20*60):
        self.max_pairs=max_pairs;self.events_per_pair=events_per_pair;self.max_age_s=max_age_s
        self._lock=Lock();self._ticks={};self.events=0
    def observe(self,pair,price,at=None):
        try:p=Decimal(str(price));now=time.time() if at is None else float(at)
        except (InvalidOperation,ValueError,TypeError):return False
        if not (p.is_finite() and p>0 and math.isfinite(now) and isinstance(pair,str) and '-' in pair):return False
        with self._lock:
            if pair not in self._ticks and len(self._ticks)>=self.max_pairs:
                oldest=min(self._ticks,key=lambda key:self._ticks[key][-1][0])
                del self._ticks[oldest]
            q=self._ticks.setdefault(pair,deque(maxlen=self.events_per_pair))
            if q and now<q[-1][0]:return False
            q.append((now,float(p)))
            while q and now-q[0][0]>self.max_age_s:q.popleft()
            self.events+=1
        return True
    def snapshot(self,now=None):
        now=time.time() if now is None else float(now)
        with self._lock:items=[(p,list(q)) for p,q in self._ticks.items()];total=self.events
        summary=[]
        for pair,points in items:
            active=[(ts,val) for ts,val in points if 0<=now-ts<=self.max_age_s]
            if not active:continue
            current=active[-1][1]
            def change(sec):
                prior=[v for ts,v in active if ts<=now-sec]
                return round(100*(current/prior[-1]-1),4) if prior and prior[-1] else None
            summary.append({'pair':pair,'last_trade':current,'age_ms':round((now-active[-1][0])*1000),
                'ticks_60s':len(active),'change_5s_pct':change(5),'change_30s_pct':change(30)})
        return {'events':total,'pairs':len(summary),'telemetry_only':True,'rows':summary}

    def rank_for_rest_scout(self,eligible,exclude=(),now=None,limit=6):
        """Prioritize ALL-catalog tick activity for REST verification only.

        Activity/movement are not a BUY/SELL signal, bid/ask, spread,
        liquidity guarantee, predictive model or authorization.
        Require three distinct events over >=20s and a recent event.
        Alerts persist up to 180 seconds so REST can verify multiple samples.
        The ordinary rotating catalog scout remains active for silent pairs.
        """
        now=time.time() if now is None else float(now)
        valid=set(eligible)-set(exclude)
        with self._lock:
            points=[(pair,list(q)) for pair,q in self._ticks.items() if pair in valid]
        ranked=[]
        for pair,raw in points:
            active=[(ts,val) for ts,val in raw if 0<=now-ts<=15*60]
            if len(active)<3 or now-active[-1][0]>180 or active[-1][0]-active[0][0]<20:
                continue
            if not active[0][1]:continue
            move=100*(active[-1][1]/active[0][1]-1)
            if not math.isfinite(move) or not 0.12<=abs(move)<=30:continue
            # Largest observed changes and broader trade participation come
            # first, but execution viability is unknown until REST validation.
            score=abs(move)*min(3,math.sqrt(len(active))/2)
            ranked.append((score,pair,move))
        rising=sorted((x for x in ranked if x[2]>0),key=lambda r:(-r[0],r[1]))
        falling=sorted((x for x in ranked if x[2]<0),key=lambda r:(-r[0],r[1]))
        n=max(0,int(limit))
        if rising and falling and n>1:
            up=min(len(rising),n-max(1,n//4))
            neg=min(len(falling),n-up)
            picked=rising[:up]+falling[:neg]
            chosen={x[1] for x in picked}
            picked.extend(x for x in rising[up:]+falling[neg:] if x[1] not in chosen)
        else:
            picked=rising+falling
        return [pair for _,pair,_ in picked[:n]]
