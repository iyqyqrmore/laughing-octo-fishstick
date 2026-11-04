"""Strict quantity-free beta projections shared by diagnostics and monitor."""
LIVE_KEYS='blocked state orders fills unresolved settings_version classification profit provider'
MANUAL_KEYS='state orders filled partials canceled_unfilled known_native_flow unknown account_reconciliation execution_authority sample_warning'
BOOK_KEYS='state subscribed healthy provider queue_or_fills_verified'
LIVE_STATES={'OFF','PAUSED','ACTIVE','RECONCILIATION_REQUIRED','EXPIRED','UNKNOWN_LOCKED','UNAVAILABLE','UNKNOWN'}


def _count(value):return value if type(value) is int and 0<=value<=8192 else 0


def project(live=None,manual=None,book=None):
    live=live or {};manual=manual or {};book=book or {}
    return dict(live=dict(blocked=live.get('blocked') is not False,
        state=live.get('state') if live.get('state') in LIVE_STATES else 'UNKNOWN',
        **{k:_count(live.get(k)) for k in ('orders','fills','unresolved','settings_version')},
        classification='REAL_BETA_EXECUTION',profit='NOT_ESTABLISHED',provider='COINBASE_LIMIT_POST_ONLY'),
        manual=dict(state=manual.get('state') if manual.get('state') in ('UNOBSERVED','OBSERVED','UNAVAILABLE') else 'UNOBSERVED',
            **{k:_count(manual.get(k)) for k in ('orders','filled','partials','canceled_unfilled','known_native_flow','unknown')},
            account_reconciliation='UNKNOWN',execution_authority=False,sample_warning='SMALL_SELECTED_SAMPLE_NO_DEMONSTRATED_EDGE'),
        book=dict(state=book.get('state') if book.get('state') in ('OFF','HEALTHY','RESYNCING','UNAVAILABLE') else 'OFF',
            subscribed=min(6,_count(book.get('subscribed'))),healthy=min(6,_count(book.get('healthy'))),
            provider='PUBLIC_LEVEL2_OBSERVATION',queue_or_fills_verified=False))


def validate(value):
    def keys(obj,expected):
        if not isinstance(obj,dict) or set(obj)!=set(expected.split()):raise ValueError('INVALID_BETA_PUBLIC_SCHEMA')
    keys(value,'live manual book');keys(value['live'],LIVE_KEYS);keys(value['manual'],MANUAL_KEYS);keys(value['book'],BOOK_KEYS)
    for obj,fields in ((value['live'],'orders fills unresolved settings_version'),
            (value['manual'],'orders filled partials canceled_unfilled known_native_flow unknown'),(value['book'],'subscribed healthy')):
        for key in fields.split():
            if type(obj[key]) is not int or obj[key]!=_count(obj[key]):raise ValueError('INVALID_BETA_PUBLIC_COUNT')
    for obj,key in ((value['live'],'blocked'),(value['manual'],'execution_authority'),(value['book'],'queue_or_fills_verified')):
        if type(obj[key]) is not bool:raise ValueError('INVALID_BETA_PUBLIC_FLAG')
    if project(value['live'],value['manual'],value['book'])!=value:raise ValueError('INVALID_BETA_PUBLIC_VALUE')
    if value['book']['healthy']>value['book']['subscribed']:raise ValueError('INVALID_BETA_BOOK_COUNTS')
    return value
