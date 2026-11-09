"""Fixed synthetic 24h forward comparisons; no client, credentials or network.

The future path is withheld from selection. These cases test conservation and
adverse outcomes, not model accuracy or realistic exchange fill probabilities.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
from coincat_forecast_24h import HOUR,forecast
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_intelligent_trader import IntelligentTrader
from coincat_intelligent_policy import IntelligentConfig
from coincat_maker_shadow import active
from coincat_version import DISPLAY
from offline_tests.intelligent_fixtures import Clock,history,frame

CASES=('flat_costs_hold','trend_no_fill','trend_unseen_reversal','trend_unseen_continuation','high_own_fee_hold')

@native_math
def run_case(name,comparison='DIRECT_24H_ANALOG_V1'):
    if name not in CASES or comparison not in ('DIRECT_24H_ANALOG_V1','NAIVE_24H_MOMENTUM'):raise ValueError('Unknown fixed comparison')
    clock=Clock();rows=history(clock,mode='flat' if name=='flat_costs_hold' else 'btc_trend');at_start=clock.wall()
    initial=frame(clock,rows,maker=D('.04') if name=='high_own_fee_hold' else D('.005'));prediction=deepcopy(initial['forecast'])
    if comparison=='NAIVE_24H_MOMENTUM':prediction['mean']={a:rows[-1]['marks'][a]/rows[-25]['marks'][a]-1 for a in rows[-1]['marks']}
    config=replace(IntelligentConfig(),provider='NO_FILL_OBSERVATION_V1' if name=='trend_no_fill' else 'TRADE_THROUGH_QUEUE_V1')
    with TemporaryDirectory(prefix='CoinCat_v105_Fixed_Forward_') as folder:
        engine=IntelligentTrader(Path(folder)/'trial.sqlite3',clock=clock.wall,monotonic_ns=clock.ns);engine.start(config)
        prints=[];chosen=None;tape=[]
        for i in range(10):
            f=frame(clock,rows,maker=initial['tier']['maker'],prediction=prediction);f['forecast'].update(decision_at=clock.wall(),forecast_end_at=clock.wall()+86400)
            o=active(engine.state()) if engine.state() else None
            if o:
                if chosen is None:chosen=deepcopy(o['projection'])
                tick=D(o['rules']['price_increment']);price=o['price']+tick if o['side']=='SELL' else o['price']-tick
                prints.append(dict(id='fixed-print-'+str(i),price=price,size=D(1000),at=clock.wall()))
                f['market_trades']=dict(pair=o['pair'],at=clock.wall(),prints=deepcopy(prints))
            engine.review(f);s=engine.state();tape.append(dict(elapsed_s=clock.wall()-at_start,performance=s['last_performance'],fills=s['metrics']['fill_events']))
            clock.tick(10)
        engine.pause();clock.tick(3);engine.heartbeat(persist=True);original=deepcopy(engine.state()['original'])
        future=deepcopy(rows);end=int(at_start)//HOUR*HOUR
        # Deterministic forward observations, unavailable to the decision above.
        change=D('.8') if name=='trend_unseen_reversal' else D('1.05') if name=='trend_unseen_continuation' else D(1)
        for hour in range(1,25):
            marks=deepcopy(rows[-1]['marks']);marks['BTC']*=1+(change-1)*D(hour)/24;future.append(dict(at=end+hour*HOUR,marks=marks))
        clock.tick(86400-(clock.wall()-at_start));engine.start()
        try:next_prediction=forecast(future[-2400:],clock.wall())
        except BetaBlocked as exc:next_prediction=dict(state='HOLD',reason=str(exc))
        f=frame(clock,future[-2400:],maker=initial['tier']['maker'],prediction=next_prediction);engine.review(f);s=engine.state();perf=s['last_performance']
        assert s['original']==original
        assert perf['advantage_usd']==perf['portfolio_usd']-perf['hold_usd']
        assert sum(s['fees_native'].values())>=0
        result=dict(case=name,comparison=comparison,version=DISPLAY,classification='FIXED_SYNTHETIC_CONDITIONAL_NOT_PROFITABILITY_EVIDENCE',
            forecast_horizon_s=86400,chosen=chosen,performance=perf,original=original,wallet=s['wallet'],native_fees=s['fees_native'],
            metrics=s['metrics'],max_drawdown=s['max_drawdown'],forward_counts=s['prediction_counts'],
            chronological_validation=prediction['provenance']['validation'],unseen_historical_holdout=prediction['provenance']['holdout'],tape=tape)
        engine.shutdown();return result

def render(results):
    lines=['# '+DISPLAY+' — fixed chronological engineering comparisons','',
        'Synthetic 100-day history; the following 24h path is withheld from entry decisions. Original five-asset HOLD stays immutable.',
        'Both forecast alternatives use the same wallet, entry rules, own maker fee, risk constraints and conditional queue provider.',
        'This is not a historical backtest, calibrated maker-fill study, native Windows run or profitability claim. No account is opened.','',
        '| Forward case | Forecast | Fills | Portfolio USD | Original HOLD USD | Advantage USD |',
        '|---|---|---:|---:|---:|---:|']
    for row in results:
        p=row['performance'];lines.append('| '+row['case']+' | '+row['comparison']+' | '+str(row['metrics']['fill_events'])+' | '+
            ' | '.join(format(p[k],'.8f') for k in ('portfolio_usd','hold_usd','advantage_usd'))+' |')
    lines+=['','Zero fills incur zero commission. Reversal losses are retained. Positive synthetic outcomes do not validate forecasts.',
        'The private application records prospective 24h outcomes and overlapping-sample limitations; 168 valid hours may finish with no trades.']
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve()
    if output==ROOT or ROOT in output.parents:raise ValueError('Keep generated evidence outside source')
    results=[run_case(case,model) for case in CASES for model in ('DIRECT_24H_ANALOG_V1','NAIVE_24H_MOMENTUM')]
    output.mkdir(parents=True,exist_ok=True);(output/'intelligent-scenarios.json').write_text(json.dumps(results,default=str,indent=2)+'\n')
    (output/'intelligent-scenarios.md').write_text(render(results),encoding='utf-8');print(render(results))
    return 0

if __name__=='__main__':raise SystemExit(main())
