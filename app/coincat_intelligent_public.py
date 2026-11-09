"""Strict versioned v1.05 shadow facts. No prices, positions or policy values."""
from copy import deepcopy
from coincat_version import DISPLAY
from coincat_intelligent_rejections import validate_public as validate_rejections

POLICY='INTELLIGENT_ONE_LEG_24H_V1'
STATES={'OFF','WAITING','RECOVERING','ACTIVE','PAUSED','REVIEW_REQUIRED','FINALIZING','COMPLETE'}
ORDER_STATES={'NONE','NEW','OPEN','PARTIAL','CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'}
COUNTS=('reviews','direction_checks','qualified_checks','rejected_checks','opportunity_episodes','orders','fill_events',
    'modeled_fills','replay_fills','partials','canceled','nonfills','replacements','gaps','unknown_events','valid_seconds','restart_count',
    'active_orders','unresolved_orders','market_coverage','valuation_coverage','history_observations','history_required','history_references','validation_predictions','holdout_predictions',
    'forward_predictions','forward_known','forward_unknown','forward_direction_checks','forward_direction_matches')
FIXED=dict(version=DISPLAY,selected_policy=POLICY,horizon_s=86400,live_order_authority=False,
    forecast_validation='UNVALIDATED_RESEARCH_ESTIMATE',execution_calibration='CONDITIONAL_NOT_CALIBRATED',
    execution_evidence='CONDITIONAL_SHADOW_NOT_EXCHANGE_FILLS',profit='NOT_ESTABLISHED',
    forward_sample='OVERLAPPING_24H_FORECASTS_NOT_INDEPENDENT')
DATA={'UNOBSERVED','FRESH','PARTIAL','STALE'}
HISTORY={'NOT_READY','READY','STALE','GAP','REVIEW_REQUIRED'}

def project(value):
    result=dict(**FIXED,state=value.get('state','OFF'),order_state=value.get('order_state','NONE'),
        data_state=value.get('data_state','UNOBSERVED'),history_state=value.get('history_state','NOT_READY'),
        **{k:value.get(k,0) for k in COUNTS},rejection_breakdown=deepcopy(value['rejection_breakdown']))
    return validate(result)

def validate(value):
    expected=set(FIXED)|set(COUNTS)|{'state','order_state','data_state','history_state','rejection_breakdown'}
    if not isinstance(value,dict) or set(value)!=expected:raise ValueError('INVALID_INTELLIGENT_PUBLIC_KEYS')
    for key,constant in FIXED.items():
        if type(value[key]) is not type(constant) or value[key]!=constant:raise ValueError('INVALID_INTELLIGENT_PUBLIC_IDENTITY')
    for key,allowed in (('state',STATES),('order_state',ORDER_STATES),('data_state',DATA),('history_state',HISTORY)):
        if not isinstance(value[key],str) or value[key] not in allowed:raise ValueError('INVALID_INTELLIGENT_PUBLIC_STATE')
    if any(type(value[k]) is not int or not 0<=value[k]<=2**53 for k in COUNTS):raise ValueError('INVALID_INTELLIGENT_PUBLIC_COUNT')
    if (value['direction_checks']!=14*value['reviews'] or value['rejected_checks']+value['qualified_checks']!=value['direction_checks'] or
            value['modeled_fills']+value['replay_fills']!=value['fill_events'] or value['valid_seconds']>604800 or
            value['active_orders']>1 or value['unresolved_orders']>value['active_orders'] or value['history_references']>5 or
            value['market_coverage']>7 or value['valuation_coverage']>5 or
            value['forward_known']+value['forward_unknown']>value['forward_predictions'] or
            value['forward_direction_matches']>value['forward_direction_checks'] or
            value['state']=='COMPLETE' and (value['valid_seconds']!=604800 or value['active_orders'])):
        raise ValueError('INVALID_INTELLIGENT_PUBLIC_TOTALS')
    validate_rejections(value['rejection_breakdown'],value['rejected_checks']);return value
