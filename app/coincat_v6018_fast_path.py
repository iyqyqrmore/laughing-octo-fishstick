"""Bounded event-to-REST research queue. NO signals, orders or broker permissions.

All candidates originate in authenticated spot catalog + public WebSocket alerts.
REST bid/ask verification and existing full-portfolio planner remain authoritative.
Price observations used here are NEVER a Coinbase executable-order preview.
"""
from decimal import Decimal, InvalidOperation

MAX_FAST_BOOKS=16
MAX_TARGETS=3


def select_fast_books(alerts, catalog, funding_assets, *, limit=MAX_FAST_BOOKS,
                      required_assets=(), quotes=None, now=None,target_assets=None,valuation_catalog=None):
    """Refresh HOLD/current/fee marks before adding complete target dependencies.

    Cached <=12s marks need not consume a request. A small budget refreshes marks
    in stages; it never invents coverage or an unlisted bridge. No research gate.
    """
    import time
    from coincat_v701_quotes import mark_paths, mark_coverage
    from coincat_portfolio_prices import DISPLAY_MAX_SPREAD
    now = time.time() if now is None else now
    budget = min(MAX_FAST_BOOKS, max(0, int(limit)))
    available = set(catalog or ())
    funding = {str(a).upper() for a in funding_assets or () if a}
    required = funding | set(required_assets or ())
    chosen, missing_paths, targets = [], [], []

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

    baseline = dependencies(required,valuation=True)
    chosen.extend(baseline[:budget])
    deferred = len(baseline) > budget
    routes = []
    for pair in alerts or ():
        if deferred or len(targets) >= MAX_TARGETS: break
        if pair not in available or '-' not in pair: continue
        asset = (target_assets or {}).get(pair,pair.split('-')[0])
        if asset not in pair.split('-'):continue
        if asset in [a for a, _ in targets]: continue
        direct = [p for fund in sorted(funding) for p in
                  (f'{asset}-{fund}', f'{fund}-{asset}') if p in available]
        if not direct: continue
        # Prefer one complete conversion over seven routes with incomplete marks.
        route = direct[0]
        extra = list(dict.fromkeys([pair, route]+dependencies({asset})))
        extra = [p for p in extra if p not in chosen]
        if len(chosen)+len(extra) > budget: continue
        chosen.extend(extra)
        targets.append((asset, pair))
        routes.extend(p for p in direct if p not in routes)
    # Remaining capacity can verify alternative funding routes, never displace
    # a required HOLD/current mark or a complete selected target.
    for route in routes:
        if len(chosen)>=budget: break
        if route not in chosen: chosen.append(route)
    return {'targets': targets, 'books': chosen, 'candidate_routes': len(routes),
            'funding_assets': len(funding), 'max_books': MAX_FAST_BOOKS,
            'required_assets': sorted(required | {a for a, _ in targets}),
            'unlisted_mark_assets': missing_paths, 'mark_refresh_deferred': deferred}


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
