"""v50.6 portfolio capital and protected-profit reserve ADVISORY.

Exact-Decimal calculations; never mutates account, ledger or trading limits.
A USD reserve in volatile holdings is NOT ring-fenced money. Enforcement
requires verified per-asset excluded balances AND a certified portfolio floor.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation,localcontext
from dataclasses import dataclass
from datetime import date

class CapitalBlocked(ValueError):pass

def d(value,*,allow_zero=True):
    if value is None or isinstance(value,(bool,float)):raise CapitalBlocked('Exact nonnegative USD value required')
    try:v=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise CapitalBlocked('Invalid USD amount') from None
    if not v.is_finite() or v<0 or (not allow_zero and v==0):raise CapitalBlocked('Invalid USD amount')
    return v

def quarter_label(day):
    if not isinstance(day,date):raise CapitalBlocked('Verified calendar day required')
    return f'{day.year}-Q{(day.month-1)//3+1}'

@dataclass(frozen=True)
class ReserveView:
    enrolled_usd:Decimal
    liquid_available_usd:Decimal
    starting_capital_usd:Decimal
    net_external_contributions_usd:Decimal
    safeguarded_original_usd:Decimal
    remaining_available_usd:Decimal
    quarter:str
    doubling_reached:bool
    reserve_funded:bool
    state:str


def reserve_view(*,enrolled_usd,verified_liquid_usd,starting_capital_usd,
                 net_external_contributions_usd='0',verified_reserve_usd='0',
                 protect_original_after_doubling=False,day):
    """An *advisory*, not a trade authorization or custody of funds.

    A doubling is measured on net-external-flow-adjusted value. Once reached,
    original starting stake is suggested for segregation. Never silently
    labels a suggested reserve as protected: reserve_funded is independently
    asserted by an externally verified excluded/segregated amount.
    """
    with localcontext() as ctx:
        ctx.prec=100
        total=d(enrolled_usd);liquid=d(verified_liquid_usd)
        start=d(starting_capital_usd,allow_zero=False)
        deposits=Decimal(str(net_external_contributions_usd))
        if not deposits.is_finite():raise CapitalBlocked('External-flow evidence missing')
        reserve=d(verified_reserve_usd)
        if liquid>total or reserve>total or liquid+reserve>total:
            raise CapitalBlocked('Reserve must be excluded from spendable verified portfolio')
        effective=total-deposits
        doubled=effective>=start*2
        suggested=start if protect_original_after_doubling and doubled else Decimal(0)
        funded=(reserve>=suggested and suggested>0)
        # Reserve must be excluded from verified liquid funding inventory. Never
        # double-subtract it from verified spendable units.
        spendable=liquid
        if suggested and not funded:
            # A proposed reserve is not a safe spendable balance. Pause proposed
            # capital increase until the reserve is actually segregated.
            spendable=Decimal(0)
        state=('RESERVE_SEGREGATION_REQUIRED' if suggested and not funded
               else 'FUNDED_RESERVE_CONFIRMED' if funded
               else 'NO_AUTOMATIC_RESERVE')
        return ReserveView(total,liquid,start,deposits,suggested,spendable,
                           quarter_label(day),doubled,funded,state)


def size_advice(*,view,verified_order_funding_usd,proposed_notional_usd,
                worst_case_fees_spread_slippage_usd,expected_incremental_net_usd,
                confidence_validated,manual_per_order_limit_usd,manual_daily_remaining_usd,
                independent_portfolio_floor_headroom_usd,minimum_net_gain_usd='0.55'):
    """Large positions permitted up to confirmed liquid/floor/manual constraints.

    Refuses to infer a profitable trade from a 0.55 SELL target or an AI score.
    An independent validated forward net gain is needed even for research advice.
    """
    with localcontext() as ctx:
        ctx.prec=100
        requested=d(proposed_notional_usd,allow_zero=False)
        stressed=d(worst_case_fees_spread_slippage_usd)
        expected=Decimal(str(expected_incremental_net_usd))
        if not expected.is_finite():raise CapitalBlocked('Unverified forecast amount')
        available=min(view.remaining_available_usd,d(verified_order_funding_usd),
                      d(manual_per_order_limit_usd),d(manual_daily_remaining_usd),
                      d(independent_portfolio_floor_headroom_usd))
        reasons=[]
        if not confidence_validated:reasons.append('OUT_OF_SAMPLE_NET_USD_EDGE_UNVERIFIED')
        if expected<d(minimum_net_gain_usd):reasons.append('NET_USD_GAIN_BELOW_PREFERENCE')
        if requested+stressed>available:reasons.append('FUNDING_OR_RISK_HEADROOM_INSUFFICIENT')
        if not view.reserve_funded and view.safeguarded_original_usd>0:
            reasons.append('PROTECTED_ORIGINAL_CAPITAL_NOT_SEGREGATED')
        return {'advisory_only':True,'order_allowed':False,
                'research_qualified':not reasons,
                'max_stressed_usd':format(available,'f'),
                'maximum_gross_usd':format(max(Decimal(0),available-stressed),'f'),
                'reason_codes':tuple(reasons) or ('VALIDATED_RESEARCH_ONLY_PRODUCTION_BLOCKED',)}


def capital_rehearsal():
    """No private values, wallets or network; exercises crossing the doubling point."""
    from datetime import date
    a=reserve_view(enrolled_usd='199.99',verified_liquid_usd='199.99',starting_capital_usd='100',
                   protect_original_after_doubling=True,day=date(2026,10,24))
    b=reserve_view(enrolled_usd='200',verified_liquid_usd='100',starting_capital_usd='100',
                   verified_reserve_usd='100',protect_original_after_doubling=True,day=date(2026,10,24))
    c=reserve_view(enrolled_usd='200',verified_liquid_usd='200',starting_capital_usd='100',
                   verified_reserve_usd='0',protect_original_after_doubling=True,day=date(2026,10,24))
    allowed=size_advice(view=b,verified_order_funding_usd='100',proposed_notional_usd='90',
                worst_case_fees_spread_slippage_usd='3',expected_incremental_net_usd='1.50',
                confidence_validated=True,manual_per_order_limit_usd='100',
                manual_daily_remaining_usd='100',independent_portfolio_floor_headroom_usd='100')
    assert not a.doubling_reached and a.remaining_available_usd==Decimal('199.99')
    assert b.doubling_reached and b.reserve_funded and b.remaining_available_usd==100
    assert c.state=='RESERVE_SEGREGATION_REQUIRED' and c.remaining_available_usd==0
    assert allowed['research_qualified'] and not allowed['order_allowed']
    assert quarter_label(date(2027,1,1))=='2027-Q1'
    return {'doubling_below':True,'reserve_segmentation':True,'growth_budget':True,
            'quarterly_manual_only':True,'no_live_orders':True}
