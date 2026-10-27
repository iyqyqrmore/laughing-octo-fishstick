"""Portfolio-value objective support: offline, read-only research helpers.

Opportunity discovery does not depend on which assets the account owns. An
owned asset is potential *authorized liquid inventory* and not a reason to
rank a market. Whole-holding exit estimates are not executable order plans;
Coinbase increments/minimums, settled fees, FX at fill time, tax lots, risk
limits and explicit ARM still govern every actual order.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
from coincat_cross_quote import split_spot, USD_QUOTES


def balanced_market_universe(catalog, reserved=()):
    """Interleave non-dollar and dollar markets with a stable order independent
    of holdings. Coinbase eligible product catalog is authoritative.

    Equal *sampling slots* do NOT assert equal liquidity, quality or profitability.
    Qualified scouts may supersede this fallback ordering.
    """
    reserved = set(reserved)
    cross, dollar = [], []
    for name in set(catalog or ()):
        try:
            _, quote = split_spot(name)
        except (ValueError, TypeError):
            continue
        if name in reserved:
            continue
        (dollar if quote in USD_QUOTES else cross).append(name)
    # Stable, deterministic scatter to prevent the first few symbols in
    # alphabetic order from monopolizing the same 45-minute fallback cohort.
    key = lambda name: (sha256(name.encode('ascii')).hexdigest(), name)
    cross.sort(key=key); dollar.sort(key=key)
    result = []
    for idx in range(max(len(cross), len(dollar))):
        if idx < len(cross): result.append(cross[idx])
        if idx < len(dollar): result.append(dollar[idx])
    return result


def full_holding_exit_preview(*, authorized_qty, verified_available_qty,
        bid_quote, quote_to_usd, usd_per_order_cap, price_age_s,
        balance_age_s, max_price_age_s=180, max_balance_age_s=300):
    """Value 100% of *currently authorized/verified* base inventory in USD.

    Returns the theoretical number of per-order-cap slices, NOT executable
    orders. Cannot authorize an over-cap order or infer FX, Coinbase fees,
    precision, min size, tax gain or expected total-portfolio improvement.
    """
    def pos(raw, label):
        try: value = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f'{label} is not numeric') from None
        if not value.is_finite() or value <= 0:
            raise ValueError(f'{label} must be finite and positive')
        return value
    qty = pos(authorized_qty, 'approved quantity')
    available = pos(verified_available_qty, 'Coinbase available quantity')
    bid = pos(bid_quote, 'market bid')
    fx = pos(quote_to_usd, 'USD conversion')
    cap = pos(usd_per_order_cap, 'order cap')
    for age, ceiling, label in ((price_age_s, max_price_age_s, 'market quote'),
                                (balance_age_s, max_balance_age_s, 'Coinbase balance')):
        try: age = float(age)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f'{label} freshness is unknown') from None
        if not 0 <= age <= ceiling:
            raise ValueError(f'{label} too old or unverified')
    liquid = min(qty, available)
    gross = liquid * bid * fx
    theoretical_orders = int((gross / cap).to_integral_value(rounding=ROUND_CEILING))
    return {
        'state':'RESEARCH ONLY', 'liquid_qty':liquid,
        'gross_usd_before_fees':gross, 'usd_per_order_cap':cap,
        'min_cap_slices_estimate':theoretical_orders,
        'full_disposition_possible_in_one_current_cap_order':theoretical_orders == 1,
        'disclaimer':'Not an order instruction or net gain: market impact, Coinbase minimums/increments, fee currency, taxes, verified fills and independent ARM remain mandatory.'
    }


def priority_cross_cohort(catalog, reserved=(), *, capacity=64, cohort_epoch=0):
    """Reserve fair deep-study coverage for actual exchange-listed cross quotes.

    If all cross-quoted pairs fit in half the non-anchor budget, include all.
    Otherwise rotate a deterministic half-budget cohort each epoch, leaving
    remaining slots for USD and all other eligible markets. No holdings bias.
    """
    cross=[]
    exclude=set(reserved)
    for pair in set(catalog or ()):
        try:
            _,quote=split_spot(pair)
            if pair not in exclude and quote not in USD_QUOTES: cross.append(pair)
        except (ValueError,TypeError): continue
    cross.sort(key=lambda p:(sha256(p.encode('ascii')).hexdigest(),p))
    slots=max(0,int(capacity)-len(exclude))
    if not slots or not cross:return []
    count=min(len(cross), max(1,slots//2))
    if count==len(cross):return cross
    start=(max(0,int(cohort_epoch))*count)%len(cross)
    return (cross[start:]+cross[:start])[:count]


def quote_mix(pairs):
    """Return source-neutral counts for comparing full catalog and deep cohort."""
    mix={'USD/USDC':0,'USDT/DAI':0,'CRYPTO/OTHER':0}
    for pair in set(pairs or ()):
        try:_,q=split_spot(pair)
        except (TypeError,ValueError):continue
        key='USD/USDC' if q in USD_QUOTES else 'USDT/DAI' if q in ('USDT','DAI') else 'CRYPTO/OTHER'
        mix[key]+=1
    return mix
