"""Bounded event-to-REST research queue. NO signals, orders or broker permissions.

All candidates originate in authenticated spot catalog + public WebSocket alerts.
REST bid/ask verification and existing full-portfolio planner remain authoritative.
Price observations used here are NEVER a Coinbase executable-order preview.
"""
from decimal import Decimal, InvalidOperation

MAX_FAST_BOOKS=16
MAX_TARGETS=3


def fundable_alerts(alerts,catalog,funding,snapshot,*,limit=12):
    """Discovery may use another quote; the actual conversion must be direct."""
    if limit<=0:return []
    listed=set(catalog);funding=set(funding);out=[]
    rows={r.get('pair'):r for r in (snapshot or {}).get('rows',())}
    for pair in alerts:
        if pair not in listed:continue
        base,quote=pair.split('-')
        try:falling=Decimal(str(rows.get(pair,{}).get('change_30s_pct') or 0))<0
        except (InvalidOperation,ValueError,TypeError):falling=False
        target=quote if falling else base
        if any(source!=target and (f'{target}-{source}' in listed or f'{source}-{target}' in listed)
               for source in funding):
            if pair not in out:out.append(pair)
        if len(out)>=limit:break
    return out


def select_fast_books(alerts, catalog, funding_assets, *, limit=MAX_FAST_BOOKS,
                      required_assets=(), quotes=None, now=None,target_assets=None,valuation_catalog=None,
                      route_cursor=0,target_cursor=0):
    """Price a complete funded route, then refresh remaining wallet marks fairly.

    Cached <=12s marks need not consume a request. A small budget refreshes marks
    in stages; it never invents coverage or an unlisted bridge. No research gate.
    """
    import time
    from coincat_v701_quotes import mark_paths, mark_coverage, newest_books, valid_book
    from coincat_portfolio_prices import DISPLAY_MAX_SPREAD
    now = time.time() if now is None else now
    budget = min(MAX_FAST_BOOKS, max(0, int(limit)))
    available = set(catalog or ())
    cursor=max(0,int(route_cursor))
    fresh_routes=set(newest_books(quotes or {},now=now,max_age=12,max_spread=Decimal('.0025')))
    funding = {str(a).upper() for a in funding_assets or () if a}
    required = funding | set(required_assets or ())
    chosen, missing_paths, targets = [], [], []
    target_routes={}
    def priority(pair):
        raw=valid_book((quotes or {}).get(pair),now,12)
        return 1 if raw is not None and pair not in fresh_routes else 0
    alerts=sorted(dict.fromkeys(alerts or ()),key=priority)
    # Keep the leading alerts responsive and give the remaining candidate pool
    # a rotating slot, so three persistent wide products cannot own every pass.
    if len(alerts)>2:
        rest=alerts[2:];offset=max(0,int(target_cursor))%len(rest)
        alerts=alerts[:2]+rest[offset:]+rest[:offset]

    def dependencies(assets, *, valuation=False):
        needed = []
        for asset in sorted(set(assets)-{'USD'}):
            spread=DISPLAY_MAX_SPREAD if valuation else Decimal('.0025')
            legs=3 if valuation else 2
            if mark_coverage([asset], quotes or {}, now=now, max_age=12,
                             max_spread=spread,max_legs=legs)['complete']:
                continue
            # Disabled trading assets already held still need honest wallet
            # marks. Their valuation books never enter candidate routing.
            path = mark_paths(asset,set(valuation_catalog) if valuation and valuation_catalog is not None
                              else available,max_legs=legs)
            if path is None:
                if asset not in missing_paths: missing_paths.append(asset)
                continue
            for pair in path:
                if pair not in chosen and pair not in needed: needed.append(pair)
        return needed

    routes = []
    for pair in alerts or ():
        if len(targets) >= MAX_TARGETS: break
        if pair not in available or '-' not in pair: continue
        asset = (target_assets or {}).get(pair,pair.split('-')[0])
        if asset not in pair.split('-'):continue
        if asset in [a for a, _ in targets]: continue
        direct = [p for fund in sorted(funding) for p in
                  (f'{asset}-{fund}', f'{fund}-{asset}') if p in available]
        if not direct: continue
        offset=cursor%len(direct)
        direct=direct[offset:]+direct[:offset]
        # Prefer one complete conversion over seven routes with incomplete marks.
        def source_for(route):
            return next(a for a in route.split('-') if a!=asset)
        # Known-price funding first; all alternatives still enter the rotation.
        route = next((p for p in direct if source_for(p)=='USD'),
                     next((p for p in direct if p in fresh_routes),direct[0]))
        extra = list(dict.fromkeys(([] if route in fresh_routes else [route])+
                                  dependencies({asset,source_for(route)})))
        extra = [p for p in extra if p not in chosen]
        if len(chosen)+len(extra) > budget: continue
        chosen.extend(extra)
        targets.append((asset, pair))
        target_routes[asset]=list(direct)
        routes.extend(p for p in direct if p not in routes)
    # Missing/unrelated holdings must not consume every slot before a funded
    # target. Refresh their marks next, oldest first, without fabricating prices.
    baseline=dependencies(required,valuation=True)
    cached=newest_books(quotes or {},now=now,max_age=180)
    baseline.sort(key=lambda p:(cached.get(p,(None,None,float('-inf')))[2],p))
    remaining=max(0,budget-len(chosen))
    chosen.extend(baseline[:remaining])
    deferred=len(baseline)>remaining
    # Remaining capacity can verify alternative funding routes, never displace
    # a required HOLD/current mark or a complete selected target.
    for route in routes:
        if len(chosen)>=budget: break
        if route not in chosen and route not in fresh_routes: chosen.append(route)
    return {'targets': targets, 'books': chosen, 'candidate_routes': len(routes),
            'funding_assets': len(funding), 'max_books': MAX_FAST_BOOKS,
            'required_assets': sorted(required | {a for a, _ in targets}),
            'unlisted_mark_assets': missing_paths, 'mark_refresh_deferred': deferred,
            'funding_routes_deferred':sum(p not in chosen and p not in fresh_routes for p in routes),
            'next_route_cursor':cursor+max(1,sum(p in routes for p in chosen)),
            'target_routes':target_routes,'next_target_cursor':max(0,int(target_cursor))+1}


def fast_candidates(targets, quotes, stream_snapshot, *, now, max_age=25,target_routes=None):
    """Explicitly unvalidated short-horizon research ideas, no BUY qualification."""
    snapshot={r.get('pair'):r for r in (stream_snapshot or {}).get('rows',())}
    out=[]; rejected=0
    for asset,pair in targets or ():
        try:
            from coincat_v701_quotes import valid_book
            routes=[pair] if target_routes is None else target_routes.get(asset,())
            verified=[(p,b) for p in routes if (b:=valid_book((quotes or {}).get(p),now,max_age,Decimal('.0025'))) is not None]
            if not verified:raise ValueError()
            verified_pair,(bid,ask,ts)=min(verified,key=lambda v:(v[1][1]-v[1][0])/v[1][1])
            spread=(ask-bid)/ask*Decimal(10000)
            row=snapshot.get(pair) or {}
            trend=row.get('change_30s_pct')
            momentum=Decimal(str(trend)) if trend is not None else Decimal(0)
            if not momentum.is_finite():raise ValueError()
            out.append({'pair':pair,'momentum_pct':momentum,'spread_bps':spread,
                        'action':'EXPLORE_ONLY','strategy':'FAST_STREAM_REST_RESEARCH',
                        'verified_funding_pair':verified_pair,
                        'time_window':'30s if available','validated':False})
        except (ValueError,TypeError,InvalidOperation,IndexError,KeyError):rejected+=1
    return out,rejected


def fast_funnel(*,detected=0,selected=0,fetched=0,errors=0,targets=0,
                 planner=None,snowball=None,simulated_delta=0,fresh=None):
    p=planner or {};s=snowball or {}
    return {'stream_alerts':int(detected),'fundable_alerts':int(selected),
            'book_requests':int(fetched)+int(errors),'fresh_books':int(fresh) if fresh is not None else 0,
            'quote_errors':int(errors),'fresh_targets':int(targets),
            'one_order_routes':int(p.get('one_order_routes_evaluated',p.get('viable_routes',0)) or 0),
            'distinct_candidate_routes':len({tuple(i.get('route') or ()) for i in p.get('ideas',())}),
            'route_blockers':dict(p.get('route_blockers') or {}),
            'immediate_priced':int(s.get('priced') or 0),
            'positive_estimates':int(s.get('positive') or 0),
            'above_target':int(s.get('above_floor') or 0),
            'modeled_fills_this_event':int(simulated_delta),
            'no_live_orders':True}
