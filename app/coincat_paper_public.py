"""Frozen legacy paper public schema; no automatic controller import."""
PUBLIC_COUNTS=('orders','fills','non_fills','partials','gaps','enabled_views','reviews',
    'settings_version','completed_rotations','qualifying_rotations')
PUBLIC_STATES=('OFF','ACTIVE','PAUSED','RECONCILIATION_REQUIRED','EXPIRED','UNAVAILABLE','WAITING_FOR_FRAME')
POLICY='PATIENT_MAKER_ETH_V1'
POLICIES=(POLICY,'SHORT_LIVED_ETH_V1')
MODELS=('NO_FILL_V1','CONSERVATIVE_STRESS_V1','PARTIAL_SCARCE_V1','ADVERSE_SLOW_V1')
GLOBAL_POLICY='GLOBAL_USD_ROTATION_V1'

def public_status(value=None):
    value=value if isinstance(value,dict) else {}
    out={k:value.get(k,0) if type(value.get(k,0)) is int and 0<=value.get(k,0)<=1000000000 else 0 for k in PUBLIC_COUNTS}
    out.update(state=value.get('state') if value.get('state') in PUBLIC_STATES else 'OFF',
        model=value.get('model') if value.get('model') in MODELS else 'UNOBSERVED',
        policy=value.get('policy') if value.get('policy') in POLICIES+(GLOBAL_POLICY,) else POLICY,
        provider='SEEDED_BBO_STRESS_NOT_EXCHANGE_MATCHING',classification='SIMULATED_ASSUMPTION',
        valuation=value.get('valuation') if value.get('valuation') in ('PAPER_ETH_CASH','UNKNOWN') else 'UNKNOWN',
        actual_profit='NOT_ESTABLISHED',edge='NO_DEMONSTRATED_EDGE',live_permission=False)
    return out


def validate_public(value):
    current=set(public_status());legacy=current-{'settings_version','completed_rotations','qualifying_rotations'}
    if not isinstance(value,dict) or set(value) not in (current,legacy):
        raise ValueError('INVALID_AUTO_PAPER_PUBLIC_SCHEMA')
    if value.get('policy')==GLOBAL_POLICY and set(value)!=current:raise ValueError('INVALID_AUTO_PAPER_PUBLIC_SCHEMA')
    expected=public_status(value)
    if value!={key:expected[key] for key in value}:raise ValueError('INVALID_AUTO_PAPER_PUBLIC_SCHEMA')
    if any(type(value[k]) is not int for k in PUBLIC_COUNTS if k in value):raise ValueError('INVALID_AUTO_PAPER_PUBLIC_COUNT')
    if type(value['live_permission']) is not bool:raise ValueError('INVALID_AUTO_PAPER_PUBLIC_PERMISSION')
    return value
