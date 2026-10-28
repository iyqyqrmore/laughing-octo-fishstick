"""Read-only, conservative USD value estimates for non-USD Coinbase spot pairs.

Prices are observed Coinbase bid/ask quotes, never executable conversion orders.
FX paths are simple, bounded (at most two spot legs), fresh, and prefer the
lower realizable bid / inverse ask. No assumed USDC peg. No API access or orders.

These observations may support AI Lab display. They DO NOT authorize live
cross-quoted orders, tax basis, quote-wallet disposal, or settlement accounting.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from collections import deque
import re

SPOT_PAIR_RE = re.compile(r'^[A-Z0-9]{2,20}-[A-Z0-9]{2,20}$')
USD_QUOTES = frozenset(('USD', 'USDC'))


def split_spot(pair):
    if not isinstance(pair, str) or not SPOT_PAIR_RE.fullmatch(pair):
        raise ValueError('Invalid uppercase Coinbase spot product identifier')
    base, quote = pair.split('-')
    if base == quote:
        raise ValueError('A spot pair must contain two different assets')
    return base, quote


def is_cross_quote(pair):
    return split_spot(pair)[1] not in USD_QUOTES


def _positive(raw):
    v = Decimal(str(raw))
    if not v.is_finite() or v <= 0:
        raise ValueError('Invalid price')
    return v


def usd_conversion(currency, quotes, *, now, max_age=180, max_legs=2, max_spread=Decimal('.0025'), excluded_pairs=()):
    """Return conservative USD/unit and source path, or None (unverifiable).

    quotes: {PAIR: (bid, ask, observed_epoch_secs)}. Reverse direction
    uses 1/ask, not the inverse bid. Quotes must be recent, valid and cannot
    be ticker-only last-trade observations. No synthetic USD/USDC equality.
    """
    if currency == 'USD':
        return {'rate': Decimal(1), 'path': (), 'observed_age_s': 0}
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Z0-9]{2,20}',currency):
        return None
    if max_legs not in (1, 2, 3) or max_age <= 0:
        raise ValueError('Unsafe FX path limits')
    max_spread = _positive(max_spread)
    if max_spread >= 1: raise ValueError('Unusable spread cap')
    graph = {}
    for pair, quote in quotes.items():
        if pair in excluded_pairs:continue
        try:
            a, b = split_spot(pair)
            bid, ask, timestamp = quote
            bid, ask = _positive(bid), _positive(ask)
            age = float(now) - float(timestamp)
            if age < 0 or age > max_age or bid > ask:
                continue
            # A huge spread is unusable for valuation or research profit checks.
            if (ask-bid)/ask > max_spread:
                continue
            graph.setdefault(a, []).append((b, bid, pair, int(age)))
            graph.setdefault(b, []).append((a, Decimal(1)/ask, pair, int(age)))
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            continue
    # Find shortest valid path first, then select the highest conservative
    # proceeds among paths of that length. Never traverse a currency twice.
    queue = deque([(currency, Decimal(1), (), 0, frozenset((currency,)))])
    candidates = []
    while queue:
        node, value, path, worst_age, seen = queue.popleft()
        if node == 'USD':
            candidates.append((value, path, worst_age))
            continue
        if len(path) >= max_legs:
            continue
        for target, rate, pair, age in graph.get(node, ()):
            if target not in seen:
                queue.append((target, value*rate, path+(pair,), max(worst_age, age), seen|{target}))
    if not candidates:
        return None
    shortest = min(len(path) for _, path, _ in candidates)
    rate, path, worst_age = max((x for x in candidates if len(x[1]) == shortest), key=lambda x: x[0])
    return {'rate': rate, 'path': path, 'observed_age_s': worst_age}


def research_sell_preview(bid_quote, quote_to_usd, *, available_base, usd_order_cap,
                          basis_usd, target_net_usd, assumed_fee_rate=None,
                          slippage_bps=Decimal('15')):
    """Conservative *research estimate* of a non-USD pair's sell proceeds.

    Caller must verify FIFO lot basis in USD for the same base quantity and
    mark the result RESEARCH ONLY. Does not calculate executable base increment.
    """
    bid = _positive(bid_quote)
    conversion = _positive(quote_to_usd)
    available = _positive(available_base)
    cap = _positive(usd_order_cap)
    quantity = min(available, cap/(bid*conversion))
    if assumed_fee_rate is None:
        raise ValueError('Coinbase fee evidence required for cross-quote research preview')
    fee = Decimal(str(assumed_fee_rate))
    slippage = Decimal(str(slippage_bps))/Decimal(10000)
    if fee < 0 or fee >= 1 or slippage < 0 or slippage >= 1:
        raise ValueError('Invalid research fee or slippage estimate')
    cost = Decimal(str(basis_usd))
    target = Decimal(str(target_net_usd))
    if not cost.is_finite() or cost < 0 or not target.is_finite() or target < 0:
        raise ValueError('Invalid USD basis/target')
    proceeds_usd = quantity*bid*conversion*(1-fee)*(1-slippage)
    net_usd = proceeds_usd-cost
    net_pct = net_usd/cost*100 if cost>0 else None
    action = ('SELL' if net_usd >= target else
              'PROTECTIVE EXIT' if net_pct is not None and net_pct <= Decimal('-3') else 'HOLD')
    return {'action': action, 'size_base': quantity, 'gross_usd': quantity*bid*conversion,
            'net_usd': net_usd, 'net_pct': net_pct,
            'reason': 'Read-only cross-quote estimate; Coinbase preview, currency lots and verified fees required'}
