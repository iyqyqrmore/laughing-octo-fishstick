"""Strict aggregate trial status; no balances, valuations, paths or identities."""
STATES={'OFF','PAUSED','RUNNING','DISCONNECTED','RECOVERING','COMPLETE','REVIEW_REQUIRED'}
COUNTS=('reviews','orders','fills','unresolved','valid_seconds','restart_count')
KEYS={'state','provider','live_permission','objective','forecast','actual_profit','coverage_percent',*COUNTS}

def project(value=None):
    value=value or {};coverage=value.get('coverage_percent',0)
    return dict(state=value.get('state') if value.get('state') in STATES else 'OFF',
        provider='READ_ONLY_SHADOW_WITH_EXPLICIT_REPLAY',live_permission=False,
        objective='RISK_ADJUSTED_USD_VS_ORIGINAL_HOLD',
        **{k:value.get(k,0) if type(value.get(k,0)) is int and 0<=value.get(k,0)<=1000000 else 0 for k in COUNTS},
        coverage_percent=coverage if type(coverage) in (int,float) and 0<=coverage<=100 else 0,
        forecast='UNVALIDATED',actual_profit='NOT_ASSESSED')

def validate(value):
    if not isinstance(value,dict) or set(value)!=KEYS or value!=project(value):raise ValueError('INVALID_SHADOW_PUBLIC_SCHEMA')
    if type(value['live_permission']) is not bool:raise ValueError('INVALID_SHADOW_PUBLIC_AUTHORITY')
    for k in COUNTS:
        if type(value[k]) is not int:raise ValueError('INVALID_SHADOW_PUBLIC_COUNT')
    if type(value['coverage_percent']) not in (int,float):raise ValueError('INVALID_TRIAL_COVERAGE_TYPE')
    if value['valid_seconds']>604800:raise ValueError('INVALID_TRIAL_VALID_TIME')
    return value
