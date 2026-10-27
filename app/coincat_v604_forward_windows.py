"""V60.4 observational 1/3/5/15/60-minute outcomes from canonical REST quotes.

No new quotes, ML database, or invented ticks. A counterfactual BUY ask ->
future SELL bid is a pair-level round trip versus unchanged CASH, *NOT*
portfolio USD-over-HOLD alpha. Incomplete future windows are discarded; never
backfill with historical OHLCV or public last-trade ticks. Pure read-only.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
from bisect import bisect_left
from statistics import mean

HORIZONS_SECONDS=(60,180,300,900,3600)
DEFAULT_TAKER=Decimal('.009')
DEFAULT_SLIPPAGE=Decimal('.0015')


def observed_windows(rows, *, horizon_s, taker_fee=DEFAULT_TAKER,
                     slippage=DEFAULT_SLIPPAGE, min_samples=2):
    """Use nonoverlapping realized future data with bounded endpoint tolerance.

    Data shape: (timestamp, bid, ask). A missing or stale future mark does NOT
    become a flat return. No proposed entry/exit order is ever constructed.
    """
    h=int(horizon_s)
    if h not in HORIZONS_SECONDS:raise ValueError('Unsupported research horizon')
    fee=Decimal(str(taker_fee));slip=Decimal(str(slippage))
    if any(not v.is_finite() or v<0 or v>=Decimal('.1') for v in (fee,slip)):
        raise ValueError('Bad research fee assumptions')
    data=[]
    for raw in rows:
        try:
            ts=int(raw[0]);bid=Decimal(str(raw[1]));ask=Decimal(str(raw[2]))
            if ts>0 and bid.is_finite() and ask.is_finite() and 0<bid<=ask:
                data.append((ts,bid,ask))
        except (TypeError,ValueError,OverflowError,InvalidOperation,IndexError):continue
    data=sorted(set(data),key=lambda x:x[0])
    if len(data)<min_samples:return {'horizon_s':h,'matured':0,'positive':0,
                                    'mean_net_pct':None,'net_returns':[],'missing_future':0}
    # Duplicate timestamps may come from malformed evidence; retain one quote
    # per second, without inserting fictitious additional observations.
    uniq=[]
    for row in data:
        if uniq and uniq[-1][0]==row[0]:continue
        uniq.append(row)
    ts=[x[0] for x in uniq]
    matured=[];missing=0;next_allowed=0
    tolerance=max(30,min(300,h//3))
    for at,bid,ask in uniq:
        if at<next_allowed or at+h>ts[-1]:continue
        next_allowed=at+h
        j=bisect_left(ts,at+h)
        if j>=len(ts) or ts[j]>at+h+tolerance:
            missing+=1
            continue
        exit_bid=uniq[j][1]
        # After a taker BUY and taker SELL plus both-leg slippage reserve.
        proceeds=(exit_bid/ask)*(1-fee-slip)**2
        matured.append(float((proceeds-1)*100))
    return {'horizon_s':h,'matured':len(matured),'positive':sum(x>0 for x in matured),
            'mean_net_pct':round(mean(matured),6) if matured else None,
            'net_returns':matured,'missing_future':missing,
            'caveat':'Pair-level after-cost counterfactual vs cash; NOT portfolio-vs-HOLD advantage'}


def research_summary(store, pairs, *, now=None, fee_rate=None, max_pairs=12,
                     lookback_s=7*3600, max_rows_per_pair=450):
    """Read-only bounded canonical quotes query, no new database or labels."""
    import time
    now=int(time.time() if now is None else now)
    fee=DEFAULT_TAKER if fee_rate is None else Decimal(str(fee_rate))
    names=list(dict.fromkeys(str(p) for p in pairs if isinstance(p,str) and '-' in p))[:max_pairs]
    result={'pair_count':0,'horizons':{},'storage':'canonical market_quotes only',
            'state':'DESCRIPTIVE_ONLY_NOT_PORTFOLIO_ALPHA','lookback_s':lookback_s}
    if not names:return result
    sums={h:{'matured':0,'positive':0,'values':[],'missing_future':0} for h in HORIZONS_SECONDS}
    with store._db() as db:
        for pair in names:
            rows=db.execute('''SELECT at_utc,bid,ask FROM market_quotes
                 WHERE pair=? AND at_utc>=? AND at_utc<=?
                 ORDER BY at_utc DESC LIMIT ?''',(pair,now-lookback_s,now,max_rows_per_pair)).fetchall()
            if len(rows)<2:continue
            result['pair_count']+=1
            for h in HORIZONS_SECONDS:
                item=observed_windows(rows,horizon_s=h,taker_fee=fee)
                acc=sums[h];acc['matured']+=item['matured'];acc['positive']+=item['positive']
                acc['missing_future']+=item['missing_future'];acc['values'].extend(item['net_returns'])
    for h,acc in sums.items():
        count=acc['matured']
        result['horizons'][h]={'matured':count,'positive':acc['positive'],
            'mean_net_pct':round(mean(acc['values']),5) if count else None,
            'missing_future':acc['missing_future']}
    return result
