"""Amount-free multi-horizon facts; every nested key is strictly allowlisted."""
from copy import deepcopy
from coincat_horizon_forecast import HORIZONS
from coincat_intelligent_public import STATES,ORDER_STATES,DATA
from coincat_maker_shadow import COUNTERS
from coincat_multi_policy import POLICY
from coincat_multi_rejections import validate_summary,empty,REASONS
from coincat_version import DISPLAY

FIXED=dict(version=DISPLAY,selected_policy=POLICY,live_order_authority=False,profit='NOT_ESTABLISHED',
    forecast_validation='UNVALIDATED_RESEARCH_ESTIMATE',execution_calibration='CONDITIONAL_NOT_CALIBRATED',
    execution_evidence='CONDITIONAL_SHADOW_NOT_EXCHANGE_FILLS',selection_validation='EXPLORATORY_MULTIPLICITY_NOT_CALIBRATED',
    comparison='INDEPENDENT_LIVE_TRIAL_NOT_PAIRED',forward_sample='OVERLAPPING_HORIZONS_NOT_INDEPENDENT')
COUNTS=tuple(COUNTERS)+('valid_seconds','restart_count','market_coverage','valuation_coverage','active_orders','unresolved_orders','order_active_reviews','unknown_events_blocking')
HCOUNTS=('checks','qualified','rejected','selected_orders','validation_predictions','holdout_predictions','forward_predictions','forward_known','forward_unknown','direction_checks','direction_matches')

def validate(value):
    if not isinstance(value,dict) or set(value)!=set(FIXED)|set(COUNTS)|{'state','order_state','data_state','horizons','rejection_breakdown'}:raise ValueError('MULTI_PUBLIC_KEYS')
    for key,constant in FIXED.items():
        if type(value[key]) is not type(constant) or value[key]!=constant:raise ValueError('MULTI_PUBLIC_IDENTITY')
    for key,allowed in (('state',STATES),('order_state',ORDER_STATES),('data_state',DATA)):
        if not isinstance(value[key],str) or value[key] not in allowed:raise ValueError('MULTI_PUBLIC_STATE')
    if any(type(value[k]) is not int or not 0<=value[k]<=2**53 for k in COUNTS):raise ValueError('MULTI_PUBLIC_COUNT')
    if (value['direction_checks']!=14*value['reviews'] or value['qualified_checks']+value['rejected_checks']!=value['direction_checks'] or
            value['modeled_fills']+value['replay_fills']!=value['fill_events'] or value['valid_seconds']>604800 or
            value['market_coverage']>7 or value['valuation_coverage']>5 or value['active_orders']>1 or value['unresolved_orders']>value['active_orders'] or
            value['state']=='COMPLETE' and (value['valid_seconds']!=604800 or value['active_orders'])):raise ValueError('MULTI_PUBLIC_TOTALS')
    validate_summary(value['rejection_breakdown'],value['rejected_checks'])
    if not isinstance(value['horizons'],dict) or set(value['horizons'])!=set(HORIZONS):raise ValueError('MULTI_PUBLIC_HORIZONS')
    for name,row in value['horizons'].items():
        if not isinstance(row,dict) or set(row)!=set(HCOUNTS)|{'horizon_s','state','reason','rejections'}:raise ValueError('MULTI_PUBLIC_HORIZON_KEYS')
        if (type(row['horizon_s']) is not int or row['horizon_s']!=HORIZONS[name] or not isinstance(row['state'],str) or row['state'] not in ('UNOBSERVED','READY','HOLD') or
                not isinstance(row['reason'],str) or row['reason'] not in set(REASONS)|{'READY','UNOBSERVED'}):raise ValueError('MULTI_PUBLIC_HORIZON_STATE')
        if any(type(row[k]) is not int or not 0<=row[k]<=2**53 for k in HCOUNTS):raise ValueError('MULTI_PUBLIC_HORIZON_COUNT')
        if (row['checks']!=14*value['reviews'] or row['qualified']+row['rejected']!=row['checks'] or
                row['forward_known']+row['forward_unknown']>row['forward_predictions'] or row['direction_matches']>row['direction_checks']):raise ValueError('MULTI_PUBLIC_HORIZON_TOTALS')
        validate_summary(row['rejections'],row['rejected'])
    if sum(r['selected_orders'] for r in value['horizons'].values())!=value['orders']:raise ValueError('MULTI_PUBLIC_SELECTION_COUNTS')
    return value

def project(value,horizons):
    result=dict(**FIXED,**{k:value.get(k,0) for k in COUNTS},state=value.get('state','OFF'),order_state=value.get('order_state','NONE'),
        data_state=value.get('data_state','UNOBSERVED'),rejection_breakdown=deepcopy(value.get('rejection_breakdown',empty())),horizons=deepcopy(horizons))
    return validate(result)
