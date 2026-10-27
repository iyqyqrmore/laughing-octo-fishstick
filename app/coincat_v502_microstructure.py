"""CoinCat v50.2: evidence-gated, read-only microtrading cost research.

Personal-PC event-driven scalp / post-only maker *research*, NOT exchange HFT.
No SDK, credentials, wallet writes, ARM or order submission. Never promote
observed quote-currency momentum to independently validated forward USD edge.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, localcontext
from statistics import median
from coincat_multicurrency import DEFAULT_SLIPPAGE_BPS

class MicrostructureBlocked(ValueError):
    pass

def dec(value, *, nonnegative=False):
    if value is None or isinstance(value, (bool, float)):
        raise MicrostructureBlocked('Exact decimal evidence required, not float or missing')
    try: d=Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError): raise MicrostructureBlocked('Invalid decimal evidence') from None
    if not d.is_finite() or (nonnegative and d < 0):
        raise MicrostructureBlocked('Nonfinite or negative decimal evidence')
    return d

def stress_hurdle_pct(*, legs, fee_fraction, slippage_bps, half_spread_bps='0', safety_bps='0'):
    """Illustrative leg cost, not independently quoted fees nor guaranteed P&L.

    User-supplied spread is EXTRA half-spread; omit if bid/ask pricing already
    incorporates crossing costs to avoid double-counting.
    """
    if type(legs) is not int or not 1 <= legs <= 8:
        raise MicrostructureBlocked('Invalid number of legs')
    with localcontext() as ctx:
        ctx.prec=80
        fee=dec(fee_fraction,nonnegative=True)
        slip=dec(slippage_bps,nonnegative=True)
        spread=dec(half_spread_bps,nonnegative=True)
        safety=dec(safety_bps,nonnegative=True)
        if fee>=1 or any(bps>10000 for bps in (slip,spread,safety)):
            raise MicrostructureBlocked('Invalid stress parameters')
        return (fee*Decimal(100)+(slip+spread)/Decimal(100))*legs+safety/Decimal(100)

def approve_research_edge(*, independently_validated_forward_usd_pct, modeled_cost_pct,
                          validated_time_blocks, usd_marks_authenticated,
                          product_rules_authenticated, fee_previews_verified,
                          executable_quote_fresh, maker_fill_evidence_verified=False):
    """Conservative edge admissibility for research ranking ONLY, NEVER live permission."""
    reasons=[]
    if independently_validated_forward_usd_pct is None: reasons.append('NO_INDEPENDENT_FORWARD_USD_EDGE')
    if type(validated_time_blocks) is not int or validated_time_blocks<35: reasons.append('INSUFFICIENT_FORWARD_BLOCKS')
    for value,flag in (('FX_MARKS_NOT_AUTHENTICATED',usd_marks_authenticated),
                       ('PRODUCT_RULES_NOT_AUTHENTICATED',product_rules_authenticated),
                       ('FEE_PREVIEWS_NOT_VERIFIED',fee_previews_verified),
                       ('QUOTE_NOT_EXECUTABLY_FRESH',executable_quote_fresh)):
        if flag is not True:reasons.append(value)
    if maker_fill_evidence_verified is not True: reasons.append('MAKER_FILL_ADVERSE_SELECTION_UNKNOWN')
    try:
        cost=dec(modeled_cost_pct,nonnegative=True)
        edge=dec(independently_validated_forward_usd_pct) if independently_validated_forward_usd_pct is not None else None
        if edge is not None and edge <= cost:reasons.append('FORECAST_DOES_NOT_OVERCOME_COST')
    except MicrostructureBlocked:
        reasons.append('INVALID_EDGE_OR_COST')
    return {'research_state':'ELIGIBLE_TO_INVESTIGATE' if not reasons else 'WAIT',
            'reasons':tuple(reasons), 'authorizes_trade':False}

def evaluate_shadow_idea(idea):
    """Compute immediate modeled USD drag without exposing private inventory."""
    if not isinstance(idea,dict):return {'state':'UNAVAILABLE','mark_pct':None}
    try:
        with localcontext() as ctx:
            ctx.prec=80
            before=dec(idea.get('initial_wallet_usd_mark'))
            after=dec(idea.get('post_route_wallet_usd_mark'))
            if before<=0 or after<0:raise MicrostructureBlocked('Bad mark')
            delta=(after/before-1)*100
            route=idea.get('route')
            legs=len(route) if isinstance(route,(tuple,list)) else 0
            if not 1 <= legs <= 8:raise MicrostructureBlocked('No route')
            return {'state':'COST_DRAG' if delta<0 else 'IMMEDIATE_MARK_NONNEGATIVE',
                    'mark_pct':delta,'legs':legs,
                    'forward_usd_edge_state':'NOT_VALIDATED', 'authorizes_trade':False}
    except (MicrostructureBlocked,InvalidOperation,ValueError,ZeroDivisionError):
        return {'state':'UNAVAILABLE','mark_pct':None,'authorizes_trade':False}

def microstructure_report(app):
    cycle=getattr(app,'last_cycle',None) or {}
    shadow=cycle.get('auto_rotation') or {} if isinstance(cycle,dict) else {}
    ideas=(shadow.get('ideas') or [])[:12] if isinstance(shadow,dict) else []
    screened=[evaluate_shadow_idea(x) for x in ideas]
    negative=[x['mark_pct'] for x in screened if x.get('mark_pct') is not None and x['mark_pct']<0]
    positive=sum(1 for x in screened if x.get('state')=='IMMEDIATE_MARK_NONNEGATIVE')
    uncertain=sum(1 for x in screened if x.get('state')=='UNAVAILABLE')
    total=len(ideas)
    fee_data=getattr(app,'fee_learning',None)
    fee_state=fee_data.latest_tier() if fee_data else {'fresh':False,'state':'NO_ACCOUNT_FEE_EVIDENCE'}
    # Present the active ONE-order prescreen separately from historical
    # entry+exit comparisons. Neither diagnostic cost is subtracted from
    # modeled bid/ask route marks or charged to SHADOW FIFO.
    single_cost=(stress_hurdle_pct(legs=1,fee_fraction=fee_state['taker'],slippage_bps=DEFAULT_SLIPPAGE_BPS)
                 if fee_state.get('fresh') else None)
    roundtrip_cost=(stress_hurdle_pct(legs=2,fee_fraction=fee_state['taker'],slippage_bps=DEFAULT_SLIPPAGE_BPS)
                    if fee_state.get('fresh') else None)
    lines=[
        'CoinCat v50.5 — PERSONAL-PC MICROTRADING COST AND EDGE AUDIT',
        'OFFLINE/READ ONLY • NO COINBASE API • NO ORDER SUBMISSION • NOT A PROFIT FORECAST',
        'CoinGecko strategy #3 is high-frequency trading. This home-PC edition evaluates cost-aware,',
        'event-driven maker/taker feasibility; it does NOT claim microsecond HFT capability.',
        'MARKET EXECUTION FEES: '+fee_state['state']+'; account tiers are not pair-specific previews.',
        'Post-only orders may not fill; confirmed maker/taker status requires actual fills.',
        'and maker fills face queue position, repricing, missed opportunity and adverse selection.',
        'SOURCE OF LOSSES: modelled fee/slippage/spread drag, not trading budget caps or floors.',
        'BUDGET/FLOOR LIMITS: constrain trade permission/size; do not cause negative simulated marks.',
        'ACTIVE ONE-ORDER conversion screening hurdle (fee + stress slippage, BEFORE spread): '
            +(format(single_cost,'.4f')+'% using authenticated account taker tier' if single_cost is not None
              else 'UNAVAILABLE — fee tier missing or stale; no invented 1% fallback'),
        'HISTORICAL TWO-ORDER entry+later-exit sensitivity ONLY (NOT active one-order gate): '
            +(format(roundtrip_cost,'.4f')+'% using authenticated account taker tier' if roundtrip_cost is not None
              else 'UNAVAILABLE — fee tier missing or stale; no invented 1% fallback'),
        'NO DOUBLE FEE: observed-momentum hurdle filters research only; actual one-order route receipts charge the fee once, and FIFO inherits those receipts.',
        'HOLD-vs-SWITCH adds future relative asset returns to the already-after-cost route mark; no second fee subtraction.',
        'Slippage reserve per leg: '+format(DEFAULT_SLIPPAGE_BPS,'f')+' bps (ASSUMED; not confirmed fill slippage).',
        'Candidate route proposals shown: '+str(total)+' (may reuse target assets and represent no fills)',
        'Negative immediately marked USD routes: '+str(len(negative)),
        'Nonnegative immediate marks (NOT proof of profitability): '+str(positive),
        'Missing/invalid comparison marks: '+str(uncertain),
        'Validated positive independent forward USD edges: 0 • none supplied to this evaluator',
        'Routes eligible for automatic live action on this evidence: 0',
    ]
    if negative:
        lines.extend(('Median negative immediate modeled USD change: '+format(median(negative),'.4f')+'%',
                      'Worst negative immediate modeled USD change: '+format(min(negative),'.4f')+'%'))
    for idx,review in enumerate(screened,1):
        line=f'  ROUTE {idx:02d}: {review.get("state","UNAVAILABLE")}'
        if review.get('mark_pct') is not None:
            line+=' | simulated immediate USD change='+format(review['mark_pct'],'+.4f')+'%'
        line+=' | independently validated future USD edge=NO | NO ORDERS'
        lines.append(line)
    lines.extend([
        'HFT-LIKE RESEARCH GATES before any execution: confirmed fee tier and order previews;',
        'maker-vs-taker assignment per fill; bid/ask+depth/volume; queue/nonfill and adverse-selection',
        'measurements; precise increments/minimums; out-of-sample USD-vs-HOLD edge; full cost budget.',
        'Current research cannot infer future USD alpha from momentum or an assumed 70% win rate.',
        'Do not force twelve real orders when no qualifying trades exist.',
        'A future 12-trade pilot still needs production FIFO, idempotent POST recovery, verified fees',
        'and independent portfolio-wide loss protection. No approval is unlocked by this report.',
        'END MICROTRADING COST & EDGE AUDIT',
    ])
    return '\n'.join(lines)+'\n'
