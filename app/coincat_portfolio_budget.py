"""Fail-closed, USD-verified enrolled portfolio ceiling for manual pilot budgets.

This is NOT a trading instruction, AI-selected parameter, or cross-quote fill
permission. Pricebook marks can overstate executable proceeds; each Coinbase
order still needs current actual funding, fees, spread, and stop checks.
"""
from decimal import Decimal, InvalidOperation
from coincat_live import LiveBlocked

def portfolio_ceiling(enrollment, balances, rate_records):
    """Conservative MAX upper bound; None means some authorized asset unpriced.

    No staking/excluded/unavailable quantities are included. Uses bid-side
    USD rates from current externally authenticated Coinbase books.
    """
    total=Decimal(0)
    for item in enrollment or ():
        if not item.get('enabled',1):
            continue
        asset=item.get('asset')
        try:
            remaining=Decimal(str(item.get('remaining_qty','0')))
            available=Decimal(str((balances or {}).get(asset,'0')))
            if not remaining.is_finite() or not available.is_finite() or min(remaining,available)<0:
                return None
            qty=min(remaining,available)
            if qty==0:continue
            record=(rate_records or {}).get(asset)
            rate=record.get('rate') if isinstance(record,dict) else None
            if rate is None:return None
            fx=Decimal(str(rate))
            if not fx.is_finite() or fx<=0:return None
            total+=qty*fx
        except (InvalidOperation,ValueError,TypeError,AttributeError):
            return None
    return total if total>0 and total.is_finite() else None

def validate_manual_budget(order,daily,exposure,attempts,portfolio_usd):
    try:
        limit=Decimal(str(portfolio_usd))
        values=[Decimal(str(x)) for x in (order,daily,exposure)]
        number=int(attempts)
        if not limit.is_finite() or limit<=0 or any(not v.is_finite() or v<=0 for v in values):
            raise ValueError('Invalid positive amounts')
        if any(v>limit for v in values):
            raise LiveBlocked('Budget exceeds verified available ENROLLED portfolio USD value')
        if str(attempts).strip()!=str(number) or number<=0:
            raise LiveBlocked('Attempts must be a positive whole number')
        # Safety bound unrelated to any capacity-stage token: manual only.
        # Prevent unbounded order storms. Counts BUY attempts; protective exits
        # cannot be blocked by this setting.
        maximum=min(1000,max(12,int(limit)))
        if number>maximum:
            raise LiveBlocked(f'Maximum {maximum} manual BUY attempts per rolling 24h for current verified portfolio')
        return limit
    except LiveBlocked:raise
    except (ValueError,TypeError,InvalidOperation,OverflowError):
        raise LiveBlocked('Invalid manually requested portfolio trading budget') from None
