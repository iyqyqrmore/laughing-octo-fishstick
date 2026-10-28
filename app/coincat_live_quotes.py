"""Public Coinbase spot bid/ask snapshots. No orders and no backfilled candles."""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import requests
from coincat_cross_quote import split_spot

TICKER='https://api.coinbase.com/api/v3/brokerage/market/products/{pair}/ticker'

def fetch_public_ticker(pair,*,get=None):
    split_spot(pair)  # strict identifier: no extra hyphens, path injection, or synthetic product
    from coincat_v701_transport import BUDGET, pooled_get
    import time
    BUDGET.acquire(time.monotonic()+10)
    response=(pooled_get if get is None else get)(TICKER.format(pair=pair),params={'limit':1},timeout=10,
                 headers={'Accept':'application/json'})
    if getattr(response, 'status_code', None) == 429:
        BUDGET.postpone(response.headers.get('Retry-After'))
    response.raise_for_status()
    return parse_ticker(response.json())


def parse_ticker(data):
    try:bid=Decimal(str(data['best_bid']));ask=Decimal(str(data['best_ask']))
    except (KeyError,InvalidOperation,TypeError) as ex:raise ValueError('Coinbase ticker missing bid/ask') from ex
    if not all(x.is_finite() for x in (bid,ask)) or not 0<bid<=ask:raise ValueError('Crossed or invalid bid/ask')
    return bid,ask
