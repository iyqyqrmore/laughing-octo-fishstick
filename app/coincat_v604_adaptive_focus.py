"""V60.4 research-only adaptive deep bid/ask capacity.

Rate-limit/latency health, not profitability, determines research bandwidth.
It has NO Coinbase client, trading broker, wallet, financial ledger or ARM paths.
"""
from __future__ import annotations
import math


class AdaptiveFocusCapacity:
    def __init__(self, initial=64, minimum=48, maximum=128, step=16):
        self.minimum=int(minimum)
        self.maximum=int(maximum)
        self.step=int(step)
        self.capacity=max(self.minimum,min(self.maximum,int(initial)))
        self.healthy_streak=0
        self.reason='Waiting for observed REST scan performance'
        self.increases=0
        self.decreases=0

    def observe(self, *, elapsed, scan_interval, quotes, failures, websocket_healthy,
                portfolio_healthy=True):
        """Called once after an ACTUAL completed scan (not ticker events)."""
        try:
            latency=float(elapsed);cadence=float(scan_interval)
            count=int(quotes);errors=int(failures)
        except (ValueError, TypeError, OverflowError):
            self.healthy_streak=0
            self.reason='Unavailable scan timing; holding current capacity'
            return self.capacity
        if not (math.isfinite(latency) and math.isfinite(cadence)) or cadence<=0 or latency<0 or count<0 or errors<0:
            self.healthy_streak=0
            self.reason='Invalid scan evidence; holding current capacity'
            return self.capacity
        rate=errors/max(1,count+errors)
        overloaded=(rate>=0.05 or latency>=cadence*0.75 or not portfolio_healthy)
        if overloaded:
            self.healthy_streak=0
            old=self.capacity
            self.capacity=max(self.minimum,self.capacity-self.step)
            self.decreases+=int(self.capacity<old)
            self.reason='Reduced deep study to protect REST latency, error rate or account refresh'
        elif (websocket_healthy and count>0 and rate<0.01
              and latency<=cadence*0.45 and portfolio_healthy):
            self.healthy_streak+=1
            if self.healthy_streak>=3:
                old=self.capacity
                self.capacity=min(self.maximum,self.capacity+self.step)
                self.increases+=int(self.capacity>old)
                self.healthy_streak=0
                self.reason='Expanded deep study after three verified healthy REST scans'
            else:
                self.reason='Healthy REST scan; checking sustained headroom'
        else:
            self.healthy_streak=0
            self.reason='Holding capacity until REST and public stream health support growth'
        return self.capacity

    def snapshot(self):
        return {'focus_capacity':self.capacity,'minimum':self.minimum,'maximum':self.maximum,
                'healthy_streak':self.healthy_streak,'increases':self.increases,
                'decreases':self.decreases,'reason':self.reason,
                'scope':'READ ONLY; never changes order limits or trading permissions'}
