"""v60.12 plain-English, *presentation-only* research decisions and small BUY preflight.

No exchange IO, financial ledger writes, history pruning or trade authorization.
The raw reason codes remain unchanged in reports and complete cell tooltips.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from coincat_cross_quote import split_spot

MIN_PAIRED_WINDOWS=35
MIN_SPAN_DAYS=Decimal('7')


def _number(value):
    try:
        value=Decimal(str(value))
        return value if value.is_finite() else None
    except (ValueError,TypeError,InvalidOperation):
        return None


def history_percent(idea):
    """Data maturity, NOT win rate, expected profitability or permission.

    BOTH independent paired-window count and elapsed span are required. An
    unreported span cannot be represented as 100% merely from many labels.
    """
    windows=max(0,int(_number((idea or {}).get('evidence_windows')) or 0))
    days=_number((idea or {}).get('evidence_span_days'))
    if days is None:days=Decimal(0)
    observed=min(Decimal(1),Decimal(windows)/MIN_PAIRED_WINDOWS)
    elapsed=min(Decimal(1),max(Decimal(0),days)/MIN_SPAN_DAYS)
    return max(0,min(100,int(min(observed,elapsed)*100)))


def cost_drag_percent(idea):
    """Immediate modeled USD mark drag; includes spread/fee/slippage once.

    This is NOT a claim that the entire loss is an exchange trading fee. It is
    the decrease in the compared portfolio slice immediately after conversion.
    """
    before=_number((idea or {}).get('initial_wallet_usd_mark'))
    delta=_number((idea or {}).get('immediate_change_usd'))
    if before is None or before<=0 or delta is None or delta>=0:return None
    pct=(-delta/before*100).quantize(Decimal('0.1'),rounding=ROUND_CEILING)
    return pct


def decision_label(idea,*,shadow_armed=False,delivered_to_shadow=False):
    idea=idea or {}
    state=str(idea.get('research_decision') or '').upper()
    reason=str(idea.get('reason') or '').upper()
    if 'MINIMUM' in state or 'MINIMUM' in reason or state=='SMALL':return 'Small'
    if 'NO_FRESH_LISTED_ROUTE' in state or 'UNLISTED' in state:return 'Unavailable'
    if 'MISSING_USD_CONVERSION' in state:return 'USD?'
    if state in ('SWITCH_WORTH_RESEARCH','SHADOW_COMPONENT_SCREENED'):
        return 'S.Ready - '+('Y' if shadow_armed and delivered_to_shadow else 'N')
    if state=='HOLD_PREFERRED':
        drag=cost_drag_percent(idea)
        if drag is not None and _number(idea.get('net_mean_usd')) is not None and _number(idea.get('net_mean_usd'))<=0:
            return f'Costs {drag:.1f}%'
        return 'Hold'
    if 'COST' in state or ('COST' in reason and state not in ('STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED','HOLD_UNTIL_VERIFIED')):
        drag=cost_drag_percent(idea)
        return f'Costs {drag:.1f}%' if drag is not None else 'Costs'
    if state in ('STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED','HOLD_UNTIL_VERIFIED',
                 'JOINT_FORWARD_EVIDENCE_REQUIRED') or not state:
        return f'History {history_percent(idea)}%'
    return 'Wait'


def reason_tooltip(idea,*,shadow_armed=False,delivered_to_shadow=False):
    idea=idea or {}
    state=str(idea.get('research_decision') or '')
    label=decision_label(idea,shadow_armed=shadow_armed,delivered_to_shadow=delivered_to_shadow)
    details=[]
    if label.startswith('History'):
        details.append('Research history completion, NOT probability of profit.')
        details.append(f'Paired 1-hour windows: {idea.get("evidence_windows",0)}/35; span: {idea.get("evidence_span_days","unknown")}/7 days.')
        details.append('Even at 100%, independent portfolio-vs-HOLD validation and all risk gates must pass.')
    elif label=='Small':details.append('This proposal does not meet verified Coinbase product minimums or increments at the funded size; research may continue.')
    elif label=='Unavailable':details.append('No eligible authenticated single-order Coinbase spot product; excluded from active routing until authenticated catalog recheck.')
    elif label=='USD?':details.append('A fresh USD valuation is unavailable. This does NOT necessarily mean the pair is unlisted. Trading blocked pending fresh valid marks; no permanent exclusion.')
    elif label.startswith('Costs'):
        details.append('Modeled immediate wallet-value drag, including fees, spread and slippage assumptions, rounded UP to tenths. Not an actual paid fee and not a prediction of future losses.')
    elif label=='Hold':details.append('Current comparison favors keeping the existing coin(s), or has not demonstrated enough after-cost improvement.')
    elif label.startswith('S.Ready'):
        if delivered_to_shadow and shadow_armed:
            details.append('Y = eligible candidate handed to the armed SHADOW observer. This does not mean it filled; FIFO and risk checks are separate.')
        elif not shadow_armed:
            details.append('N = SHADOW is not armed. No simulation handoff occurred.')
        else:
            details.append('N = candidate was not in the eligible modeled-wallet batch; check actual funding, order minimums, quote freshness and independent portfolio evidence.')
    if state:details.append('Internal code: '+state)
    raw=str(idea.get('reason') or '')
    if raw:details.append('Detail: '+raw)
    drag=cost_drag_percent(idea)
    if drag is not None and not label.startswith('Costs'):
        details.append(f'Immediate modeled mark drag: {drag:.1f}% (not future profit forecast).')
    return '\n'.join(details)


def known_small_direct_buy(pair,rules,enrollment,verified_balances,books,*,now):
    """Reject only DEFINITELY insufficient available quote funds for a direct BUY.

    A false positive could incorrectly suppress trading opportunity research.
    Therefore unknown product rules, unknown quote, unknown enrolled funding,
    stale books and variable fee currency return None (ordinary review handles).
    This check ONLY prevents redundant brokerage *read-only* review; the
    portfolio planner continues researching alternative funding sources.
    """
    try:
        base,quote=split_spot(pair)
        rule=(rules or {}).get(pair)
        if not isinstance(rule,dict):return None
        allowed={str(r.get('asset','')).upper():_number(r.get('remaining_qty'))
                 for r in enrollment or () if r.get('enabled',1)}
        approved=allowed.get(quote)
        verified=_number((verified_balances or {}).get(quote))
        if approved is None or verified is None or min(approved,verified)<=0:
            return None  # absence of quote fuel is NOT a claim of small order
        min_quote=_number(rule.get('quote_min_size'))
        min_base=_number(rule.get('base_min_size'))
        min_required=max(Decimal(0),min_quote or Decimal(0))
        if min_base is not None and min_base>0:
            book=(books or {}).get(pair)
            if not book or len(book)<3:return None
            ask=_number(book[1]);timestamp=_number(book[2])
            if ask is None or ask<=0 or timestamp is None or not 0 <= Decimal(str(now))-timestamp <=120:
                return None
            min_required=max(min_required,min_base*ask)
        if min_required<=0:return None
        funding=min(approved,verified)
        if funding < min_required:
            return (f'Coinbase requires at least {min_required} {quote} before fees; '
                    f'approved available {funding} {quote}.')
    except (KeyError,TypeError,ValueError,InvalidOperation,IndexError):pass
    return None
