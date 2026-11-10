"""M2 walk-forward study only. Real CSVs required; no paper/live dispatch."""
from bisect import bisect_left
from collections import deque
from datetime import datetime,timezone
from pathlib import Path
from decimal import Decimal as D
import argparse,csv,json,hashlib
from v106.fee_check import ROOT,exact,save_report
from v106.export_candles import bar,iso
from v106.simulator import Simulator
from v106.strategies import snap
from v106.preregistered import (MAKER,TAKER,FEE_STRESS,TRAIN_DAYS,TEST_DAYS,STRATEGIES,SOURCE_FRACTION,
    ENTRY_SIDE,ROUNDTRIPS,ALTERNATING_SIDE,ALTERNATING_PARAMETERS,MIN_TEST_WINDOWS,MIN_ADVANTAGE_FRACTION,grid,verdict)
from coincat_execution_limits import native_math

PREREGISTRATION_COMMIT='eed34e25f5dd35499d5e3086a2d4f090a3ffd3b3'


def load_frames(directory,rules):
    refs={}
    for asset in ('ETH','BTC'):
        with (directory/(asset+'-USD_5m.csv')).open(newline='',encoding='utf-8') as f:
            refs[asset]={int(r['start']):exact(r['close']) for r in csv.DictReader(f)}
    tick=exact(rules['price_increment']);frames=[]
    with (directory/'ETH-BTC_5m.csv').open(newline='',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            t,values=bar(row,300)
            if t not in refs['ETH'] or t not in refs['BTC']:continue
            o,h,low,c,v=map(exact,values);bid=snap(c,tick)-tick;ask=snap(c,tick,up=True)+tick
            if bid<=0 or refs['ETH'][t]<=0 or refs['BTC'][t]<=0:raise ValueError('Invalid positive price')
            frames.append(dict(start=t,at=t+300,open=o,high=h,low=low,close=c,volume=v,bid=bid,ask=ask,
                eth_usd=refs['ETH'][t],btc_usd=refs['BTC'][t]))
    frames.sort(key=lambda f:f['at'])
    if len({f['at'] for f in frames})!=len(frames):raise ValueError('Duplicate decision bars')
    return frames


@native_math
def choose(name,frames,rules):
    if name=='ROUNDTRIP_ALTERNATING':raise ValueError('Reuse ROUNDTRIP selection; no alternating parameter search')
    best=None
    for index,params in enumerate(grid(name)):
        sim=Simulator(name,frames[0],rules,params=params)
        for frame in frames:sim.step(frame)
        result=sim.snapshot();key=(result['advantage_usd'],-result['fees_usd'],-result['orders'],-index)
        if best is None or key>best[0]:best=(key,params)
    return best[1]


@native_math
def study(frames,rules,*,train_days=TRAIN_DAYS,test_days=TEST_DAYS,progress=None):
    if not frames:return dict(status='NOT_EVALUATED',reason='NO_SYNCHRONIZED_CANDLES',windows=[],strategies={})
    stamps=[f['at'] for f in frames];cut=stamps[0]+train_days*86400
    windows=[];engines={};stress={};ledger=[]
    while cut+test_days*86400<=stamps[-1]+300:
        train=frames[bisect_left(stamps,cut-train_days*86400):bisect_left(stamps,cut)]
        test=frames[bisect_left(stamps,cut):bisect_left(stamps,cut+test_days*86400)]
        if not train or not test:cut+=test_days*86400;continue
        row=dict(start_utc=iso(test[0]['at']),end_utc=iso(test[-1]['at']),train_end_utc=iso(train[-1]['at']),observations=len(test),results={})
        selected={}
        for name in STRATEGIES:
            selection='reusing ROUNDTRIP training choice' if name=='ROUNDTRIP_ALTERNATING' else f'selecting on {len(train)} past bars'
            if progress:progress(f"M2 window {len(windows)+1} {row['start_utc']} | {name} | {selection}, then {len(test)} unseen bars")
            params=selected['ROUNDTRIP'] if name=='ROUNDTRIP_ALTERNATING' else choose(name,train,rules)
            selected[name]=params
            if name not in engines:
                engines[name]=Simulator(name,test[0],rules,params=params,record=True)
                stress[name]=Simulator(name,test[0],rules,params=params,fee=MAKER*FEE_STRESS)
                for engine in (engines[name],stress[name]):engine.trail=deque((f['close'] for f in train[-287:]),maxlen=288)
            sim,stressed=engines[name],stress[name];before=sim.snapshot();stress_before=stressed.snapshot()
            peak=before['value_usd'];dd=D(0)
            for frame in test:
                sim.step(frame,params);stressed.step(frame,params)
                nav=sim.value(frame)['value_usd'];peak=max(peak,nav);dd=max(dd,1-nav/peak)
            after=sim.snapshot();after_stress=stressed.snapshot()
            result=dict(selected_params=params,ending_value_usd=after['value_usd'],hold_usd=after['hold_usd'],
                advantage_change_usd=after['advantage_usd']-before['advantage_usd'],
                advantage_change_btc=after['advantage_btc']-before['advantage_btc'],
                cumulative_advantage_usd=after['advantage_usd'],cumulative_advantage_btc=after['advantage_btc'],
                stressed_change_usd=after_stress['advantage_usd']-stress_before['advantage_usd'],
                fees_usd=after['fees_usd']-before['fees_usd'],
                fees_pct_starting_portfolio=100*(after['fees_usd']-before['fees_usd'])/before['value_usd'],
                max_drawdown=dd,time_in_market_pct=after['time_in_market_pct'])
            for key in ('orders','filled_orders','fills','misses','entry_cancels','entry_replaces','cycles','gaps'):
                result[key]=after[key]-before[key]
            result['trades']=result['filled_orders']
            if name in ROUNDTRIPS:
                result['by_entry_side']={}
                for side,g in after['by_entry_side'].items():
                    b=before['by_entry_side'][side]
                    delta={k:g[k]-b[k] for k in ('started','entered','completed','exit_seconds','net_btc','net_usd','fees_btc','fees_usd')}
                    delta.update(average_days_to_exit=D(delta['exit_seconds'])/delta['completed']/86400 if delta['completed'] else None,
                        max_stuck_days_to_date=g['max_stuck_days'],current_stuck_days=g['current_stuck_days'],open_entry=g['open_entry'],open_exit=g['open_exit'])
                    result['by_entry_side'][side]=delta
            row['results'][name]=result
        windows.append(row);cut+=test_days*86400
    summaries={}
    for name,sim in engines.items():
        final=sim.snapshot();doubled=stress[name].snapshot();wins=sum(w['results'][name]['advantage_change_usd']>0 for w in windows)
        final.update(winning_windows=wins,test_windows=len(windows),stress_advantage_usd=doubled['advantage_usd'],stress_advantage_btc=doubled['advantage_btc'],
            stress_fees_pct_initial_portfolio=doubled['fees_pct_initial_portfolio'],stress_by_entry_side=doubled['by_entry_side'],
            verdict='REFERENCE' if name=='HOLD50' else verdict(wins,len(windows),final['advantage_usd'],doubled['advantage_usd'],sim.capital),
            verdict_reason='INSUFFICIENT_WINDOWS' if name!='HOLD50' and len(windows)<MIN_TEST_WINDOWS else None)
        summaries[name]=final
        ledger.extend(dict(strategy=name,**r) for r in sim.records)
    return dict(status='EVALUATED' if windows else 'NOT_EVALUATED',reason=None if windows else 'NEED_60_DAY_TRAIN_AND_30_DAY_UNSEEN_TEST',
        windows=windows,strategies=summaries,ledger=ledger)


def fmt(x):return 'UNKNOWN' if x is None else ('0' if x==0 else format(x,'.8g')) if isinstance(x,D) else str(x)


def render(result):
    summaries=result['strategies'];active=[v for k,v in summaries.items() if k!='HOLD50']
    headline='NOT EVALUATED: insufficient or inaccessible synchronized market data.' if not active else 'ALL STRATEGIES NO-GO; recommend HOLD50 under these assumptions.' if all(r['verdict']=='NO-GO' for r in active) else 'Conditional GO candidates require owner review; paper/live not started.'
    lines=['# CoinCat v1.06 M2', '',headline,'','## Design','',
        'Preregistration commit: `'+result.get('design',{}).get('preregistration_commit',PREREGISTRATION_COMMIT)+'`.',
        'Maker 0.5% per filled leg; stress 1.0%. Taker 0.9% is recorded but never used. Fees are native BTC under an explicit model, not exact exchange settlement proof.',
        'Portfolio: simulated $200 initially 50/50 BTC/ETH, unchanged original HOLD50. No-trade HOLD50 is this same baseline, not an independent fourth sample.',
        'Only unseen 30-day windows are headline results; preceding 60 days choose parameters. Continuous OOS inventory/HOLD/stuck cycles carry across windows.',
        'ROUNDTRIP chooses direction once per cycle from total ETH/BTC at BID/ASK mid, including reservations; <=50% ETH means BUY, >50% SELL. No tolerance. Entry replacements keep that side.',
        'ROUNDTRIP_ALTERNATING starts BUY and flips only after completion; it reuses the exact ROUNDTRIP training parameters, dates, funding, fee and fill model without a separate search.',
        'OHLCV has no historical BBO/queue: modeled close +/- one tick; next-bar strict trade-through only, volume-bounded partials, no same-bar exit. No calibrated execution/profit claim.',
        'Missing synchronized bars cancel without fills and preserve inventory; observed drawdown cannot reveal unobserved intragap extremes.',
        'Fee percentage denominator: total starting portfolio value (each window / initial aggregate), never merely trade notional. Long-only time in market is 100%.','',
        '| Strategy | Verdict | Wins/windows | USD advantage | BTC advantage | 2x fees USD advantage | Fees USD | Fees % portfolio | Cycles/day | Avg cycle days | Max stuck days | Misses / submitted | Open cycle | Max DD |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|']
    for name,r in summaries.items():
        decision=r['verdict']+(' ('+r['verdict_reason']+')' if r.get('verdict_reason') else '')
        values=[name,decision,f"{r['winning_windows']}/{r['test_windows']}",r['advantage_usd'],r['advantage_btc'],r['stress_advantage_usd'],r['fees_usd'],r['fees_pct_initial_portfolio'],r['cycles_per_day'],r['average_days_per_cycle'],r['max_stuck_days'],f"{r['misses']}/{r['orders']}",r['open_cycle'],r['max_drawdown']]
        lines.append('| '+' | '.join(map(fmt,values))+' |')
    for name in ROUNDTRIPS:
        if name not in summaries:continue
        r=summaries[name]
        lines+=['',f"{name}: {r['cycles']} completed cycles; {r['trades']} filled orders; {r['partials']} partial-fill events; {r['entry_cancels']} entry cancels / {r['entry_replaces']} replacements; {r['pending_orders']} pending orders.",
            'Completed-cycle modeled profit, marked in USD at completion: '+fmt(r['cycle_profit_usd'])+' USD / '+fmt(r['cycle_profit_btc'])+' BTC. Open inventory is also included in the HOLD comparison.',
            'UTC completed cycles per day: '+str(r['cycles_by_day']),
            'Counts separate started / entry-filled / completed cycles. Average days to exit starts at the entry fill. Net is completed-cycle profit after both own fees; fee totals also include open cycles. Stuck time runs from entry fill, including any still-open cycle.',
            '| Fee scenario | Entry side | Started / entered / completed | Average days to exit | Net USD | Net BTC | Fees USD | Fees BTC | Max stuck days | Current stuck days | Open entry / exit |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for scenario,groups in (('0.5% maker',r['by_entry_side']),('1.0% stress',r['stress_by_entry_side'])):
            for side,g in groups.items():
                values=[scenario,side+'-first',f"{g['started']} / {g['entered']} / {g['completed']}",g['average_days_to_exit'],g['net_usd'],g['net_btc'],g['fees_usd'],g['fees_btc'],g['max_stuck_days'],g['current_stuck_days'],f"{g['open_entry']} / {g['open_exit']}"]
                lines.append('| '+' | '.join(map(fmt,values))+' |')
    lines+=['','| Unseen window | Strategy | USD change vs HOLD | BTC change vs HOLD | Fees % portfolio | Trades / fill events | Misses | Max DD | Selected parameters |','|---|---|---:|---:|---:|---|---:|---:|---|']
    for w in result['windows']:
        for name,r in w['results'].items():
            values=[w['start_utc']+' to '+w['end_utc'],name,r['advantage_change_usd'],r['advantage_change_btc'],r['fees_pct_starting_portfolio'],str(r['trades'])+' / '+str(r['fills']),r['misses'],r['max_drawdown'],str(r['selected_params'])]
            lines.append('| '+' | '.join(map(fmt,values))+' |')
    lines+=['','Entry cancels/replaces, native fees, partials, pending orders, gaps, wallet and full simulated ledger: backtest_results.json.',
        'GO: >=10 unseen test windows, >=60% winning windows, final advantage over HOLD50 >=1% of the starting portfolio, and nonnegative doubled-fee advantage. Fewer windows or a smaller gain => NO-GO. Stress uses the same base-training choices. Open losses are included. Stop for owner review.']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=ROOT/'v106_out'/'data');p.add_argument('--fees',type=Path,default=ROOT/'v106_out'/'fees.json')
    p.add_argument('--output',type=Path,default=ROOT/'v106_out');a=p.parse_args(argv);a.output.mkdir(parents=True,exist_ok=True)
    fees=json.loads(a.fees.read_text());f=fees.get('fees') or {}
    if fees.get('status')!='VERIFIED' or fees.get('product_id')!='ETH-BTC' or exact(f.get('maker_rate'))!=MAKER or exact(f.get('taker_rate'))!=TAKER:
        raise ValueError('Verified M0 rates must match the preregistered 0.5% / 0.9%; never substitute fees')
    rules=fees['product']
    try:
        summary=json.loads((a.data/'export_summary.json').read_text())
        if summary.get('status')!='COMPLETE':result=dict(status='NOT_EVALUATED',reason='M1_EXPORT_INCOMPLETE',windows=[],strategies={})
        else:frames=load_frames(a.data,rules);result=study(frames,rules,progress=lambda text:print(text,flush=True))
    except FileNotFoundError:result=dict(status='NOT_EVALUATED',reason='M1_CSV_FILES_NOT_AVAILABLE',windows=[],strategies={})
    result['m0_sha256']=hashlib.sha256(a.fees.read_bytes()).hexdigest()
    result['data_hashes']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in a.data.glob('*_5m.csv')}
    result['design']=dict(maker=str(MAKER),taker_recorded_not_used=str(TAKER),stress=str(FEE_STRESS),train_days=TRAIN_DAYS,test_days=TEST_DAYS,
        preregistration_commit=PREREGISTRATION_COMMIT,original_preregistration_commit='78f70fa',
        direction_preregistration_commit='4dc4ca83d491c2f3fcf54889055ce914d7ca6400',
        minimum_test_windows=MIN_TEST_WINDOWS,minimum_advantage_fraction=str(MIN_ADVANTAGE_FRACTION),
        preregistration_sha256=hashlib.sha256((Path(__file__).with_name('preregistered.py')).read_bytes()).hexdigest(),
        source_fraction=str(SOURCE_FRACTION),entry_side=ENTRY_SIDE,grids={n:grid(n) for n in STRATEGIES},
        alternating_side=ALTERNATING_SIDE,alternating_parameters=ALTERNATING_PARAMETERS,
        quote_model='CLOSE_PLUS_MINUS_ONE_TICK_UNCALIBRATED',live_authority=False)
    # Decimal strings preserve exact native arithmetic in private model results.
    (a.output/'backtest_results.json').write_text(json.dumps(result,default=str,indent=2)+'\n',encoding='utf-8')
    (a.output/'backtest_report.md').write_text(render(result),encoding='utf-8')
    print(render(result).split('\n')[2]);print('Saved backtest_report.md; stop after M2. No paper/live orders.')
    return 0 if result['status']=='EVALUATED' else 1


if __name__=='__main__':raise SystemExit(main())
