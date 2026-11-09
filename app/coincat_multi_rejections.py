"""Separate fixed reason catalog for the multi-horizon policy, never raw errors."""
from copy import deepcopy
from coincat_intelligent_rejections import GROUPS as BASE_GROUPS
from coincat_horizon_forecast import HORIZONS

GROUPS=deepcopy(BASE_GROUPS)
GROUPS['DATA_UNAVAILABLE']+=('HORIZON_INPUTS_UNVERIFIED','HORIZON_DATA_UNAVAILABLE','HORIZON_HISTORY_INVALID','HORIZON_HISTORY_GAP',
    'HORIZON_HISTORY_STALE','HORIZON_FORECAST_INVALID_OR_STALE','HORIZON_HISTORY_REVIEW_REQUIRED','FORECAST_HISTORY_REVIEW_REQUIRED')
GROUPS['INSUFFICIENT_HISTORY']+=('HORIZON_HISTORY_INSUFFICIENT','HORIZON_TRAINING_INSUFFICIENT','HORIZON_VALIDATION_INSUFFICIENT')
GROUPS['FORECAST_UNCERTAINTY']+=('HORIZON_FEATURE_OUT_OF_DISTRIBUTION','HORIZON_RETURN_OUTLIER')
GROUPS['INSUFFICIENT_ADVANTAGE']+=('INSUFFICIENT_HORIZON_EXPECTED_ADVANTAGE','IMMEDIATE_AFTER_FEE_MARK_NOT_POSITIVE','NO_SUPPORTED_HORIZON')
REASONS={r:k for k,rs in GROUPS.items() for r in rs}

def empty():return dict(schema='multi-rejections/v1',total=0,categories=dict.fromkeys(GROUPS,0),reasons=dict.fromkeys(REASONS,0))
def add(result,reason):
    code=reason if reason in REASONS else 'OTHER_UNCLASSIFIED';result['total']+=1;result['reasons'][code]+=1;result['categories'][REASONS[code]]+=1
def record(metrics,rows):
    if 'rejection_detail' not in metrics:metrics['rejection_detail']=dict(summary=empty(),horizons={n:dict(checks=0,qualified=0,rejections=empty()) for n in HORIZONS})
    detail=metrics['rejection_detail']
    for row in rows:
        if row['state']!='QUALIFIED':add(detail['summary'],row['reason'])
        for name in HORIZONS:
            item=row.get('horizons',{}).get(name,row);counts=detail['horizons'][name];counts['checks']+=1
            if item['state']=='QUALIFIED':counts['qualified']+=1
            else:add(counts['rejections'],item['reason'])
def validate_summary(value,total):
    if (not isinstance(value,dict) or set(value)!={'schema','total','categories','reasons'} or value['schema']!='multi-rejections/v1' or
            type(value['total']) is not int or value['total']!=total):raise ValueError('MULTI_REJECTION_SCHEMA')
    for key,allowed in (('categories',set(GROUPS)),('reasons',set(REASONS))):
        if (not isinstance(value[key],dict) or set(value[key])!=allowed or any(type(v) is not int or not 0<=v<=2**53 for v in value[key].values()) or
                sum(value[key].values())!=total):raise ValueError('MULTI_REJECTION_TOTALS')
    return value
def validate_detail(value,total):
    if not isinstance(value,dict) or set(value)!={'summary','horizons'} or set(value['horizons'])!=set(HORIZONS):raise ValueError('MULTI_REJECTION_HORIZONS')
    validate_summary(value['summary'],total)
    for row in value['horizons'].values():
        if set(row)!={'checks','qualified','rejections'} or any(type(row[k]) is not int or row[k]<0 for k in ('checks','qualified')) or row['qualified']>row['checks']:
            raise ValueError('MULTI_REJECTION_HORIZON_COUNT')
        validate_summary(row['rejections'],row['checks']-row['qualified'])
    return value
def summary(metrics):return deepcopy(metrics.get('rejection_detail',dict(summary=empty()))['summary'])
