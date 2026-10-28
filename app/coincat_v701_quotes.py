"""Shared read-only quote validation and complete shadow mark dependencies."""
from decimal import Decimal, InvalidOperation
import math

from coincat_cross_quote import usd_conversion


def valid_book(raw, now, max_age=30):
    try:
        bid, ask, stamp = raw
        bid, ask, stamp = Decimal(str(bid)), Decimal(str(ask)), float(stamp)
        if (not bid.is_finite() or not ask.is_finite() or not math.isfinite(stamp)
                or not 0 < bid <= ask or not 0 <= now-stamp <= max_age
                or (ask-bid)/ask > Decimal('.0025')):
            return None
        return bid, ask, stamp
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        return None


def newest_books(*sources, now, max_age=180):
    """Never overwrite a newer valid book; ties prefer the first source."""
    result = {}
    for source in sources:
        for pair, raw in (source or {}).items():
            book = valid_book(raw, now, max_age)
            if book and (pair not in result or book[2] > result[pair][2]):
                result[pair] = book
    return result


def required_shadow_assets(*sessions, funding=()):
    assets = set(funding)
    for session in sessions:
        if not getattr(session, 'armed', False):
            continue
        for wallet in getattr(session, 'fifo_portfolios', {}).values():
            assets.update(wallet.start)
            # Current balances are supplied as cached funding by the worker.
            # SQLite RAM wallets belong to the GUI thread; do not query here.
    return sorted(a for a in assets if a and a != 'USD')


def mark_paths(asset, catalog):
    """Shortest listed path to USD, at most two legs; never assume a peg."""
    graph = {}
    for pair in sorted(set(catalog)):
        parts = pair.split('-')
        if len(parts) != 2 or parts[0] == parts[1]:
            continue
        a, b = parts
        graph.setdefault(a, []).append((b, pair))
        graph.setdefault(b, []).append((a, pair))
    queue = [(asset, (), {asset})]
    for node, path, seen in queue:
        if node == 'USD':
            return path
        if len(path) < 2:
            queue.extend((nxt, path+(pair,), seen | {nxt})
                         for nxt, pair in graph.get(node, ()) if nxt not in seen)
    return None


def mark_coverage(assets, books, *, now, max_age=30, max_skew=12):
    clean = newest_books(books, now=now, max_age=max_age)
    rates, problems, stamps = {'USD': '1'}, {}, []
    for asset in sorted(set(assets)-{'USD'}):
        fx = usd_conversion(asset, clean, now=now, max_age=max_age)
        if fx is None:
            problems[asset] = 'MISSING_STALE_WIDE_OR_INVALID_USD_PATH'
            continue
        rates[asset] = str(fx['rate'])
        stamps.extend(clean[p][2] for p in fx['path'])
    span = max(stamps)-min(stamps) if stamps else 0
    if span > max_skew:
        problems['_snapshot'] = 'UNSYNCHRONIZED_USD_PATHS'
    return {'complete': not problems, 'rates': rates, 'problems': problems,
            'book_span_s': span, 'assets': len(set(assets))}
