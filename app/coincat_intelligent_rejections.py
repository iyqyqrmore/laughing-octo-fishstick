"""Fixed v1.05 reasons/categories; no portfolio values or exception text leave."""
from copy import deepcopy

GROUPS={
    'DATA_UNAVAILABLE':('INTELLIGENT_INPUTS_UNVERIFIED','PARTIAL_OR_UNVERIFIED_INPUTS','INTELLIGENT_REFERENCES_ASYNCHRONOUS',
        'INTELLIGENT_NATIVE_REFERENCE_CONFLICT','SHADOW_BOOK_MISSING_OR_STALE','SHADOW_VALUATION_DECISION_SPAN_EXCEEDS_12S',
        'FORECAST_HISTORY_UNAVAILABLE','FORECAST_HISTORY_INVALID','FORECAST_HISTORY_STALE','FORECAST_HISTORY_GAP',
        'FORECAST_HORIZON_OR_FRESHNESS_INVALID','FORECAST_ESTIMATE_UNVERIFIED'),
    'INSUFFICIENT_HISTORY':('FORECAST_HISTORY_INSUFFICIENT','FORECAST_TRAINING_INSUFFICIENT','FORECAST_VALIDATION_INSUFFICIENT'),
    'FEES':('FRESH_AUTHENTICATED_MAKER_FEE_REQUIRED','ENTRY_FEE_REMOVES_ADVANTAGE'),
    'FORECAST_UNCERTAINTY':('FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE','FORECAST_FEATURE_OUT_OF_DISTRIBUTION','FORECAST_RETURN_OUTLIER','FORECAST_CURRENT_PRICE_SHOCK'),
    'NATIVE_RULES':('PRODUCT_NOT_TRADABLE_WITH_THIS_ACCOUNT','PRODUCT_NOT_ACCEPTING_ORDERS','PRODUCT_CURRENCY_CONFLICT',
        'PRODUCT_SIZE_RULES_UNAVAILABLE','PRODUCT_PRICE_TICK_UNAVAILABLE','INTELLIGENT_NATIVE_SIZE_INVALID',
        'USE_EXACT_NATIVE_SIZE_AND_PRICE_INCREMENTS','ORDER_OUTSIDE_EXCHANGE_NATIVE_MINIMUM_OR_MAXIMUM',
        'POST_ONLY_PRICE_WOULD_TAKE_USE_BID_FOR_BUY_OR_ASK_FOR_SELL','NO_NONCROSSING_MAKER_PRICE','EXCHANGE_REQUIRES_POST_ONLY'),
    'LIQUIDITY':('SIZED_NATIVE_DEPTH_INSUFFICIENT','SIZED_NATIVE_DEPTH_UNAVAILABLE','SHADOW_BOOK_CROSSED_OR_WIDE'),
    'SOURCE_FUNDS':('NO_SHADOW_SOURCE_FUNDS','INTELLIGENT_SOURCE_FUNDS_OR_FRACTION','INTELLIGENT_MINIMUM_EXCEEDS_JUSTIFIED_FUNDS'),
    'RISK':('INTELLIGENT_CONCENTRATION_LIMIT','PORTFOLIO_RISK_REMOVES_ADVANTAGE','RISK_COVARIANCE_NOT_POSITIVE_SEMIDEFINITE'),
    'INSUFFICIENT_ADVANTAGE':('INSUFFICIENT_24H_EXPECTED_ADVANTAGE',),
    'OTHER':('OTHER_UNCLASSIFIED',)}
REASON_CATEGORY={r:k for k,rows in GROUPS.items() for r in rows}

def empty():return dict.fromkeys(GROUPS,0)
def record(metrics,rows):
    if 'rejection_detail' not in metrics:metrics['rejection_detail']=dict(schema=105,counts=empty())
    for row in rows:
        if row['state']!='QUALIFIED':metrics['rejection_detail']['counts'][REASON_CATEGORY.get(row.get('reason'),'OTHER')]+=1
def validate_detail(value,total):
    if (not isinstance(value,dict) or set(value)!={'schema','counts'} or type(value['schema']) is not int or value['schema']!=105 or
            not isinstance(value['counts'],dict) or set(value['counts'])!=set(GROUPS) or
            any(type(n) is not int or not 0<=n<=2**53 for n in value['counts'].values()) or sum(value['counts'].values())!=total):
        raise ValueError('INVALID_INTELLIGENT_REJECTION_COUNTS')
    return value
def summary(metrics):
    total=metrics.get('rejected_checks',0);value=metrics.get('rejection_detail',dict(schema=105,counts=empty()))
    validate_detail(value,total)
    reasons=dict.fromkeys(REASON_CATEGORY,0)
    for code,n in metrics.get('rejections',{}).items():reasons[code if code in REASON_CATEGORY else 'OTHER_UNCLASSIFIED']+=n
    result=dict(schema='intelligent-rejections/v1',total=total,categories=deepcopy(value['counts']),reasons=reasons)
    return validate_public(result,total)
def validate_public(value,total):
    if (not isinstance(value,dict) or set(value)!={'schema','total','categories','reasons'} or value['schema']!='intelligent-rejections/v1' or
            type(value['total']) is not int or value['total']!=total):raise ValueError('INVALID_INTELLIGENT_REJECTION_PUBLIC')
    for key,allowed in (('categories',set(GROUPS)),('reasons',set(REASON_CATEGORY))):
        if (not isinstance(value[key],dict) or set(value[key])!=allowed or
                any(type(n) is not int or not 0<=n<=2**53 for n in value[key].values()) or sum(value[key].values())!=total):
            raise ValueError('INVALID_INTELLIGENT_REJECTION_PUBLIC_COUNTS')
    return value
