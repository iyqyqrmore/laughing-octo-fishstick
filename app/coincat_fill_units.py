"""Coinbase Advanced Trade fill-unit normalization (pure, network-free).

Fill `size` is in quote currency when `size_in_quote` is true. Never
mistake a dollar notional for base-token inventory. Ambiguous/incomplete
fills must halt reconciliation instead of being guessed or retried.
"""
from decimal import Decimal, InvalidOperation


class FillUnitError(ValueError):
    pass


def _decimal(value, field):
    if value is None or isinstance(value, bool):
        raise FillUnitError(f'Missing/invalid {field}')
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise FillUnitError(f'Invalid Coinbase {field}') from exc
    if not number.is_finite() or number < 0:
        raise FillUnitError(f'Invalid Coinbase {field}')
    return number


def _quote_flag(value):
    if value is None or value is False or value == 0 or value == 'false' or value == 'False':
        return False
    if value is True or value == 1 or value == 'true' or value == 'True':
        return True
    raise FillUnitError('Unrecognized Coinbase size_in_quote value')


def normalize_fill(fill):
    """Return quantities for one fill, preserving actual exchange commission.

    When size_in_quote is absent, legacy Coinbase fills are assumed to have
    base size, but order-level totals must still agree before any ledger write.
    """
    if not isinstance(fill, dict):
        raise FillUnitError('Invalid Coinbase fill record')
    price = _decimal(fill.get('price'), 'fill price')
    raw_size = _decimal(fill.get('size'), 'fill size')
    fee = _decimal(fill.get('commission'), 'fill commission')
    if price <= 0 or raw_size <= 0:
        raise FillUnitError('Nonpositive Coinbase fill size or price')
    quote_sized = _quote_flag(fill.get('size_in_quote'))
    base_qty = raw_size / price if quote_sized else raw_size
    quote_qty = raw_size if quote_sized else raw_size * price
    return dict(base_qty=base_qty, quote_qty=quote_qty, commission=fee,
                quote_sized=quote_sized, price=price)


def summarize_fills(fills, *, order_id, pair, side=None):
    if not isinstance(fills, list) or not fills:
        raise FillUnitError('No Coinbase fills returned')
    total_base = total_quote = total_fees = Decimal('0')
    count_quote = 0
    seen = set()
    for fill in fills:
        if str(fill.get('order_id') or '') != str(order_id):
            raise FillUnitError('Fill belongs to another order')
        if fill.get('product_id', pair) != pair:
            raise FillUnitError('Fill belongs to another product')
        if side is not None and str(fill.get('side', side)).upper() != side:
            raise FillUnitError('Fill side disagrees with Coinbase order')
        tid = str(fill.get('trade_id') or '')
        if not tid or tid in seen:
            raise FillUnitError('Duplicate or missing Coinbase trade_id')
        seen.add(tid)
        n = normalize_fill(fill)
        count_quote += int(n['quote_sized'])
        total_base += n['base_qty']
        total_quote += n['quote_qty']
        total_fees += n['commission']
    return dict(base_qty=total_base, quote_qty=total_quote, fees=total_fees,
                quote_sized=count_quote, base_sized=len(fills)-count_quote,
                count=len(fills))


def verify_order_totals(order, totals):
    """Cross-check base filled_size, gross quote filled_value, and fees.

    This function never changes an order or assumes an ambiguous amount is a
    SOL/BTC/ETH quantity. A mismatch must leave the order pending/disarmed.
    """
    base = _decimal(order.get('filled_size'), 'order filled_size')
    if base <= 0 or abs(totals['base_qty'] - base) > Decimal('0.000000001'):
        raise FillUnitError('Normalized base fills do not match Coinbase filled_size')
    value = order.get('filled_value')
    if value is not None:
        value = _decimal(value, 'order filled_value')
        if abs(totals['quote_qty'] - value) > Decimal('0.000001'):
            raise FillUnitError('Quote fill amounts do not match Coinbase filled_value')
    fees = order.get('total_fees', order.get('fee'))
    if fees is not None:
        fees = _decimal(fees, 'order total_fees')
        if abs(totals['fees'] - fees) > Decimal('0.000001'):
            raise FillUnitError('Fill commissions do not match Coinbase reported fees')
    return True
