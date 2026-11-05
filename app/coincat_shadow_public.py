"""Strict aggregate trial status; no balances, valuations, paths or identities."""
STATES={'OFF','PAUSED','RUNNING','DISCONNECTED','RECOVERING','COMPLETE','REVIEW_REQUIRED'}
COUNTS=('reviews','orders','fills','unresolved','valid_seconds','restart_count')
KEYS={'state','provider','live_permission','objective','forecast','actual_profit','coverage_percent',*COUNTS}
ECOUNTS=('evaluations','direction_checks','qualifying_checks','replay_fill_events','replay_filled_orders','retired_without_fill')
HISTORIES={'COMPLETE_SINCE_TRIAL_START','SINCE_UPGRADE','UNINSTRUMENTED'}
STRATEGY={'UNPROVEN_UNRECONCILED_OUTCOMES','UNPROVEN_INCOMPLETE_OPPORTUNITY_HISTORY',
    'UNPROVEN_NO_QUALIFYING_TRADES','UNPROVEN_NO_SIMULATED_FILLS','UNPROVEN_EXPLICIT_REPLAY_ONLY'}
BENCHMARKS={'UNKNOWN','ABOVE_AS_MARKED','BELOW_AS_MARKED','EQUAL_AS_MARKED'}

def evidence_project(raw=None):
    raw=raw if isinstance(raw,dict) else {};episodes=raw.get('opportunity_episodes')
    episodes=episodes if type(episodes) is int and 0<=episodes<=1000000000 else None
    history=raw.get('opportunity_history') if raw.get('opportunity_history') in HISTORIES else 'UNINSTRUMENTED'
    none_qualified=history=='COMPLETE_SINCE_TRIAL_START' and episodes==0
    return dict(**{k:raw.get(k,0) if type(raw.get(k,0)) is int and 0<=raw.get(k,0)<=1000000000 else 0 for k in ECOUNTS},
        opportunity_episodes=episodes,opportunity_history=history,
        realistically_fillable_count=0 if none_qualified else None,
        fill_feasibility='NO_QUALIFIED_OPPORTUNITIES' if none_qualified else 'UNKNOWN_NO_CALIBRATED_MAKER_MODEL',
        monitoring_outcome='COMPLETE_168_VALID_HOURS' if raw.get('monitoring_outcome')=='COMPLETE_168_VALID_HOURS' else 'IN_PROGRESS',
        strategy_evidence=raw.get('strategy_evidence') if raw.get('strategy_evidence') in STRATEGY else 'UNPROVEN_INCOMPLETE_OPPORTUNITY_HISTORY',
        portfolio_vs_hold=raw.get('portfolio_vs_hold') if raw.get('portfolio_vs_hold') in BENCHMARKS else 'UNKNOWN')

def project(value=None):
    value=value or {};coverage=value.get('coverage_percent',0)
    result=dict(state=value.get('state') if value.get('state') in STATES else 'OFF',
        provider='READ_ONLY_SHADOW_WITH_EXPLICIT_REPLAY',live_permission=False,
        objective='RISK_ADJUSTED_USD_VS_ORIGINAL_HOLD',
        **{k:value.get(k,0) if type(value.get(k,0)) is int and 0<=value.get(k,0)<=1000000 else 0 for k in COUNTS},
        coverage_percent=coverage if type(coverage) in (int,float) and 0<=coverage<=100 else 0,
        forecast='UNVALIDATED',actual_profit='NOT_ASSESSED')
    if 'evidence' in value:result['evidence']=evidence_project(value['evidence'])
    return result

def validate(value):
    if not isinstance(value,dict) or set(value) not in (KEYS,KEYS|{'evidence'}) or value!=project(value):raise ValueError('INVALID_SHADOW_PUBLIC_SCHEMA')
    if type(value['live_permission']) is not bool:raise ValueError('INVALID_SHADOW_PUBLIC_AUTHORITY')
    for k in COUNTS:
        if type(value[k]) is not int:raise ValueError('INVALID_SHADOW_PUBLIC_COUNT')
    if type(value['coverage_percent']) not in (int,float):raise ValueError('INVALID_TRIAL_COVERAGE_TYPE')
    if value['valid_seconds']>604800:raise ValueError('INVALID_TRIAL_VALID_TIME')
    if 'evidence' in value:
        e=value['evidence']
        if not isinstance(e,dict) or set(e)!=set(evidence_project()) or e!=evidence_project(e):raise ValueError('INVALID_TRIAL_EVIDENCE_PUBLIC_SCHEMA')
        if any(type(e[k]) is not int for k in ECOUNTS):raise ValueError('INVALID_TRIAL_EVIDENCE_PUBLIC_COUNT')
        if e['opportunity_episodes'] is not None and type(e['opportunity_episodes']) is not int:raise ValueError('INVALID_OPPORTUNITY_COUNT')
        if e['realistically_fillable_count'] is not None and type(e['realistically_fillable_count']) is not int:raise ValueError('INVALID_REALISTIC_FILL_COUNT')
        if e['direction_checks']!=14*e['evaluations'] or not 0<=e['qualifying_checks']<=e['direction_checks']:raise ValueError('INVALID_TRIAL_EVIDENCE_PUBLIC_TOTALS')
        if e['opportunity_episodes'] is not None and not 0<=e['opportunity_episodes']<=e['qualifying_checks']:raise ValueError('INVALID_OPPORTUNITY_EPISODES')
    return value
