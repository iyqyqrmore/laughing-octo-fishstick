"""Quantity-free assumed-fill status. Never merge with trial or real fills."""
STATES={'OFF','PAUSED','WAITING','RUNNING','COMPLETE','REVIEW_REQUIRED'}
COUNTS=('waves','orders','buys','sells','maker_orders','taker_orders','valid_seconds','restart_count')
FIXED=dict(provider='EXPLICIT_ASSUMED_FILL_SANDBOX',live_permission=False,
    fill_evidence='ASSUMED_NOT_OBSERVED',profit_evidence='NOT_ESTABLISHED')

def project(value=None):
    value=value or {}
    return dict(state=value.get('state') if value.get('state') in STATES else 'OFF',**FIXED,
        **{k:value.get(k,0) if type(value.get(k,0)) is int and value.get(k,0)>=0 else 0 for k in COUNTS})

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(project()) or value!=project(value):raise ValueError('INVALID_ASSUMED_PUBLIC_SCHEMA')
    if type(value['live_permission']) is not bool or any(type(value[k]) is not int for k in COUNTS):raise ValueError('INVALID_ASSUMED_PUBLIC_TYPE')
    if value['orders']!=value['buys']+value['sells'] or value['orders']!=value['maker_orders']+value['taker_orders']:
        raise ValueError('INVALID_ASSUMED_PUBLIC_TOTALS')
    if value['valid_seconds']>604800:raise ValueError('INVALID_ASSUMED_TRIAL_TIME')
    if value['state']=='COMPLETE' and value['valid_seconds']!=604800:raise ValueError('INVALID_ASSUMED_TRIAL_COMPLETION')
    return value
