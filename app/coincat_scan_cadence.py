"""Adaptive non-overlapping REST research cadence for CoinCat.

This is a throughput/health controller, NOT an optimizer of trading returns.
Coinbase REST API quotas are not a blanket authorization to trade faster.
Never alters arming, individual order limits, quotes used for order submission,
or independent pending fill reconciliation. Every sampled observation must be real.
"""
from __future__ import annotations
import math

STEPS=(15, 20, 30, 45, 60, 90, 120, 180)

class AdaptiveCadence:
    def __init__(self, initial=30, min_seconds=15, max_seconds=180, max_quote_rps=5.0):
        self.min_seconds=int(min_seconds)
        self.max_seconds=int(max_seconds)
        self.max_quote_rps=float(max_quote_rps)
        self.seconds=min(STEPS,key=lambda x:abs(x-initial))
        self.good_streak=0
        self.last_reason='Waiting for completed market scans'
        self.last_latency=0.0
        self.failures=0
        self.last_pair_count=0
        self.last_error_rate=0.0
        self.history=[]

    def update(self, *, elapsed, pairs, failures=0, ws_healthy=True, portfolio_healthy=True):
        """Called only for a COMPLETE live scan, never for ticker display.
        Reserve REST headroom: ceil(total quote requests / 5req/s), then
        increase delay on errors, slow scans, or other failing subsystems.
        """
        n=max(0,int(pairs));failed=max(0,int(failures));elapsed=max(0.,float(elapsed))
        rate=failed/max(1,n)
        self.last_latency=elapsed;self.failures=failed;self.last_pair_count=n;self.last_error_rate=rate
        floor=max(self.min_seconds, math.ceil(n/max(self.max_quote_rps,0.1)),
                  math.ceil(elapsed*1.5))
        viable=[s for s in STEPS if s>=floor and s<=self.max_seconds]
        hard=min(viable) if viable else self.max_seconds
        slow=(elapsed>self.seconds*.8 or rate>=.05 or not portfolio_healthy)
        bad=rate>=.02 or elapsed>self.seconds*.72 or not portfolio_healthy
        if bad:
            self.good_streak=0
            proposed=max(hard,self.seconds*1.5)
            self.seconds=next((s for s in STEPS if s>=proposed),self.max_seconds)
            self.last_reason='Backing off on scan latency, quote errors or portfolio verification'
        else:
            self.good_streak+=1
            if self.good_streak>=3 and ws_healthy:
                self.seconds=next((s for s in reversed(STEPS) if s<self.seconds and s>=hard),self.seconds)
                self.good_streak=0
                self.last_reason='Three healthy scans; safely stepping faster'
            else:self.last_reason='Stable scans; collecting speed and API-health evidence'
        self.seconds=max(hard,min(self.max_seconds,self.seconds))
        self.history.append((self.seconds,round(elapsed,2),n,failed))
        if len(self.history)>60:self.history=self.history[-60:]
        return self.seconds

    def snapshot(self):
        return {'seconds':self.seconds,'elapsed':round(self.last_latency,2),
                'pairs':self.last_pair_count,'failures':self.failures,
                'error_rate':round(self.last_error_rate*100,1),'reason':self.last_reason}
