"""Marked shadow advantage and rolling comparisons; losses and gaps retained."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math

@native_math
def append_point(state,performance):
    rows=state['performance_history'];at=performance['at']
    if rows and at<=rows[-1]['at']:return
    if not rows or at-rows[-1]['at']>=300:
        rows.append({k:deepcopy(performance[k]) for k in ('at','portfolio_usd','hold_usd','advantage_usd')})
        # 168 hours at five-minute spacing plus start/ending points.
        while len(rows)>2100:rows.pop(0) # GUI cache only; private transaction evidence retains every mark.

@native_math
def rolling(rows,current):
    result={}
    for hours in (1,6,24):
        value=dict(state='INSUFFICIENT_HISTORY',advantage_change_usd=None,relative_return_percent=None)
        if current:
            target=current['at']-hours*3600;prior=[r for r in rows if r['at']<=target]
            if prior and target-prior[-1]['at']<=300:
                old=prior[-1];inside=[r for r in rows if old['at']<=r['at']<=current['at']]
                stamps=[r['at'] for r in inside]+[current['at']]
                if all(b-a<=600 for a,b in zip(stamps,stamps[1:])) and old['portfolio_usd']>0 and old['hold_usd']>0:
                    value=dict(state='MARKED_WITH_OBSERVED_COVERAGE',advantage_change_usd=current['advantage_usd']-old['advantage_usd'],
                        relative_return_percent=(current['portfolio_usd']/old['portfolio_usd']-current['hold_usd']/old['hold_usd'])*100)
                else:value['state']='OBSERVATION_GAP'
        result[str(hours)+'h']=value
    return result
