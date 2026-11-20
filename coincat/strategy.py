"""Independent one-leg maker decisions and native post-only proposals."""

from dataclasses import dataclass
from decimal import Decimal

from .market import BASE, QUOTE
from .money import Commission, D, ONE, ZERO, conversion, maker_commission, native_math, snap, value

SOURCE_FRACTION = D(".10")
MAX_TARGET_CONCENTRATION = D(".80")
MAX_SPREAD = D(".005")
EXECUTION_ALLOWANCE = D(".0005")


@dataclass(frozen=True)
class Candidate:
    side: str
    funding: str
    target: str
    price: Decimal
    quantity: Decimal
    budget: Decimal
    destination: Decimal
    fee: Commission
    rate: Decimal
    immediate: Decimal
    versus_hold: Decimal
    horizon: int
    advantage: Decimal
    uncertainty_pct: Decimal
    observations: int
    reason: str

    @property
    def qualified(self):
        return self.reason == "QUALIFIED_CONDITIONAL"


def legal_size(rules, quantity, price):
    total = quantity * price
    return (
        quantity > 0
        and price > 0
        and quantity % rules.base_step == 0
        and price % rules.price_step == 0
        and quantity >= rules.base_min
        and total >= rules.quote_min
        and (rules.base_max is None or quantity <= rules.base_max)
        and (rules.quote_max is None or total <= rules.quote_max)
    )


@native_math
def candidate(frame, wallet, hold, rate, forecasts, side, *, resting=None):
    book, rules = frame.native, frame.rules
    funding, target = (QUOTE, BASE) if side == "BUY" else (BASE, QUOTE)
    if (book.ask - book.bid) / book.midpoint > MAX_SPREAD:
        return "WIDE_NATIVE_SPREAD"
    if resting is None:
        price = snap(book.bid if side == "BUY" else book.ask, rules.price_step, up=side == "SELL")
        budget = wallet[funding] * SOURCE_FRACTION
        if price <= ZERO:
            return "NONPOSITIVE_NATIVE_PRICE"
        limit = budget / (price * (ONE + rate)) if side == "BUY" else budget
        limits = [limit]
        if rules.base_max is not None:
            limits.append(rules.base_max)
        if rules.quote_max is not None:
            limits.append(rules.quote_max / price)
        largest = snap(min(limits), rules.base_step)
        # A trade starts at the smallest legal size. Reconsider larger clips only
        # after the conditional execution model has evidence for them.
        quantity = snap(max(rules.base_min, rules.quote_min / price), rules.base_step, up=True)
        if quantity < rules.base_min or quantity * price < rules.quote_min:
            quantity += rules.base_step
        if quantity > largest:
            return "SOURCE_BUDGET_BELOW_NATIVE_MINIMUM"
    else:
        price, quantity = resting
    if (side == "BUY" and price >= book.ask) or (side == "SELL" and price <= book.bid):
        return "CROSSING_NATIVE_LIMIT"
    if resting is None and not legal_size(rules, quantity, price):
        return "NATIVE_SIZE_OR_INCREMENT"
    commission = maker_commission(QUOTE, quantity, price, rate)
    change = conversion(BASE, QUOTE, side, quantity, price, commission)
    updated = {asset: wallet[asset] + change[asset] for asset in wallet}
    if min(updated.values()) < ZERO:
        return "INSUFFICIENT_AVAILABLE_SOURCE"
    marks = frame.marks
    nav = value(updated, marks)
    hold_value = value(hold, marks)
    immediate = value(change, marks)
    allowance = change[target] * marks[target] * EXECUTION_ALLOWANCE
    horizon, advantage, uncertainty, observations = 0, immediate - allowance, ZERO, 0
    for forecast in forecasts:
        adjusted = dict(marks)
        if forecast.anchor is None:
            continue
        adjusted[BASE] = marks[QUOTE] * forecast.anchor * (ONE + forecast.shift(side))
        conservative = value(change, adjusted) - allowance
        if conservative > advantage:
            horizon, advantage = forecast.horizon, conservative
            uncertainty = forecast.upper - forecast.lower
            observations = forecast.validation_count
    concentration = updated[target] * marks[target] / nav if nav else ONE
    reason = "QUALIFIED_CONDITIONAL"
    if concentration > MAX_TARGET_CONCENTRATION:
        reason = "TARGET_CONCENTRATION_LIMIT"
    elif advantage <= ZERO:
        reason = "NO_POSITIVE_RISK_ADJUSTED_ADVANTAGE"
    return Candidate(
        side,
        funding,
        target,
        price,
        quantity,
        -change[funding],
        change[target],
        commission,
        rate,
        immediate,
        nav - hold_value,
        horizon,
        advantage,
        uncertainty,
        observations,
        reason,
    )


def evaluate(frame, wallet, hold, rate, forecasts=(), *, now=None):
    if now is not None and not frame.fresh(now):
        return {"BUY": "STALE_OR_UNSYNCHRONIZED_BOOKS", "SELL": "STALE_OR_UNSYNCHRONIZED_BOOKS"}
    if rate is None:
        return {"BUY": "AUTHENTICATED_MAKER_FEE_UNVERIFIED", "SELL": "AUTHENTICATED_MAKER_FEE_UNVERIFIED"}
    return {side: candidate(frame, wallet, hold, rate, forecasts, side) for side in ("BUY", "SELL")}


def strongest(candidates):
    return max(
        (entry for entry in candidates.values() if isinstance(entry, Candidate) and entry.qualified),
        key=lambda entry: (entry.advantage, -entry.horizon),
        default=None,
    )
