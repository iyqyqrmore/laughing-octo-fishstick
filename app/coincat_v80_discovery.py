"""Bounded fair direct-pair discovery. No movement/history prerequisite."""
from decimal import Decimal
from coincat_v703_chain import approved_pairs
from coincat_v701_quotes import mark_paths
from coincat_cross_quote import usd_conversion,split_spot


def select_books(catalog,rules,funding,*,quotes,now,cursor=0,limit=16,max_routes=3,valuation_catalog=None):
    listed=approved_pairs(catalog,rules)
    valuation=set(approved_pairs(valuation_catalog if valuation_catalog is not None else catalog,rules))
    valuation_quotes={p:q for p,q in quotes.items() if p in valuation}
    sources=set(funding)
    routes=[]
    for pair in listed:
        base,quote=split_spot(pair)
        if quote in sources:routes.append((pair,'BUY',quote,base))
        if base in sources:routes.append((pair,'SELL',base,quote))
    count=len(routes);budget=max(0,min(16,int(limit)));chosen=[];selected=[];deferred=0
    missing=0;examined=0
    offset=int(cursor)%count if count else 0
    for i in range(count):
        pair,side,source,target=routes[(offset+i)%count];examined+=1
        if len(selected)>=max_routes:break
        forbidden=() if 'USD' in (source,target) else (pair,)
        dependency=[pair];valid=True
        for asset in (source,target):
            if asset=='USD':continue
            fx=usd_conversion(asset,valuation_quotes,now=now,max_age=12,max_legs=2,excluded_pairs=(pair,))
            path=fx['path'] if fx else mark_paths(asset,valuation-{pair},max_legs=2)
            if path is None and not forbidden:
                path=mark_paths(asset,valuation,max_legs=2)
            if path is None:valid=False;break
            dependency.extend(path)
        if not valid:missing+=1;continue
        extra=[p for p in dict.fromkeys(dependency) if p not in chosen]
        if len(chosen)+len(extra)>budget:deferred+=1;continue
        chosen.extend(extra);selected.append((pair,side,source,target))
    targets=list(dict.fromkeys((target,pair) for pair,side,source,target in selected))
    target_routes={}
    for pair,side,source,target in selected:target_routes.setdefault(target,[]).append(pair)
    return {'eligible_directions':routes,'books':chosen,'targets':targets,'target_routes':target_routes,'directions':selected,
        'candidate_routes':count,'funding_routes_deferred':max(0,count-len(selected)),
        'selected_directions':len(selected),'examined':examined,'missing_independent_paths':missing,
        'request_budget_deferred':deferred,'next_cursor':(offset+max(1,examined-1))%count if count else 0,
        'next_route_cursor':int(cursor)+max(1,examined-1),'next_target_cursor':0,
        'mark_refresh_deferred':False,'unlisted_mark_assets':[],
        'candidates':[{'pair':pair,'target_asset':target,'momentum_pct':Decimal(0),
                       'spread_bps':Decimal(0),'action':'EXPLORE_ONLY',
                       'strategy':'DIRECT_IMMEDIATE_DISCREPANCY'}
                      for pair,side,source,target in selected]}
