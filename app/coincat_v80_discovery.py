"""Shared quote-quality and static-path helpers for canonical/secondary models.

One unchanged 16-book collection budget. No profitability-based scheduling,
forecast gate, rate-limit override, financial write or execution authority.
"""
from decimal import Decimal
from coincat_v701_quotes import valid_book
from coincat_cross_quote import split_spot

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
