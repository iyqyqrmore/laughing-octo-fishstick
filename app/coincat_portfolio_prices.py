"""READ-ONLY portfolio USD valuation independent of AI Lab market selection.

Authenticated Coinbase Advanced Trade pricebooks are used as observations; no
last-trade ticker, pegged stablecoins, old purchase marks or invented pairs.
No permission/order/ledger writes and no pricebook result enters the broker.
"""
from __future__ import annotations
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
import time
from coinbase_account import as_dict
from coincat_cross_quote import split_spot, usd_conversion

MAX_BOOK_IDS = 32
MAX_REQUESTS = 8
MAX_AGE_S = 300
DISPLAY_MAX_SPREAD = Decimal('.20')
MAX_VALUATION_LEGS = 3


def _positive(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() and d > 0 else Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _graph(catalog):
    graph = defaultdict(list)
    for pair in sorted(set(catalog or ())):
        try:
            base, quote = split_spot(pair)
        except ValueError:
            continue
        graph[base].append((quote, pair))
        graph[quote].append((base, pair))
    return graph


def _routes_to_usd(asset, graph, max_legs=MAX_VALUATION_LEGS, max_routes=5):
    """Actual listed product paths, ordered by fewest legs, no imaginary trades."""
    if asset == 'USD':
        return [()]
    found = []
    queue = deque([(asset, (), frozenset((asset,)))])
    # Bounded by hops and a small per-source alternative count; there is no
    # external work or order submission from this path search.
    while queue and len(found) < max_routes:
        currency, products, seen = queue.popleft()
        if currency == 'USD':
            found.append(products)
            continue
        if len(products) >= max_legs:
            continue
        # Prefer USD, USDC, BTC, ETH, USDT for early alternatives, but never
        # exclude or demote an arbitrary valid asset by its quote denomination.
        priority = {'USD': 0, 'USDC': 1, 'BTC': 2, 'ETH': 3, 'USDT': 4}
        for next_currency, product in sorted(graph.get(currency, ()),
                                             key=lambda t: (priority.get(t[0], 9), t[0], t[1])):
            if next_currency not in seen:
                queue.append((next_currency, products + (product,), seen | {next_currency}))
    return found


def requested_portfolio_pairs(catalog, balances):
    """Choose book products covering ALL held coins, then fallback paths.

    Requested path products are prioritized over generic USD pairs, so the
    number of research catalog pairs cannot crowd out valuation of holdings.
    """
    graph = _graph(catalog)
    held = sorted(asset for asset, qty in (balances or {}).items() if _positive(qty))
    per_coin = {asset: _routes_to_usd(asset, graph) for asset in held if asset != 'USD'}
    requested = []
    # First route for *each* coin before alternatives for any coin. Each
    # proposed path gets all its legs, or none, within our bounded budget.
    max_routes = max((len(routes) for routes in per_coin.values()), default=0)
    for tier in range(max_routes):
        for asset in held:
            routes = per_coin.get(asset, ())
            if tier >= len(routes):
                continue
            products = [product for product in routes[tier] if product not in requested]
            if len(requested) + len(products) <= MAX_BOOK_IDS * MAX_REQUESTS:
                requested.extend(products)
    return tuple(requested)


def fetch_portfolio_books(client, catalog, balances, *, now=None):
    """Batched authenticated read-only REST snapshots; never touch orders."""
    ids = requested_portfolio_pairs(catalog, balances)
    timestamp = time.time() if now is None else float(now)
    values = {}
    errors = []
    rejected = 0
    for offset in range(0, len(ids), MAX_BOOK_IDS):
        subset = ids[offset:offset + MAX_BOOK_IDS]
        try:
            data = as_dict(client.get_best_bid_ask(product_ids=list(subset)))
            books = data.get('pricebooks')
            if not isinstance(books, list):
                raise ValueError('No pricebooks in Coinbase response')
            for book in books:
                try:
                    book = as_dict(book)
                    pair = str(book['product_id'])
                    if pair not in subset:
                        continue
                    bids, asks = book['bids'], book['asks']
                    best_bid = as_dict(bids[0]); best_ask = as_dict(asks[0])
                    bid = _positive(best_bid['price'])
                    ask = _positive(best_ask['price'])
                    if not (bid > 0 and ask >= bid):
                        rejected += 1
                        continue
                    values[pair] = (bid, ask, timestamp)
                except (KeyError, IndexError, TypeError, ValueError, AttributeError, InvalidOperation):
                    rejected += 1
        except Exception as exc:
            # Errors are intentionally type-only: Coinbase may include
            # sensitive or account-specific information in message text.
            errors.append(type(exc).__name__)
    return {'quotes': values, 'requested': len(ids), 'received': len(values),
            'missing_books': len(set(ids) - set(values)), 'invalid_books': rejected,
            'error': ', '.join(errors[:3]), 'at': timestamp}


def portfolio_usd_rates(currencies, quotes, *, now=None, max_age=MAX_AGE_S):
    """Conservative fresh USD/unit quotes up to three *listed* spot legs."""
    timestamp = time.time() if now is None else float(now)
    result = {}
    for currency in sorted(set(currencies)):
        result[currency] = usd_conversion(currency, quotes, now=timestamp,
                         max_age=max_age, max_legs=MAX_VALUATION_LEGS,
                         max_spread=DISPLAY_MAX_SPREAD)
    return result


def portfolio_coverage(balances, catalog, quotes, *, now=None):
    """Shared READ-ONLY valuation health for Portfolio, AI Lab and Auto Trader.

    Contains aggregate counts and missing symbols only, never balances, keys,
    account IDs or dollar amounts; does not authorize any trading action.
    """
    now = time.time() if now is None else float(now)
    held = {asset: _positive(qty) for asset, qty in (balances or {}).items() if _positive(qty)}
    values = portfolio_usd_rates(held, quotes, now=now)
    graph = _graph(catalog)
    missing = {}
    for asset in sorted(held):
        if values.get(asset) is not None:
            continue
        if not _routes_to_usd(asset, graph):
            reason = 'NO COINBASE USD ROUTE ≤3 LEGS'
        else:
            required = requested_portfolio_pairs(catalog, {asset:held[asset]})
            if not any(pair in quotes for pair in required):
                reason = 'NO BID/ASK BOOKS RECEIVED'
            else:
                reason = 'NO FRESH USABLE PATH (STALE/MISSING/WIDE SPREAD)'
        missing[asset] = reason
    return {'held_count':len(held), 'priced_count':len(held)-len(missing),
            'unpriced_count':len(missing), 'missing':missing,
            'complete':not missing and bool(held), 'rates':values}
