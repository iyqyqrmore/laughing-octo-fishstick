"""Read-only ten-day Coinbase spot OHLCV bootstrap.

Historical candles are separate from real-time bid/ask quotes, forward-scored
signals and Coinbase actual fills. Their existence never implies a buy signal.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import time
from coincat_cross_quote import split_spot
import requests

CANDLES='https://api.coinbase.com/api/v3/brokerage/market/products/{pair}/candles'


def fetch_public_hourly_candles(pair, *, now=None, days=10, get=requests.get):
    split_spot(pair)  # any valid Coinbase crypto-crypto spot pair; research only
    if days != 10:raise ValueError('Historical bootstrap is limited to 10 days')
    now=int(now or time.time());start=now-days*86400
    response=get(CANDLES.format(pair=pair),params={
        'start':str(start),'end':str(now),'granularity':'ONE_HOUR','limit':300
    },headers={'Accept':'application/json'},timeout=18)
    response.raise_for_status();payload=response.json()
    if not isinstance(payload,dict) or not isinstance(payload.get('candles'),list):
        raise ValueError('Coinbase candles payload is missing')
    cleaned=[]
    for row in payload['candles']:
        try:
            ts=int(row['start'])
            o,h,l,c,v=[Decimal(str(row[k])) for k in ('open','high','low','close','volume')]
            if not all(x.is_finite() for x in (o,h,l,c,v)):continue
            if not (0<l<=o<=h and l<=c<=h and v>=0):continue
            if start-3600<=ts<=now:cleaned.append((ts,str(o),str(h),str(l),str(c),str(v)))
        except (ValueError,KeyError,TypeError,InvalidOperation):continue
    return sorted(set(cleaned),key=lambda x:x[0])


def fetch_public_hourly_range(pair, start_utc, end_utc, *, get=requests.get):
    """Fetch only missing hourly market context, never invented forward quotes.

    Calls are capped at ten days / 240 hours. The caller refreshes the last
    two hours again to capture revisions and the active partial hourly candle.
    """
    split_spot(pair)  # strict research product identifier
    start=int(start_utc); end=int(end_utc)
    if not 0 < end-start <= 10*86400:
        raise ValueError('Historical context must cover a positive interval of at most 10 days')
    response=get(CANDLES.format(pair=pair),params={
        'start':str(start),'end':str(end),'granularity':'ONE_HOUR','limit':300},
        headers={'Accept':'application/json'},timeout=18)
    response.raise_for_status(); payload=response.json()
    if not isinstance(payload,dict) or not isinstance(payload.get('candles'),list):
        raise ValueError('Missing Coinbase candles')
    good={}
    for row in payload['candles']:
        try:
            ts=int(row['start'])
            o,h,l,cl,v=(Decimal(str(row[k])) for k in ('open','high','low','close','volume'))
            if not all(x.is_finite() for x in (o,h,l,cl,v)):continue
            if not (0<l<=o<=h and l<=cl<=h and v>=0):continue
            if start-3600<=ts<=end:good[ts]=(ts,str(o),str(h),str(l),str(cl),str(v))
        except (KeyError,ValueError,TypeError,InvalidOperation):continue
    return [good[k] for k in sorted(good)]
