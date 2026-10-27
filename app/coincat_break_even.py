"""Read-only break-even stress math; NOT an executable quote or profit forecast."""
from decimal import Decimal, InvalidOperation

SLIPPAGE_STRESS_PER_LEG = Decimal('0.0015')

def required_moves(order_usd, profit_target_usd, fee_per_leg=None,
                   slippage_per_leg=SLIPPAGE_STRESS_PER_LEG):
    """Return pct rise needed under symmetric per-leg friction assumptions.

    Does not assume a quoted exchange fee or market spread; real-world spread,
    depth, FX and partial fills can worsen execution. Always advisory.
    """
    try:
        # Missing verified fee rate must NOT silently become the old 1% stress
        # allowance and masquerade as a current break-even forecast.
        if fee_per_leg is None:return None
        if isinstance(fee_per_leg,(bool,float)):return None
        amount, target, fee, slip = [Decimal(str(v)) for v in
                                      (order_usd, profit_target_usd, fee_per_leg, slippage_per_leg)]
        if not all(v.is_finite() for v in (amount, target, fee, slip)):
            return None
        if amount<=0 or target<0 or not (Decimal(0)<=fee<Decimal('.05')) or not (Decimal(0)<=slip<Decimal('.05')):
            return None
        retained=(Decimal(1)-fee)**2 * (Decimal(1)-slip)**2
        break_even=(Decimal(1)/retained-Decimal(1))*Decimal(100)
        target_move=((Decimal(1)+target/amount)/retained-Decimal(1))*Decimal(100)
        return {'break_even_pct':break_even,'target_move_pct':target_move,
                'account_tier_round_trip_fee_estimate_pct':fee*Decimal(200),
                'assumed_round_trip_slippage_pct':slip*Decimal(200)}
    except (InvalidOperation, ValueError, TypeError, ZeroDivisionError):
        return None


def one_order_reference(fee_per_order,slippage_per_order=SLIPPAGE_STRESS_PER_LEG):
    """Single direct order friction only; no buy+later-sell fiction."""
    try:
        fee=Decimal(str(fee_per_order));slip=Decimal(str(slippage_per_order))
        if isinstance(fee_per_order,(float,bool)) or not all(x.is_finite() for x in (fee,slip)):
            return None
        if not (0<=fee<Decimal('.05') and 0<=slip<Decimal('.05')):return None
        retained=(1-fee)*(1-slip)
        return {'one_order_recovery_pct':(1/retained-1)*100,
                'fee_pct':fee*100,'assumed_slippage_pct':slip*100}
    except (InvalidOperation,ValueError,TypeError,ZeroDivisionError):return None
