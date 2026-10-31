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
                 max_routes=None, valuation_catalog=None, excluded=(), priority_groups=(),
                 valuation_groups=(), cycle_groups=(), service_period_s=12):
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
    research_due=[];research_scheduled=[];research_deferred=[];research_unavailable=[]
    research_evidence={}

    def needed(books, earliest=None):
        extra = []
        for product in dict.fromkeys(books):
            cached = valid_book(quotes.get(product), now, REUSE_AGE_S, Decimal('.0025'))
            reusable = cached is not None and (earliest is None or cached[2] >= earliest)
            if product not in chosen and not reusable:
                extra.append(product)
        return extra

    # Protect an individual deadline before horizon-level aging when another
    # conservative collection turn may not fit. This is an estimate, never a
    # promise of network service. Outside that window retain aging EDF.
    def priority(group):
        last_turn=group['deadline']-now <= service_period_s+6
        if last_turn:
            return (0,group['deadline'],0,0,tuple(group['books']))
        wait=group.get('wait_passes',0)
        return (1,0 if wait>=2 else 1,-wait if wait>=2 else 0,
                group['deadline'],tuple(group['books']))
    due = sorted(priority_groups,key=priority)
    committed_groups=0
    for group in due:
        if not group['earliest'] <= now <= group['deadline']:
            continue
        jobs=group.get('jobs',())
        research_due.extend(jobs)
        books = tuple(dict.fromkeys(group['books']))
        extra = needed(books, group['earliest'])
        windows=group.get('job_windows',{})
        def evidence(state, blockers=()):
            for job in jobs:
                earliest,deadline=windows.get(job,(group['earliest'],group['deadline']))
                remaining=deadline-now
                flags=list(blockers)
                if remaining < 6:
                    flags.append('LESS_THAN_COLLECTION_WINDOW_REMAINING')
                if remaining <= service_period_s+6:
                    flags.append('NO_CONSERVATIVE_RETRY_WINDOW')
                research_evidence[job]={'state':state,'blockers':tuple(flags),
                    'required_books':len(books),'additional_books':len(needed(books,earliest)),
                    'group_additional_books':len(extra),
                    'research_books_committed':len(chosen),
                    'competing_groups':committed_groups,'research_limit':min(MAX_ENDPOINT_REQUESTS,budget),
                    'remaining_s':max(0,remaining),'estimated_service_period_s':service_period_s,
                    'deadline':deadline,'planned_at':now}
        if not set(books) <= valuation:
            endpoint_unavailable += 1
            research_unavailable.extend(jobs)
            evidence('UNAVAILABLE',('PRODUCT_UNAVAILABLE',))
            continue
        if len(chosen)+len(extra) > min(MAX_ENDPOINT_REQUESTS, budget):
            endpoint_deferred += 1
            research_deferred.extend(jobs)
            blockers=['SIX_BOOK_RESEARCH_LIMIT' if budget>=MAX_ENDPOINT_REQUESTS else 'OVERALL_REQUEST_LIMIT']
            if len(extra)>min(MAX_ENDPOINT_REQUESTS,budget):
                blockers.append('DEPENDENCIES_CANNOT_FIT_TOGETHER')
            if committed_groups:
                blockers.append('COMPETING_DEADLINE_GROUPS')
            evidence('DEFERRED',blockers)
            continue
        evidence('SCHEDULED')
        chosen.extend(extra)
        dependencies.update(books)
        endpoint_groups += 1
        research_scheduled.extend(jobs)
        committed_groups+=1
    endpoint_requests = len(chosen)

    # One fresh native-cycle group shares the six-book research allowance.
    # Refresh every dependency in this collection; never fill from old scans.
    cycle_group=None;cycle_deferred=0
    for group in cycle_groups:
        books=tuple(dict.fromkeys(group['books']))
        extra=[p for p in books if p not in chosen]
        if not set(books)<=valuation or len(chosen)+len(extra)>min(MAX_ENDPOINT_REQUESTS,budget):
            cycle_deferred+=1
            continue
        chosen.extend(extra);dependencies.update(books);cycle_group=group
        break
    cycle_requests=len(chosen)-endpoint_requests

    # One atomic account-wide ETH group if it fits, otherwise a rotating
    # per-asset group. Every dependency includes ETH-USD. Never combine partial
    # groups into a claimed synchronized account total or exceed 16 GETs.
    eth_group=None;eth_deferred=0
    for group in valuation_groups:
        books=tuple(dict.fromkeys(group['books']))
        if not set(books)<=valuation:
            continue
        extra=needed(books)
        if len(chosen)+len(extra)>budget:
            eth_deferred+=1
            continue
        chosen.extend(extra);dependencies.update(books)
        eth_group=group
        break
    valuation_requests=len(chosen)-endpoint_requests-cycle_requests

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
        '_research_due':research_due,'_research_scheduled':research_scheduled,
        '_research_deferred':research_deferred,'_research_unavailable':research_unavailable,
        '_research_evidence':research_evidence,
        '_cycle_group':cycle_group,'cycle_requests':cycle_requests,'cycle_groups_deferred':cycle_deferred,
        '_eth_group':eth_group,'eth_valuation_requests':valuation_requests,
        'eth_groups_deferred':eth_deferred,
        'next_cursor':(offset+advance)%count if count else 0,
        'next_route_cursor':int(cursor)+advance, 'next_target_cursor':0,
        'mark_refresh_deferred':False, 'unlisted_mark_assets':[],
        'candidates':[{'pair':pair,'target_asset':target,'momentum_pct':Decimal(0),
            'spread_bps':Decimal(0),'action':'EXPLORE_ONLY',
            'strategy':'DIRECT_IMMEDIATE_DISCREPANCY'} for pair,side,source,target in selected]}
