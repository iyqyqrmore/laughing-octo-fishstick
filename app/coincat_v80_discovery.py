"""Fair quote discovery plus bounded, deadline-only research observations.

One unchanged 16-book collection budget. No profitability-based scheduling,
forecast gate, rate-limit override, financial write or execution authority.
"""
from decimal import Decimal
from coincat_v703_chain import approved_pairs
from coincat_v701_quotes import valid_book
from coincat_cross_quote import usd_conversion, split_spot

MAX_BOOK_REQUESTS = 16
MAX_ENDPOINT_REQUESTS = 6
REUSE_AGE_S = 6  # Leaves room for a 6s collection within the 12s frame span.


def book_status(raw, now):
    """Diagnose an observation without ever making an unusable book usable."""
    if raw is None:
        return 'UNOBSERVED'
    try:
        stamp = float(raw[2])
        book=valid_book(raw, stamp, 30)
        if book is None:
            return 'INVALID'
        if (book[1]-book[0])/book[1]>Decimal('.0025'):
            return 'WIDE'
        if stamp > now:
            return 'FUTURE'
        return 'STALE' if now-stamp > 30 else 'FRESH'
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        return 'INVALID'


def listed_usd_paths(catalog):
    """Predeclare shortest/lexical simple paths once, without quote economics."""
    edges={};direct={'USD':()}
    for pair in sorted(set(catalog)):
        base,quote=split_spot(pair)
        edges.setdefault(base,[]).append((quote,pair))
        edges.setdefault(quote,[]).append((base,pair))
        if quote=='USD':
            direct.setdefault(base,(pair,))
        if base=='USD':
            direct.setdefault(quote,(pair,))
    paths=dict(direct)
    for asset,neighbors in edges.items():
        if asset in paths:
            continue
        candidates=[(pair,)+direct[target] for target,pair in neighbors if target in direct]
        if candidates:
            paths[asset]=min(candidates)
    return paths


def select_books(catalog, rules, funding, *, quotes, now, cursor=0, limit=16,
                 max_routes=None, valuation_catalog=None, excluded=(), priority_groups=()):
    listed = approved_pairs(catalog, rules, excluded)
    valuation = set(approved_pairs(valuation_catalog if valuation_catalog is not None else catalog,
                                   rules, excluded))
    valuation_quotes = {p:q for p,q in sorted(quotes.items()) if p in valuation}
    sources = set(funding)-set(excluded)
    routes = []
    for pair in listed:
        base, quote = split_spot(pair)
        if quote in sources:
            routes.append((pair, 'BUY', quote, base))
        if base in sources:
            routes.append((pair, 'SELL', base, quote))
    count = len(routes)
    budget = max(0, min(MAX_BOOK_REQUESTS, int(limit)))
    chosen, selected = [], []
    dependencies = set()
    endpoint_groups = endpoint_deferred = endpoint_unavailable = 0

    def needed(books, earliest=None):
        extra = []
        for product in dict.fromkeys(books):
            cached = valid_book(quotes.get(product), now, REUSE_AGE_S, Decimal('.0025'))
            reusable = cached is not None and (earliest is None or cached[2] >= earliest)
            if product not in chosen and not reusable:
                extra.append(product)
        return extra

    # Earliest-expiring observations get at most six GETs. Shared paths are
    # deduplicated; discovery always retains at least ten slots at full budget.
    due = sorted(priority_groups, key=lambda g:(g['deadline'], tuple(g['books'])))
    for group in due:
        if not group['earliest'] <= now <= group['deadline']:
            continue
        books = tuple(dict.fromkeys(group['books']))
        if not set(books) <= valuation:
            endpoint_unavailable += 1
            continue
        extra = needed(books, group['earliest'])
        if len(chosen)+len(extra) > min(MAX_ENDPOINT_REQUESTS, budget):
            endpoint_deferred += 1
            continue
        chosen.extend(extra)
        dependencies.update(books)
        endpoint_groups += 1
    endpoint_requests = len(chosen)

    mark_cache = {}
    structural_paths=listed_usd_paths(valuation)
    def wallet_path(asset):
        if asset == 'USD':
            return ()
        if asset not in mark_cache:
            structural = structural_paths.get(asset)
            observed = usd_conversion(asset, valuation_quotes, now=now, max_age=30, max_legs=2)
            # Fetch a shorter listed path before using an incidental indirect
            # cached path. Direct USD trades must use their own consistent mark.
            path = (observed['path'] if observed is not None and structural is not None
                    and len(observed['path']) <= len(structural) else structural)
            mark_cache[asset] = path
        return mark_cache[asset]

    offset = int(cursor)%count if count else 0
    deferred = missing = examined = 0
    first_deferred = None
    for i in range(count):
        if max_routes is not None and len(selected) >= max_routes:
            first_deferred = i
            break
        pair, side, source, target = routes[(offset+i)%count]
        examined += 1
        source_path, target_path = wallet_path(source), wallet_path(target)
        forbidden = () if 'USD' in (source, target) else (pair,)
        if (source_path is None or target_path is None or
                any(p in forbidden for p in source_path+target_path)):
            missing += 1
            continue
        dependency = tuple(dict.fromkeys((pair,)+source_path+target_path))
        extra = needed(dependency)
        if len(chosen)+len(extra) > budget:
            deferred += 1
            if first_deferred is None:
                first_deferred = i
            continue
        chosen.extend(extra)
        dependencies.update(dependency)
        selected.append((pair, side, source, target))
    advance = max(1, first_deferred if first_deferred is not None else examined)
    target_routes = {}
    for pair,side,source,target in selected:
        target_routes.setdefault(target, []).append(pair)
    return {'eligible_directions':routes, 'books':chosen,
        'targets':list(dict.fromkeys((target,pair) for pair,side,source,target in selected)),
        'target_routes':target_routes, 'directions':selected,
        'candidate_routes':count, 'funding_routes_deferred':max(0,count-len(selected)),
        'selected_directions':len(selected), 'examined':examined,
        'missing_independent_paths':missing, 'request_budget_deferred':deferred,
        'cached_reused_books':len(dependencies-set(chosen)),
        'endpoint_groups_scheduled':endpoint_groups,
        'endpoint_groups_deferred':endpoint_deferred,
        'endpoint_groups_unavailable':endpoint_unavailable,
        'endpoint_requests':endpoint_requests,
        'next_cursor':(offset+advance)%count if count else 0,
        'next_route_cursor':int(cursor)+advance, 'next_target_cursor':0,
        'mark_refresh_deferred':False, 'unlisted_mark_assets':[],
        'candidates':[{'pair':pair,'target_asset':target,'momentum_pct':Decimal(0),
            'spread_bps':Decimal(0),'action':'EXPLORE_ONLY',
            'strategy':'DIRECT_IMMEDIATE_DISCREPANCY'} for pair,side,source,target in selected]}
