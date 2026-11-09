"""Observational rejection counts only; never admission rules or financial data."""
from copy import deepcopy

from coincat_execution_limits import native_math
from coincat_v80_immediate import exact

SCHEMA='opportunity-rejections/v1'
MAX_COUNT=2**53
REASON_GROUPS={
    'UNAVAILABLE_DATA':(
        'PARTIAL_OR_UNVERIFIED_INPUTS','UNVERIFIED_OPPORTUNITY_INPUTS','SHADOW_BOOK_MISSING_OR_STALE',
        'SHADOW_VALUATION_DECISION_SPAN_EXCEEDS_12S','OPPORTUNITY_DECISION_SPAN_EXCEEDS_12_SECONDS',
        'NATIVE_BOOK_USD_REFERENCE_CONFLICT','FRESH_AUTHENTICATED_MAKER_FEE_REQUIRED',
        'FRESH_AUTHENTICATED_TAKER_FEE_REQUIRED','NATIVE_PRODUCT_RULES_UNAVAILABLE',
        'PRODUCT_SIZE_RULES_UNAVAILABLE','PRODUCT_PRICE_TICK_UNAVAILABLE',
        'SIZED_NATIVE_DEPTH_UNAVAILABLE','SIZED_FUTURE_EXIT_COST_UNKNOWN'),
    'INSUFFICIENT_EXPECTED_ADVANTAGE':(),
    'LIQUIDITY_LIMITATION':('SIZED_NATIVE_DEPTH_INSUFFICIENT',),
    'UNCERTAINTY':('RISK_RETURN_OUTLIER_REVIEW_REQUIRED','RISK_COVARIANCE_NOT_POSITIVE_SEMIDEFINITE'),
    'MODEL_WARMUP':('WARMING_RISK_OBSERVATIONS_HOLD','WARMING_AFTER_RISK_OBSERVATION_GAP_HOLD','RISK_OBSERVATION_GAP_HOLD'),
    'MARKET_RULES_OR_FUNDING':(
        'NO_FUNDED_UNRESERVED_OPPORTUNITY_SOURCE','INSUFFICIENT_SIMULATED_SOURCE_INCLUDING_NATIVE_FEE',
        'PRODUCT_NOT_TRADABLE_WITH_THIS_ACCOUNT','PRODUCT_NOT_ACCEPTING_ORDERS','PRODUCT_CURRENCY_CONFLICT',
        'USE_EXACT_NATIVE_SIZE_AND_PRICE_INCREMENTS','ORDER_OUTSIDE_EXCHANGE_NATIVE_MINIMUM_OR_MAXIMUM',
        'EXCHANGE_REQUIRES_POST_ONLY','POST_ONLY_PRICE_WOULD_TAKE_USE_BID_FOR_BUY_OR_ASK_FOR_SELL',
        'NO_NONCROSSING_MAKER_PRICE','OPPORTUNITY_REMAINING_SIZE_INVALID'),
    'SPREAD_OR_CROSSED_BOOK':('SHADOW_BOOK_CROSSED_OR_WIDE',),
    'ADVANTAGE_OR_UNCERTAINTY_UNSPLIT':('NO_COST_RISK_JUSTIFIED_ADVANTAGE',),
    'OTHER_OR_UNCLASSIFIED':('OTHER_UNCLASSIFIED','UNRECORDED_HISTORY')}
CATEGORIES=tuple(REASON_GROUPS)
REASON_CATEGORY={r:c for c,reasons in REASON_GROUPS.items() for r in reasons}
REASONS=tuple(REASON_CATEGORY)
LABELS=dict(UNAVAILABLE_DATA='Unavailable or unverified data',
    INSUFFICIENT_EXPECTED_ADVANTAGE='Insufficient expected advantage after costs and risk',
    LIQUIDITY_LIMITATION='Insufficient sized liquidity',UNCERTAINTY='Uncertainty blocks admission',
    MODEL_WARMUP='Model warmup or observation gap',MARKET_RULES_OR_FUNDING='Market rules or funded inventory',
    SPREAD_OR_CROSSED_BOOK='Spread limit or crossed book',
    ADVANTAGE_OR_UNCERTAINTY_UNSPLIT='Advantage / uncertainty not separately recorded',
    OTHER_OR_UNCLASSIFIED='Other or unrecorded history')
COVERAGE={'COMPLETE_SINCE_TRIAL_START','SPLIT_SINCE_UPGRADE','LEGACY_AGGREGATES_ONLY'}

def count(value):return type(value) is int and 0<=value<=MAX_COUNT
def empty(keys):return dict.fromkeys(keys,0)

@native_math
def category(row):
    reason=row.get('reason')
    if not isinstance(reason,str):return 'OTHER_OR_UNCLASSIFIED'
    if reason=='NO_COST_RISK_JUSTIFIED_ADVANTAGE':
        try:
            edge,forecast,execution=(exact(row[k]) for k in ('projected_advantage_usd','forecast_uncertainty_usd','execution_uncertainty_usd'))
            if edge>0 or forecast<0 or execution<0:raise ValueError()
            # Existing projected advantage already includes entry fees, risk and
            # future exit estimates. This only identifies a binding allowance;
            # it never recomputes or relaxes the admission decision.
            return 'UNCERTAINTY' if edge+forecast+execution>0 else 'INSUFFICIENT_EXPECTED_ADVANTAGE'
        except (ValueError,TypeError,KeyError,ArithmeticError):return 'ADVANTAGE_OR_UNCERTAINTY_UNSPLIT'
    return REASON_CATEGORY.get(reason,'OTHER_OR_UNCLASSIFIED')

def histogram(metrics):
    total=metrics.get('rejected_checks',0);raw=metrics.get('rejections',{});result=empty(REASONS)
    if not count(total):raise ValueError('INVALID_REJECTION_TOTAL')
    if not isinstance(raw,dict) or any(not count(n) for n in raw.values()) or sum(raw.values())>total:
        result['UNRECORDED_HISTORY']=total;return result
    for reason,n in raw.items():result[reason if reason in REASON_CATEGORY else 'OTHER_UNCLASSIFIED']+=n
    result['UNRECORDED_HISTORY']=total-sum(result.values());return result

def legacy_categories(reasons):
    result=empty(CATEGORIES)
    for reason,n in reasons.items():result[REASON_CATEGORY[reason]]+=n
    return result

def validate_detail(detail,total):
    if (not isinstance(detail,dict) or set(detail)!={'schema','baseline_rejected_checks','baseline_categories','counts'} or
            type(detail['schema']) is not int or detail['schema']!=1 or not count(detail['baseline_rejected_checks'])):
        raise ValueError('INVALID_REJECTION_DETAIL_SCHEMA')
    for field in ('baseline_categories','counts'):
        if not isinstance(detail[field],dict) or set(detail[field])!=set(CATEGORIES) or any(not count(n) for n in detail[field].values()):
            raise ValueError('INVALID_REJECTION_DETAIL_COUNTS')
    if (sum(detail['baseline_categories'].values())!=detail['baseline_rejected_checks'] or
            detail['baseline_rejected_checks']+sum(detail['counts'].values())!=total):raise ValueError('INVALID_REJECTION_DETAIL_TOTALS')
    return detail

def record(metrics,rows):
    """Run before existing rejected_checks increments, in its existing transaction."""
    if 'rejection_detail' not in metrics:
        metrics['rejection_detail']=dict(schema=1,baseline_rejected_checks=metrics['rejected_checks'],
            baseline_categories=legacy_categories(histogram(metrics)),counts=empty(CATEGORIES))
    for row in rows:
        if row.get('state')!='QUALIFIED':metrics['rejection_detail']['counts'][category(row)]+=1

def summary(metrics):
    total=metrics.get('rejected_checks',0);reasons=histogram(metrics);detail=metrics.get('rejection_detail')
    if detail is None:
        baseline=total;categories=legacy_categories(reasons);split=0
        coverage='LEGACY_AGGREGATES_ONLY' if total else 'COMPLETE_SINCE_TRIAL_START'
    else:
        validate_detail(detail,total);baseline=detail['baseline_rejected_checks'];split=total-baseline
        categories={k:detail['baseline_categories'][k]+detail['counts'][k] for k in CATEGORIES}
        coverage='SPLIT_SINCE_UPGRADE' if baseline else 'COMPLETE_SINCE_TRIAL_START'
    return dict(schema=SCHEMA,coverage=coverage,total=total,history_before_split=baseline,
        split_checks=split,categories=categories,reasons=reasons)

def validate(value,total):
    if (not isinstance(value,dict) or set(value)!={'schema','coverage','total','history_before_split','split_checks','categories','reasons'} or
            value['schema']!=SCHEMA or not isinstance(value['coverage'],str) or value['coverage'] not in COVERAGE):raise ValueError('INVALID_REJECTION_PUBLIC_SCHEMA')
    if any(not count(value[k]) for k in ('total','history_before_split','split_checks')):raise ValueError('INVALID_REJECTION_PUBLIC_COUNT')
    for name,keys in (('categories',CATEGORIES),('reasons',REASONS)):
        if not isinstance(value[name],dict) or set(value[name])!=set(keys) or any(not count(n) for n in value[name].values()):
            raise ValueError('INVALID_REJECTION_PUBLIC_KEYS_OR_COUNTS')
        if sum(value[name].values())!=value['total']:raise ValueError('INVALID_REJECTION_PUBLIC_SUM')
    if value['total']!=total or value['history_before_split']+value['split_checks']!=total:raise ValueError('INVALID_REJECTION_PUBLIC_TOTAL')
    if (value['coverage']=='COMPLETE_SINCE_TRIAL_START' and value['history_before_split']!=0 or
            value['coverage']=='LEGACY_AGGREGATES_ONLY' and value['split_checks']!=0 or
            value['coverage']=='SPLIT_SINCE_UPGRADE' and value['history_before_split']==0):raise ValueError('INVALID_REJECTION_PUBLIC_COVERAGE')
    return value

def public_copy(value,total):return deepcopy(validate(value,total))

def diagnostic_lines(value):
    validate(value,value['total'])
    lines=['Opportunity rejection breakdown: '+str(value['total'])+' direction checks; one first blocking reason per rejected check.',
        'Rejection history coverage: '+value['coverage']+'; checks before detailed split '+str(value['history_before_split'])+
        '; checks with detailed split '+str(value['split_checks'])+'.']
    lines.extend('  '+LABELS[k]+': '+str(value['categories'][k]) for k in CATEGORIES)
    lines.append('Rejection reason counts (fixed codes):')
    lines.extend('  '+k+': '+str(n) for k,n in value['reasons'].items() if n)
    if not value['total']:lines.append('  No rejected checks recorded.')
    lines.append('Counts include repeated reviews and warmup; these are not rejected exchange orders. Unsplit history is not attributed to a guessed cause.')
    return lines
