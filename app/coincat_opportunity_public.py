"""Strict quantity-free opportunity-policy diagnostics, distinct from arithmetic."""
STATES={'OFF','WAITING','RECOVERING','ACTIVE','PAUSED','REVIEW_REQUIRED','FINALIZING','COMPLETE'}
ORDERS={'NONE','NEW','OPEN','PARTIAL','CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'}
COUNTS=('reviews','direction_checks','qualified_checks','rejected_checks','opportunity_episodes','orders','fill_events',
    'modeled_fills','replay_fills','partials','canceled','nonfills','replacements','gaps','unknown_events','valid_seconds','restart_count')
FIXED=dict(provider='OPPORTUNITY_SHADOW_NO_LIVE_AUTHORITY',live_permission=False,
    forecast='UNVALIDATED',fill_evidence='CONDITIONAL_NOT_CALIBRATED',profit='NOT_ESTABLISHED')

def project(value=None):
    value=value or {}
    return dict(state=value.get('state') if value.get('state') in STATES else 'OFF',
        order_state=value.get('order_state') if value.get('order_state') in ORDERS else 'NONE',**FIXED,
        **{k:value.get(k,0) if type(value.get(k,0)) is int and value.get(k,0)>=0 else 0 for k in COUNTS})

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(project()) or value!=project(value):raise ValueError('INVALID_OPPORTUNITY_PUBLIC_SCHEMA')
    if type(value['live_permission']) is not bool or any(type(value[k]) is not int for k in COUNTS):raise ValueError('INVALID_OPPORTUNITY_PUBLIC_TYPES')
    if (value['direction_checks']!=14*value['reviews'] or value['qualified_checks']+value['rejected_checks']!=value['direction_checks'] or
            value['modeled_fills']+value['replay_fills']!=value['fill_events'] or value['valid_seconds']>604800 or
            value['state']=='COMPLETE' and (value['valid_seconds']!=604800 or value['order_state']!='NONE')):
        raise ValueError('INVALID_OPPORTUNITY_PUBLIC_TOTALS')
    return value
