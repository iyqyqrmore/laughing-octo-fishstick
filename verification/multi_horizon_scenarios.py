"""Paired synthetic forward one-leg studies, not forecast/fill calibration.

Each policy sees identical past histories, wallet, native rules, own fees and
public tape. Ninety seconds of conditional execution precedes a withheld two-
hour path. This isolates selection/fees/fills; it is not a continuous backtest.
"""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_forecast_24h import forecast as daily_forecast
from coincat_horizon_forecast import HORIZONS
from coincat_intelligent_policy import project_forecast,performance
from coincat_intelligent_trader import IntelligentTrader,IntelligentPolicy
from coincat_maker_shadow import MakerShadowTrader,active
from coincat_multi_policy import MultiConfig,native_sizes,corrected_core
from coincat_multi_trader import MultiTrader
from coincat_portfolio_policy import DIRECTIONS
from coincat_version import DISPLAY
from coincat_watchlist import WATCH_PAIRS
from offline_tests.multi_fixtures import Clock,series,predictions
from offline_tests.intelligent_fixtures import frame

CASES=('flat_hold','long_trend_no_fill','long_trend_continuation','long_trend_reversal','short_history_continuation','short_history_reversal','fees_exceed_edge')

class NaivePolicy(IntelligentPolicy):
    name='NAIVE_M15_REFERENCE_V1';provider='NAIVE_M15_SHADOW_NO_LIVE_AUTHORITY';report_prefix='naive-m15-'
    def observe(self,s,frame,now):
        if frame.get('portfolio')!=s['account_scope']:raise BetaBlocked('SYNTHETIC_SCOPE_CHANGED')
    @staticmethod
    def assess(frame,wallet,original,observations,config,ticket,*,resting=False):
        f=frame['horizon_forecasts']['M15'].get('naive_reference',{})
        if f.get('state')!='READY':raise BetaBlocked('HORIZON_HISTORY_INSUFFICIENT')
        core,_=corrected_core(MultiConfig(**config.__dict__));r=project_forecast(frame,wallet,original,core,ticket,f,resting=resting)
        r['expected_incremental_usd']=r.pop('expected_24h_incremental_usd');return r
    @staticmethod
    def evaluate(frame,wallet,available,original,observations,config):
        rows=[];f=frame['horizon_forecasts']['M15'].get('naive_reference',{})
        for direction in DIRECTIONS:
            row=dict(**direction,state='HOLD',reason='HORIZON_HISTORY_INSUFFICIENT')
            try:
                if f.get('state')!='READY':raise BetaBlocked('HORIZON_HISTORY_INSUFFICIENT')
                price,sizes=native_sizes(frame,direction,available[direction['source']],f,config);candidates=[]
                for size in sizes:
                    try:candidates.append(NaivePolicy.assess(frame,wallet,original,observations,config,dict(pair=direction['pair'],side=direction['side'],size=size,price=price)))
                    except (ValueError,TypeError,KeyError,ArithmeticError):pass
                if candidates:row.update(max(candidates,key=lambda r:r['projected_advantage_usd']))
            except (ValueError,TypeError,KeyError,ArithmeticError):pass
            rows.append(row)
        qualified=[r for r in rows if r['state']=='QUALIFIED'];return rows,max(qualified,key=lambda r:r['projected_advantage_usd']) if qualified else None
    def report_metadata(self):return dict(version=DISPLAY,selected_policy=self.name,reference='OBSERVED_15_MINUTE_MOMENTUM_WITH_PAST_NAIVE_RESIDUALS')

@native_math
def run_case(name):
    if name not in CASES:raise ValueError('Unknown fixed scenario')
    clock=Clock();rate=D(0) if name=='flat_hold' else D('.00001') if name=='fees_exceed_edge' else D('.0015') if name.startswith('short_history') else D('.00005')
    minute=series(clock,60,4320,rate=rate);five=series(clock,300,2880,rate=rate);hours=series(clock,3600,240 if name.startswith('short_history') else 2400,rate=rate)
    try:daily=daily_forecast(hours,clock.wall())
    except BetaBlocked as exc:daily=dict(state='HOLD',reason=str(exc))
    forecasts=predictions(clock,minute,five,daily=daily);maker=D('.04') if name=='fees_exceed_edge' else D('.005')
    provider='NO_FILL_OBSERVATION_V1' if name=='long_trend_no_fill' else 'TRADE_THROUGH_QUEUE_V1';tapes={p:[] for p in WATCH_PAIRS};start=clock.wall()
    with TemporaryDirectory(prefix='CoinCat_Multi_Paired_Forward_') as folder:
        base=IntelligentTrader(Path(folder)/'24h.sqlite3',clock=clock.wall,monotonic_ns=clock.ns)
        multi=MultiTrader(Path(folder)/'multi.sqlite3',clock=clock.wall,monotonic_ns=clock.ns)
        naive=MakerShadowTrader(Path(folder)/'naive.sqlite3',policy=NaivePolicy(),clock=clock.wall,monotonic_ns=clock.ns)
        engines={'24H_ONLY':base,'MULTI_HORIZON':multi,'NAIVE_M15':naive};projections={};states={}
        for e in engines.values():e.start(e.pending_config.__class__(provider=provider))
        for i in range(9):
            f=frame(clock,[minute[-1]],prediction=daily,maker=maker);f['horizon_forecasts']=deepcopy(forecasts)
            if f['forecast']['state']=='READY':f['forecast'].update(decision_at=clock.wall(),forecast_end_at=clock.wall()+86400)
            for p in f['horizon_forecasts'].values():
                if p['state']=='READY':p.update(decision_at=clock.wall(),forecast_end_at=clock.wall()+p['horizon_s'])
            for pair in WATCH_PAIRS:
                b=f['books'][pair]
                for side,price in (('up',b['ask']*D('1.0001')),('down',b['bid']*D('.9999'))):tapes[pair].append(dict(id=str(i)+'-'+side,price=price,size=D(1000),at=clock.wall()))
            for label,e in engines.items():
                observed=deepcopy(f);pair=e.current_pair()
                if pair:observed['market_trades']=dict(pair=pair,at=clock.wall(),prints=deepcopy(tapes[pair]))
                e.review(observed);o=active(e.state())
                if label not in projections and o is not None:projections[label]=deepcopy(o['projection'])
            clock.tick(10)
        for e in engines.values():e.pause()
        clock.tick(3)
        for label,e in engines.items():e.heartbeat(persist=True);states[label]=e.state()
        original=deepcopy(base.state()['original']);assert all(s['original']==original for s in states.values())
        assert all(s['started_at']==base.state()['started_at'] for s in states.values())
        factor=D('.9') if name.endswith('reversal') else D('1.02') if name.endswith('continuation') or name=='long_trend_no_fill' else D(1)
        end_marks=deepcopy(minute[-1]['marks']);end_marks['BTC']*=factor;clock.tick(7200-(clock.wall()-start))
        final=frame(clock,[dict(at=clock.wall(),marks=end_marks)],prediction=dict(state='HOLD',reason='NO_FUTURE_INPUTS_AT_ORIGINAL_DECISION'),maker=maker)
        outcomes={}
        for label,s in states.items():
            perf=performance(final,s['wallet'],s['original'],s['initial_usd']);proposal=projections.get(label)
            score=None if proposal is None else proposal['projected_advantage_usd']
            horizon=None if proposal is None else 86400 if label=='24H_ONLY' else 900 if label=='NAIVE_M15' else proposal['horizon_s']
            outcomes[label]=dict(strategy=s['strategy'],wallet=s['wallet'],native_fees=s['fees_native'],metrics=s['metrics'],performance=perf,
                proposed_horizon=horizon,projected_risk_adjusted_advantage=score,initial_projection=proposal,
                forecast_outcome='NO_PROPOSAL' if proposal is None else 'NOT_MATURED_IN_TWO_HOUR_FORWARD_WINDOW' if horizon>7200 else 'WITHHELD_SYNTHETIC_FORWARD_PATH',
                original=original,started_at=s['started_at'])
        for e in engines.values():e.shutdown()
        hold=performance(final,original,original,base.state()['initial_usd']);assert hold['advantage_usd']==0
        return dict(case=name,version=DISPLAY,classification='PAIRED_SYNTHETIC_ONE_LEG_FORWARD_STUDY_NOT_CONTINUOUS_BACKTEST',
            common_provider=provider,common_maker_rate=maker,common_original=original,common_start=start,forward_seconds=7200,
            hold=hold,outcomes=outcomes,forecast_status={n:f['state'] for n,f in forecasts.items()})

def render(rows):
    lines=['# '+DISPLAY+' — paired multi-horizon engineering comparisons','',
        'Identical original wallets, decision times, closed histories, native rules, own fees and independent-of-orders public tapes.',
        'Ninety seconds of conditional execution, then a withheld two-hour path with inventory retained. No future return enters the original decision.',
        'This isolates one-leg decisions/accounting/execution. It is not a continuous market backtest or forecast/fill calibration.','',
        '| Case | Policy | Proposed horizon s | Fill events | Portfolio USD | HOLD USD | Net advantage USD |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in rows:
        for label,trial in row['outcomes'].items():
            p=trial['performance'];lines.append('| '+row['case']+' | '+label+' | '+str(trial['proposed_horizon'])+' | '+str(trial['metrics']['fill_events'])+' | '+
                ' | '.join(format(p[k],'.8f') for k in ('portfolio_usd','hold_usd','advantage_usd'))+' |')
    lines+=['','Losing and no-fill outcomes are retained. 24h outcomes have not matured in a two-hour window. Short history is not sufficient for the 100-day baseline.',
        'No real account is opened; one reported 65-second manual fill does not calibrate these queue assumptions or justify a historical recommendation.']
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve()
    if out==ROOT or ROOT in out.parents:raise ValueError('Generated evidence stays outside source')
    rows=[run_case(name) for name in CASES];out.mkdir(parents=True,exist_ok=True)
    (out/'multi-horizon-comparison.json').write_text(json.dumps(rows,default=str,indent=2)+'\n')
    (out/'multi-horizon-comparison.md').write_text(render(rows),encoding='utf-8');print(render(rows));return 0

if __name__=='__main__':raise SystemExit(main())
