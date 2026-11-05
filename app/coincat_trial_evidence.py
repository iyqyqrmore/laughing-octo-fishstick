"""Prospective opportunity accounting, separate from clocks and fill assumptions."""
from decimal import Decimal as D
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_portfolio_policy import DIRECTIONS

VIEWS={v['id'] for v in DIRECTIONS}
COUNT_KEYS=('evaluations','direction_checks','qualifying_checks','opportunity_episodes')

def new_metrics(at,*,complete_history=True,prior_reviews=0):
    return dict(schema=1,since_at=at,complete_history=complete_history,prior_reviews=prior_reviews,
        **{k:0 for k in COUNT_KEYS},active={},last_review=None)

def validate_metrics(m):
    if m.get('schema')!=1 or type(m['complete_history']) is not bool:raise BetaBlocked('TRIAL_EVIDENCE_SCHEMA_INVALID')
    if any(type(m[k]) is not int or m[k]<0 for k in COUNT_KEYS+('prior_reviews',)):raise BetaBlocked('TRIAL_EVIDENCE_COUNT_INVALID')
    if m['direction_checks']!=14*m['evaluations'] or not 0<=m['opportunity_episodes']<=m['qualifying_checks']<=m['direction_checks']:
        raise BetaBlocked('TRIAL_EVIDENCE_TOTALS_INVALID')
    if not isinstance(m['active'],dict) or not set(m['active'])<=VIEWS or any(type(v) is not int or not 0<v<=m['opportunity_episodes'] for v in m['active'].values()):
        raise BetaBlocked('TRIAL_OPPORTUNITY_EPISODES_INVALID')
    if m['last_review'] is not None and len(m['last_review']['directions'])!=14:raise BetaBlocked('TRIAL_EVIDENCE_REVIEW_INVALID')

def observe(m,rows,at):
    """An episode begins on entry into qualification, not on every refresh.

    Invalid scans never call this reducer. Existing episodes survive gaps and
    restarts until a validated policy review actually changes qualification.
    """
    if len(rows)!=14 or {r['id'] for r in rows}!=VIEWS:raise BetaBlocked('FOURTEEN_DIRECTION_EVALUATION_REQUIRED')
    m['evaluations']+=1;m['direction_checks']+=14;active={};records=[]
    for row in rows:
        qualified=row['state']=='SHADOW_CANDIDATE';view=row['id']
        if qualified:
            m['qualifying_checks']+=1
            episode=m['active'].get(view)
            if episode is None:m['opportunity_episodes']+=1;episode=m['opportunity_episodes']
            active[view]=episode
        record=dict(view=view,state=row['state'],reason=row['reason'],episode=active.get(view),
            price=row.get('price'),size=row.get('size'),
            projected_fee_usd=row.get('projected_fee_usd'),
            projected_quote_fee=(row.get('receipt') or {}).get('fee_amount_estimate'),
            fee_currency_model=(row.get('receipt') or {}).get('assumed_fee_currency_for_research'),
            marked_execution_cost_usd=row.get('trading_cost_mark_usd'),
            estimated_uncertainty_usd=row.get('uncertainty_usd'),
            fill_feasibility='UNKNOWN_NO_CALIBRATED_MAKER_MODEL' if qualified else 'NOT_APPLICABLE',
            cost_classification='CONDITIONAL_FULL_FILL_QUOTE_FEE_MODEL')
        records.append(record)
    m['active']=active;m['last_review']=dict(at=at,directions=records,execution_reason=None)
    validate_metrics(m)

@native_math
def summary(state,progress):
    m=state.get('research_metrics');orders=list(state['orders'].values());fills=list(state['fills'].values())
    settled=[f for f in fills if f['settled']];unsettled=[f for f in fills if not f['settled']]
    unknown_orders=sum(o['state'] in ('UNKNOWN','CANCEL_PENDING') for o in orders)
    episodes=None if m is None else m['opportunity_episodes'];full=bool(m and m['complete_history'])
    fees={}
    for fill in settled:
        flow=fill['flow'];asset=flow['fee_currency'];fees[asset]=fees.get(asset,D(0))+flow['commission']
    perf=state['last_performance'] or {};difference=perf.get('outperformance_usd')
    unreconciled=bool(unsettled or unknown_orders or state['mode']=='RECONCILIATION_REQUIRED')
    if unreconciled:difference=None
    elif state['wallet']==state['original']:difference=D(0)
    benchmark='UNKNOWN' if difference is None else 'ABOVE_AS_MARKED' if difference>0 else 'BELOW_AS_MARKED' if difference<0 else 'EQUAL_AS_MARKED'
    if unreconciled:evidence='UNPROVEN_UNRECONCILED_OUTCOMES'
    elif not full:evidence='UNPROVEN_INCOMPLETE_OPPORTUNITY_HISTORY'
    elif not episodes and not settled:evidence='UNPROVEN_NO_QUALIFYING_TRADES'
    elif not settled:evidence='UNPROVEN_NO_SIMULATED_FILLS'
    else:evidence='UNPROVEN_EXPLICIT_REPLAY_ONLY'
    proposals=[]
    for o in orders:
        decision=o['decision'];receipt=decision.get('receipt') or {}
        proposals.append(dict(reference=o['reference'],pair=o['pair'],side=o['side'],state=o['state'],
            projected_full_fill_fee_usd=decision.get('projected_fee_usd'),
            projected_quote_fee=receipt.get('fee_amount_estimate'),quote_fee_currency_model=receipt.get('assumed_fee_currency_for_research'),
            marked_execution_cost_usd=decision.get('trading_cost_mark_usd'),
            classification='ALTERNATIVE_OR_SEQUENTIAL_INTENT_DO_NOT_SUM_AS_EXECUTED_COST'))
    return dict(monitoring_outcome='COMPLETE_168_VALID_HOURS' if progress['state']=='COMPLETE' else 'IN_PROGRESS',
        strategy_evidence=evidence,opportunity_history='COMPLETE_SINCE_TRIAL_START' if full else 'SINCE_UPGRADE' if m else 'UNINSTRUMENTED',
        metrics_since_at=None if m is None else m['since_at'],evaluations=0 if m is None else m['evaluations'],
        direction_checks=0 if m is None else m['direction_checks'],qualifying_checks=0 if m is None else m['qualifying_checks'],
        opportunity_episodes=episodes,
        realistically_fillable_count=0 if full and episodes==0 else None,
        fill_feasibility='NO_QUALIFIED_OPPORTUNITIES' if full and episodes==0 else 'UNKNOWN_NO_CALIBRATED_MAKER_MODEL',
        feasibility_unknown_opportunities=episodes,replay_fill_events=len(settled),
        replay_filled_orders=len({f['reference'] for f in settled}),unsettled_fill_events=len(unsettled),
        retired_without_fill=sum(o['state'] in ('CANCELED','REJECTED') and o['filled']==0 for o in orders),
        partial_orders=sum(0<o['filled']<o['size'] for o in orders),
        modeled_fees_native=fees,modeled_costs_complete=not unreconciled,
        proposed_full_fill_costs=proposals,portfolio_vs_hold=benchmark,net_marked_outperformance_usd=difference,
        valuation_at=state['last_review'],liquidation_comparison='UNKNOWN_NATIVE_USD_EXIT_RULES_DEPTH_AND_FEE_UNITS',
        predictive_edge='NOT_DEMONSTRATED',realized_profit='NOT_ASSESSED')
