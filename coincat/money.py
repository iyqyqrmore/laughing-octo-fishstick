"""Exact native amounts and authoritative current-leg fee accounting."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from functools import wraps

D = Decimal
ZERO = D(0)
ONE = D(1)


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Expected an exact decimal amount")
    amount = D(value)
    if not amount.is_finite():
        raise ValueError("Expected a finite amount")
    return amount


def native_math(function):
    @wraps(function)
    def run(*args, **kwargs):
        with localcontext() as context:
            context.prec = 80
            return function(*args, **kwargs)

    return run


def snap(amount, increment, up=False):
    rounding = ROUND_CEILING if up else ROUND_FLOOR
    return (amount / increment).to_integral_value(rounding=rounding) * increment


@dataclass(frozen=True)
class Commission:
    currency: str
    amount: Decimal

    def __post_init__(self):
        if not self.currency or decimal(self.amount) < ZERO:
            raise ValueError("Invalid native commission")


@dataclass(frozen=True)
class FeeSchedule:
    maker: Decimal
    taker: Decimal

    def __post_init__(self):
        if not all(ZERO <= decimal(rate) < ONE for rate in (self.maker, self.taker)):
            raise ValueError("Invalid commission rate")


@native_math
def maker_commission(quote, quantity, price, rate):
    if quantity < ZERO or price <= ZERO or not ZERO <= rate < ONE:
        raise ValueError("Invalid modeled fill")
    return Commission(quote, quantity * price * rate)


@native_math
def conversion(base, quote, side, quantity, price, fee):
    if side not in ("BUY", "SELL") or quantity <= ZERO or price <= ZERO or base == quote:
        raise ValueError("Invalid conversion")
    direction = ONE if side == "BUY" else -ONE
    changes = {base: direction * quantity, quote: -direction * quantity * price}
    changes[fee.currency] = changes.get(fee.currency, ZERO) - fee.amount
    return changes


@native_math
def value(wallet, marks):
    return sum((quantity * marks[asset] for asset, quantity in wallet.items()), ZERO)


@native_math
def reserve(base, quote, side, quantity, price, rate):
    fee = maker_commission(quote, quantity, price, rate)
    asset = quote if side == "BUY" else base
    return asset, -conversion(base, quote, side, quantity, price, fee)[asset]
