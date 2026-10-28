"""Pure approval, ranking and unit contracts shared by the decision chain.

No network, credentials, financial writes, arming or order interface.
"""
from decimal import Decimal, InvalidOperation
from coincat_v6010_registry import one_order_catalog
from coincat_multicurrency import _rule


def approved_pairs(catalog,rules,excluded=(),*,funding=None):
    excluded=set(excluded)
    funding=None if funding is None else set(funding)
    out=[]
    for pair in one_order_catalog(catalog,rules):
        base,quote=pair.split('-')
        rec=(rules or {}).get(pair)
        if base in excluded or quote in excluded:continue
        if not isinstance(rec,dict) or _rule(rules,pair) is None:continue
        if rec.get('product_id',pair)!=pair:continue
        status=str(rec.get('status') or '').lower()
        if status and status!='online':continue
        if funding is not None and not ({base,quote}&funding):continue
        out.append(pair)
    return out


def target_momentum(idea):
    """Observed relative change, not a forecast; invert a falling base exactly."""
    try:
        raw=Decimal(str(idea.get('observed_momentum_pct',0)))
        pair=str(idea.get('trigger_pair','')).split('-')
        if not raw.is_finite() or len(pair)!=2:return None
        if idea.get('target')==pair[1] and raw<0:
            if raw<=-100:return None
            return (1/(1+raw/100)-1)*100
        return raw
    except (TypeError,ValueError,InvalidOperation,ZeroDivisionError):return None


def legacy_repeat_score(idea):
    """Archived repeat-momentum baseline for offline comparisons ONLY."""
    if idea.get('sends_live_orders') is not False:return None
    steps=idea.get('shadow_fifo_steps') or ()
    if len(steps)!=1 or idea.get('source')=='MULTI':return None
    try:
        momentum=target_momentum(idea)
        # Apply the provisional future move to actual after-cost receipts, not
        # to a nominal cap that may include unspent rounding residuals.
        notional=Decimal(str(steps[0].get('output_usd_mark',idea.get('research_size_cap_usd'))))
        change=Decimal(str(idea.get('immediate_change_usd')))
        if not notional.is_finite() or not change.is_finite():return None
    except (TypeError,ValueError,InvalidOperation):return None
    if not notional.is_finite() or not change.is_finite():return None
    instant=None
    try:
        value=Decimal(str(idea.get('snowball_immediate_usd')))
        if value.is_finite() and value>0 and idea.get('snowball_state')=='IMMEDIATE_ESTIMATE':instant=value
    except (TypeError,ValueError,InvalidOperation):pass
    trend=(notional*momentum/100+change if momentum is not None and
           Decimal('.35')<=momentum<=25 and notional>0 else None)
    return max((v for v in (instant,trend) if v is not None),default=None)


def experimental_score(idea,*,now=None):
    from coincat_v706_selection import assess
    import time
    now=idea.get('selection_asof',time.time()) if now is None else now
    return assess(idea,now=now)['score_usd']


def ranked_one_order_ideas(ideas,limit=12,*,now=None):
    """Best eligible provisional score across ALL costed proposals, then clip."""
    singles=[i for i in ideas if i.get('source')!='MULTI' and len(i.get('shadow_fifo_steps') or ())==1]
    scored=[(experimental_score(i,now=now),i) for i in singles]
    return [i for score,i in sorted(scored,key=lambda item:(
        -(item[0] if item[0] is not None else Decimal('-1e99')),
        -Decimal(str(item[1].get('immediate_change_usd',0))),
        str(item[1].get('source')),str(item[1].get('target'))))[:limit]]


def rank_experimental(ideas,quotes,now,limit=12,forward_evidence=None):
    from coincat_snowball import assess_idea
    from coincat_v706_selection import assess
    annotated=[];fx_cache={}
    for old in ideas:
        steps=old.get('shadow_fifo_steps') or ()
        if len(steps)!=1 or old.get('source')=='MULTI':continue
        idea=dict(old)
        assessment=assess_idea(idea,quotes,now=now,taker_fee=steps[0].get('fee_rate_used'),_fx_cache=fx_cache)
        idea['snowball_immediate_usd']=str(assessment['delta_usd']) if assessment['delta_usd'] is not None else None
        idea['snowball_state']=assessment['state']
        idea['snowball_executable_verified']=False
        idea['selection_asof']=now
        idea['forward_edge_evidence']=(forward_evidence or {}).get((steps[0]['pair'],steps[0]['side']),{})
        policy=assess(idea,now=now)
        idea.update(selection_state=policy['state'],selection_reason=policy['reason'],
                    selection_basis=policy['basis'],selection_score_usd=policy['score_usd'])
        annotated.append(idea)
    return ranked_one_order_ideas(annotated,limit,now=now)


def step_input_usd(step,usd_rates):
    """A SELL spends BASE units; a BUY spends QUOTE units. Never mix them."""
    base,quote=str(step['pair']).split('-')
    side=str(step['side']).upper()
    if side not in ('BUY','SELL'):raise ValueError('Invalid side')
    asset=quote if side=='BUY' else base
    if step.get('input_asset',asset)!=asset:raise ValueError('Input currency mismatch')
    qty=Decimal(str(step['input_quantity']))
    rate=Decimal(1) if asset=='USD' else Decimal(str(usd_rates[asset]))
    if not qty.is_finite() or not rate.is_finite() or min(qty,rate)<=0:raise ValueError('Invalid input USD mark')
    return qty*rate


def decision_key(idea,books):
    """One currency family per real quote observation, independent of size UI."""
    pairs=sorted({s['pair'] for s in idea.get('shadow_fifo_steps') or ()})
    return (str(idea.get('source')),str(idea.get('target')),
            tuple((p,tuple(str(v) for v in books[p])) for p in pairs))
