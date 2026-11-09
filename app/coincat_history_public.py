"""Fixed reference-bar progress, never account holdings or native trade amounts."""
import math
from copy import deepcopy
from coincat_history_backfill import SPECS,REASONS
from coincat_candle_cache import REFERENCES

def validate(value):
    if not isinstance(value,dict) or set(value)!={'state','reason','attempts','failures','last_success_age_s','granularities'}:raise ValueError('HISTORY_PROGRESS_KEYS')
    if not isinstance(value['state'],str) or value['state'] not in ('IDLE','DOWNLOADING','COLLECTING','BACKOFF','REVIEW_REQUIRED') or not isinstance(value['reason'],str) or value['reason'] not in REASONS:raise ValueError('HISTORY_PROGRESS_STATE')
    for key in ('attempts','failures'):
        if type(value[key]) is not int or not 0<=value[key]<=2**53:raise ValueError('HISTORY_PROGRESS_COUNT')
    age=value['last_success_age_s']
    if age is not None and (type(age) not in (int,float) or not math.isfinite(age) or not 0<=age<=2**53):raise ValueError('HISTORY_PROGRESS_AGE')
    if value['failures']>value['attempts']+1:raise ValueError('HISTORY_PROGRESS_FAILURES')
    if not isinstance(value['granularities'],dict) or set(value['granularities'])!=set(SPECS):raise ValueError('HISTORY_PROGRESS_GRANULARITIES')
    for name,row in value['granularities'].items():
        if not isinstance(row,dict) or set(row)!={'state','interval_s','required','aligned','products'}:raise ValueError('HISTORY_PROGRESS_GRANULARITY_KEYS')
        seconds,required=SPECS[name]
        if (row['state'] not in ('REVIEW_REQUIRED','BACKOFF','SUFFICIENT_BARS','PARTIAL','EMPTY') or type(row['interval_s']) is not int or row['interval_s']!=seconds or
                type(row['required']) is not int or row['required']!=required or type(row['aligned']) is not int or not 0<=row['aligned']<=required):raise ValueError('HISTORY_PROGRESS_COVERAGE')
        if not isinstance(row['products'],dict) or set(row['products'])!=set(REFERENCES):raise ValueError('HISTORY_PROGRESS_PRODUCTS')
        for counts in row['products'].values():
            if (not isinstance(counts,dict) or set(counts)!={'bars','pages'} or any(type(n) is not int or not 0<=n<=2**53 for n in counts.values()) or
                    counts['bars']>required or counts['bars']<row['aligned']):raise ValueError('HISTORY_PROGRESS_PRODUCT_COUNTS')
    return value

def project(value):return validate(deepcopy(value))
