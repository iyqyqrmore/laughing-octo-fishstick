"""Bounded event-to-REST research queue. NO signals, orders or broker permissions.

All candidates originate in authenticated spot catalog + public WebSocket alerts.
REST bid/ask verification and existing full-portfolio planner remain authoritative.
Price observations used here are NEVER a Coinbase executable-order preview.
"""
from decimal import Decimal, InvalidOperation

MAX_FAST_BOOKS=16
MAX_TARGETS=3


def select_fast_books(alerts, catalog, funding_assets, *, limit=MAX_FAST_BOOKS):
    """Pick active market alerts, directly fundable one-order paths and USD marks.

    Do not manufacture any pairs; select only Coinbase catalog products. Max 16
    REST GETs per attempt; a no-route alert cannot consume unlimited capacity.
    """
    available=set(catalog or ())
    funding={str(a).upper() for a in (funding_assets or ()) if str(a)}
    targets=[]; seen=set()
    for pair in alerts or ():
        if pair not in available or '-' not in pair:continue
        asset=pair.split('-')[0]
        if not asset or asset in seen:continue
        if not any(f'{asset}-{source}' in available or f'{source}-{asset}' in available
                   for source in funding):continue
        targets.append((asset,pair));seen.add(asset)
        if len(targets)>=MAX_TARGETS:break
    routes=[]
    for asset,_ in targets:
        for fund in sorted(funding):
            for p in (f'{asset}-{fund}',f'{fund}-{asset}'):
                if p in available and p not in routes:routes.append(p)
    # Crucial: direct source/destination USD marks, then stablecoin anchors.
    marks=[]
    for coin in [a for a,_ in targets]+['USDC','USDT']+list(sorted(funding))+['BTC','ETH']:
        if coin=='USD':continue
        for p in (f'{coin}-USD',f'{coin}-USDC',f'{coin}-USDT'):
            if p in available and p not in marks:marks.append(p)
    chosen=[]
    for pair in [p for _,p in targets]+routes[:7]+marks:
        if pair not in chosen:chosen.append(pair)
        if len(chosen)>=min(MAX_FAST_BOOKS,max(0,int(limit))):break
    return {'targets':targets,'books':chosen,'candidate_routes':len(routes),
            'funding_assets':len(funding),'max_books':MAX_FAST_BOOKS}


def fast_candidates(targets, quotes, stream_snapshot, *, now, max_age=25):
    """Explicitly unvalidated short-horizon research ideas, no BUY qualification."""
    snapshot={r.get('pair'):r for r in (stream_snapshot or {}).get('rows',())}
    out=[]; rejected=0
    for asset,pair in targets or ():
        book=(quotes or {}).get(pair)
        try:
            bid,ask,ts=book[:3];bid=Decimal(str(bid));ask=Decimal(str(ask))
            if not 0<=float(now)-float(ts)<=max_age or bid<=0 or ask<bid:raise ValueError()
            spread=(ask-bid)/ask*Decimal(10000)
            if spread>25:raise ValueError()
            row=snapshot.get(pair) or {}
            trend=row.get('change_30s_pct')
            momentum=Decimal(str(trend)) if trend is not None else Decimal(0)
            if not momentum.is_finite():raise ValueError()
            out.append({'pair':pair,'momentum_pct':momentum,'spread_bps':spread,
                        'action':'EXPLORE_ONLY','strategy':'FAST_STREAM_REST_RESEARCH',
                        'time_window':'30s if available','validated':False})
        except (ValueError,TypeError,InvalidOperation,IndexError,KeyError):rejected+=1
    return out,rejected


def fast_funnel(*,detected=0,selected=0,fetched=0,errors=0,targets=0,
                 planner=None,snowball=None,simulated_delta=0):
    p=planner or {};s=snowball or {}
    return {'stream_alerts':int(detected),'fundable_alerts':int(selected),
            'book_requests':int(fetched)+int(errors),'fresh_books':int(fetched),
            'quote_errors':int(errors),'fresh_targets':int(targets),
            'one_order_routes':int(p.get('viable_routes') or 0),
            'route_blockers':dict(p.get('route_blockers') or {}),
            'immediate_priced':int(s.get('priced') or 0),
            'positive_estimates':int(s.get('positive') or 0),
            'above_target':int(s.get('above_floor') or 0),
            'modeled_fills_this_event':int(simulated_delta),
            'no_live_orders':True}
