"""Cost-aware cross-sectional research ranking; strictly observational.

Ranks *already captured* authenticated bid/ask time-series descriptions.
Momentum in a quoted pair is not a USD alpha forecast; no BUY output is ever
produced and these rankings cannot bypass independent forward HOLD validation.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
from statistics import median


def rank_observed_markets(reviews, *, max_targets=3):
    raw=[]
    for r in reviews or ():
        try:
            pair=str(r['pair']).upper()
            target=pair.split('-')[0]
            bid=Decimal(str(r['bid']));ask=Decimal(str(r['ask']))
            trend=Decimal(str(r['trend']))
            if not all(v.is_finite() for v in (bid,ask,trend)):continue
            if bid<=0 or ask<bid or int(r.get('count',0))<8:continue
            spread=(ask-bid)/ask*10000
            if spread>25:continue
            # Informational spread penalty, no future prediction or profit.
            score=trend-spread/Decimal(100)
            raw.append((score,pair,trend,spread))
        except (TypeError,ValueError,KeyError,InvalidOperation,IndexError,ZeroDivisionError):continue
    if not raw:return {'candidates':[],'eligible_markets':0,'method':'observed quote relative strength; NOT predictive'}
    center=median([x[0] for x in raw])
    ranked=sorted(raw,key=lambda x:(x[2]<=0,-(x[0]-center),x[1]))
    unique=[];seen=set()
    for row in ranked:
        base=row[1].split('-')[0]
        if base in seen:continue
        seen.add(base);unique.append(row)
    return {'candidates':[{'pair':pair,'momentum_pct':momentum,'spread_bps':spread,
                           'research_score':score-center,'action':'EXPLORE_ONLY'}
                          for score,pair,momentum,spread in unique[:max(0,int(max_targets))]],
            'eligible_markets':len(raw),'unique_assets':len(unique),
            'rising_assets':sum(x[2]>0 for x in unique),
            'method':'rank positive REST quote momentum ahead of declines, after spread; descriptive, not prediction/BUY'}
