"""Synthetic timestamped hourly USD references, native books and account data."""
from decimal import Decimal as D
from copy import deepcopy
import math
from coincat_forecast_24h import HOUR,forecast
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS
from coincat_assumed_math import rounded
from offline_tests.test_resumable_trial import Clock
from offline_tests.test_spot_manual import cid

def history(clock,*,count=2400,mode='btc_trend'):
    end=int(clock.wall())//HOUR*HOUR;prices=dict(ETH=D(2000),BTC=D(60000),ADA=D('.4'),LINK=D(12),SOL=D(100));rows=[]
    for i in range(count):
        if mode=='btc_trend':prices['BTC']/=D('.999')
        elif mode=='eth_trend':prices['ETH']/=D('.999')
        elif mode=='noisy':
            for j,a in enumerate(WATCH_ASSETS):prices[a]*=1+D(str(.0003*math.sin(i/57+j)+.00015*math.sin(i/13+2*j)))
        elif mode!='flat':raise ValueError(mode)
        rows.append(dict(at=end-(count-1-i)*HOUR,marks=deepcopy(prices)))
    return rows

def frame(clock,rows=None,*,maker=D('.005'),account=None,prediction=None):
    rows=rows or history(clock);marks=rows[-1]['marks'];tick=D('.000000000001');books={}
    for pair in WATCH_PAIRS+('ETH-USD',):
        base,quote=pair.split('-');p=marks[base]/(D(1) if quote=='USD' else marks[quote]);bid=rounded(p*D('.9999'),tick);ask=rounded(p*D('1.0001'),tick,up=True)
        books[pair]=dict(pair=pair,at=clock.wall(),bid=bid,ask=ask,bids=((bid,D('.000001')),(bid-tick,D(100000))),
            asks=((ask,D('.000001')),(ask+tick,D(100000))))
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,base_increment='.000001',
        quote_increment=str(tick),price_increment=str(tick),base_min_size='.000001',quote_min_size='.000000001') for p in WATCH_PAIRS}
    references={a+'-USD':dict(pair=a+'-USD',at=clock.wall(),bid=marks[a]*D('.9999'),ask=marks[a]*D('1.0001'),
        bids=((marks[a]*D('.9999'),D(100000)),),asks=((marks[a]*D('1.0001'),D(100000)),)) for a in WATCH_ASSETS}
    account=account or dict(portfolio=cid(40),at=clock.wall(),available={a:D(100)/marks[a] for a in WATCH_ASSETS},holds={a:D(0) for a in WATCH_ASSETS})
    return dict(state='OBSERVED',at=clock.wall(),portfolio=cid(40),account=deepcopy(account),books=books,reference_books=references,rules=rules,
        tier=dict(at=clock.wall(),maker=maker,source='AUTHENTICATED_ACCOUNT_TIER'),market_trades=None,
        forecast=deepcopy(prediction) if prediction is not None else forecast(rows,clock.wall()))
