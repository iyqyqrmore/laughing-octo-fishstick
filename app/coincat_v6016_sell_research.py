"""v60.16: fail-closed, full-quantity SELL research sizing (no order authority).

READ-ONLY valuation fuel is min(enrolled remaining, authenticated available),
never a broker's nominal $5/order or editable live capacity. The LIVE broker's
independent stage and per-order guards are unchanged. Do not infer extra funds,
create executable instructions, or assume product minimums/depth are satisfied.
"""
from decimal import Decimal, InvalidOperation


def _exact_positive(value):
    if isinstance(value, (bool, float)) or value is None:
        return None
    try:
        amount=Decimal(str(value))
        return amount if amount.is_finite() and amount>=0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def verified_full_sell_quantity(enrolled, available, *, fresh):
    """Available enrolled asset units; None = not independently verifiable."""
    if fresh is not True:
        return None
    authorized=_exact_positive(enrolled)
    liquid=_exact_positive(available)
    return min(authorized,liquid) if authorized is not None and liquid is not None else None


def research_preview_slice_cap(broker_order_cap, approved_stage_cap):
    """Conservative LIVE slice-count *reference* only; no research-size cap.

    A missing/invalid broker proposal never suppresses complete-holding
    research or legitimizes a larger live order.
    """
    approved=_exact_positive(approved_stage_cap)
    broker=_exact_positive(broker_order_cap)
    if approved is None or approved<=0:
        return Decimal('0.01')
    if broker is None or broker<=0:
        return approved
    return min(approved,broker)
