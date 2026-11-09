"""Fixed synthetic minute/5m histories; current prices do not depend on the future."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_watchlist import WATCH_ASSETS
from coincat_horizon_forecast import HORIZONS,short_forecast,immediate_inputs
from offline_tests.intelligent_fixtures import Clock,frame,history

def series(clock,seconds,count,*,rate=D('.0015'),asset='BTC',end_marks=None):
    end=int(clock.wall())//seconds*seconds;marks=deepcopy(end_marks or dict(ETH=D(2000),BTC=D(60000),ADA=D('.4'),LINK=D(12),SOL=D(100)))
    anchor=int(clock.wall())//60*60;marks[asset]/=(1+rate)**((anchor-end)//60)
    values=[]
    for i in range(count):
        values.append(dict(at=end-i*seconds,marks=deepcopy(marks)));marks[asset]/=(1+rate)**(seconds//60)
    return list(reversed(values))

def predictions(clock,minute=None,five=None,*,daily=None):
    minute=minute or series(clock,60,4320);five=five or series(clock,300,2880)
    result=dict(IMMEDIATE=immediate_inputs(minute,clock.wall()),H24=daily or dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT'))
    for name in ('M5','M15','M30','H2'):result[name]=short_forecast(minute if name in ('M5','M15') else five,clock.wall(),name)
    return {name:result[name] for name in HORIZONS}

def observed(clock,forecasts,*,maker=D('.005')):
    end=series(clock,60,1)[-1];f=frame(clock,[end],prediction=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT'),maker=maker)
    f['horizon_forecasts']=deepcopy(forecasts);return f
