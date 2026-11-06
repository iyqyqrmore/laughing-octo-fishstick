"""Fixed chronological synthetic paths; model exercises, never market backtests.

Run from a source checkout with --output outside it. No SDK client, keys or
account data is opened. Every case starts with the same fictional $500 HOLD.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,csv,json,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
from coincat_assumed_math import rounded
from coincat_opportunity_policy import OpportunityConfig
from coincat_opportunity_trader import OpportunityTrader,active
from coincat_trial_clock import NS
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

CASES=('flat_no_edge','trend_no_fills','trend_conditional_fills','reversal_conditional_fills',
    'high_fees_no_edge','trade_gap_and_restart')

class ScenarioClock:
    def __init__(self):self.at=1793980800.;self.mono=0
    def wall(self):return self.at
    def ns(self):return self.mono
    def tick(self,seconds):self.at+=seconds;self.mono+=round(seconds*NS)

def frame(clock,step,*,high_fees=False):
    cross=D('.03')*D('.999')**step
    mids={'ETH-BTC':cross,'ETH-USD':D(2000),'ADA-ETH':D('.0004'),'LINK-ETH':D('.005'),'SOL-ETH':D('.05')}
    for asset in ('ADA','LINK','SOL'):mids[asset+'-BTC']=mids[asset+'-ETH']*cross
    books={};tick=D('.000000000001')
    for pair,price in mids.items():
        bid=rounded(price*D('.9999'),tick);ask=rounded(price*D('1.0001'),tick,up=True)
        books[pair]=dict(pair=pair,at=clock.wall(),bid=bid,ask=ask,
            bids=((bid,D('.000001')),(bid-tick,D(100000))),asks=((ask,D('.000001')),(ask+tick,D(100000))))
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,base_increment='.000001',
        quote_increment='.000000000001',price_increment='.000000000001',base_min_size='.000001',quote_min_size='.000000001') for p in WATCH_PAIRS}
    rate=D('.04') if high_fees else D('.005')
    return dict(state='OBSERVED',at=clock.wall(),portfolio='SYNTHETIC_ONLY',books=books,rules=rules,
        tier=dict(at=clock.wall(),maker=rate,taker=D('.04') if high_fees else D('.009'),source='AUTHENTICATED_ACCOUNT_TIER'),
        market_trades=None,trade_status='SYNTHETIC_UNSUPPLIED')

def run_case(name,*,waves=181):
    if name not in CASES:raise ValueError('Unknown fixed scenario')
    c=ScenarioClock();tape=[];public={p:[] for p in WATCH_PAIRS}
    config=replace(OpportunityConfig(),size_percent={p:D(5) for p in WATCH_PAIRS},
        provider='NO_FILL_OBSERVATION_V1' if name=='trend_no_fills' else 'TRADE_THROUGH_QUEUE_V1')
    with TemporaryDirectory(prefix='CoinCat_Opportunity_Synthetic_') as data:
        path=Path(data)/'trial.sqlite3';e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns);e.start(config)
        frozen=None
        for i in range(waves):
            step=0 if name=='flat_no_edge' else i//3
            if name=='reversal_conditional_fills' and i>=90:step=30-3*((i-90)//3)
            if name=='trade_gap_and_restart' and i==100:
                e.shutdown();before=deepcopy(e.state());hours=e.progress()['valid_seconds'];c.tick(3600);c.mono=0
                e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns)
                assert not e.load_error and e.state()['wallet']==before['wallet'] and e.progress()['valid_seconds']==hours
            f=frame(c,step,high_fees=name=='high_fees_no_edge');o=active(e.state()) if e.state() else None
            if o is not None:
                pair=o['pair'];prints=public[pair]
                if name=='trade_gap_and_restart' and i==80:prints=[]
                # Synthetic print excursions exercise the declared queue model.
                # They are input events, not fills inferred from these books.
                price=o['price']+(D('.000000000001') if o['side']=='SELL' else -D('.000000000001'))
                prints.append(dict(id=f'synthetic-{i}',price=price,size=D(10),at=c.wall()));public[pair]=prints[-100:]
                f['market_trades']=dict(pair=pair,at=c.wall(),prints=deepcopy(public[pair]),source='SYNTHETIC_PUBLIC_TRADE_TAPE')
            e.review(f);s=e.state()
            if frozen is None:frozen=deepcopy(s['original'])
            assert s['original']==frozen
            perf=s['last_performance'] or {}
            tape.append(dict(wave=i,elapsed_s=i*10,valid_s=e.progress()['valid_seconds'],orders=s['metrics']['orders'],
                fills=s['metrics']['fill_events'],portfolio_usd=perf.get('portfolio_usd'),hold_usd=perf.get('hold_usd'),
                advantage_usd=perf.get('advantage_usd'),paid_fee_usd=s['metrics']['fees_usd_at_fill'],max_drawdown=s['max_drawdown']))
            c.tick(10)
        e.pause();c.tick(3);e.heartbeat(persist=True);s=e.state();p=s['last_performance']
        summary=dict(case=name,classification='SYNTHETIC_CONDITIONAL_MODEL_NOT_PROFITABILITY_EVIDENCE',
            config=asdict(config),initial_usd=s['initial_usd'],original=s['original'],wallet=s['wallet'],performance=p,
            metrics=s['metrics'],native_fees=s['fees_native'],max_drawdown=s['max_drawdown'],progress=e.progress())
        e.shutdown();return summary,tape

def serial(value):
    if isinstance(value,D):return str(value)
    raise TypeError(type(value).__name__)

def render(summaries):
    lines=['# CoinCat v1.04 — fixed synthetic opportunity scenarios','',
        'These are deterministic engineering scenarios, not historical market backtests or evidence of predictive profitability.',
        'All cases start with $100 each in BTC, ETH, SOL, LINK and ADA. The immutable original quantities are marked on each same path.',
        'The scenario size is 5% of free source inventory; the application default remains native minimum. Fees: synthetic 0.5% maker, 0.9% future-exit benchmark; high-fee case uses 4%.',
        'The policy is frozen before each forward path: 21 observations, 30-second reviews, 120-second reconsideration, 600-second child life, 1,800-second campaign life and three replacement attempts.',
        'Conditional print excursions deliberately exercise the queue provider; 2x visible queue, 10% participation, 30-second rest, three strict-through prints and 25% child-size partial cap are uncalibrated assumptions.',
        'Paid leg fees are deducted once. Future exit estimates reduce admission advantage but are not booked. End values use midpoint marks after paid fees, before unexecuted exits. No final liquidation is forced.','',
        '| Scenario | Orders | Fill events | Nonfills | Fees USD at fill | Portfolio USD | Original HOLD USD | Net advantage USD | Max marked drawdown |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in summaries:
        p=s['performance'];m=s['metrics']
        lines.append('| '+s['case']+' | '+str(m['orders'])+' | '+str(m['fill_events'])+' | '+str(m['nonfills'])+' | '+
            f"{m['fees_usd_at_fill']:.6f} | {p['portfolio_usd']:.6f} | {p['hold_usd']:.6f} | {p['advantage_usd']:.6f} | {s['max_drawdown']*100:.4f}% |")
    lines+=['','Rejections, no fills, adverse reversals, native commissions, open inventory and restart downtime remain in the JSON/CSV evidence. No case changes HOLD to the traded wallet.',
        'The favorable synthetic trend is not a calibrated fill model or validation of the trailing-return forecast. Live or historical holdout evidence is still required.','']
    return '\n'.join(lines)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve()
    if output==ROOT or ROOT in output.parents:raise ValueError('Keep generated evidence outside the checkout')
    output.mkdir(parents=True,exist_ok=True);summaries=[]
    for name in CASES:
        summary,tape=run_case(name);summaries.append(summary)
        with (output/(name+'.csv')).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(tape[0]));writer.writeheader();writer.writerows(tape)
    (output/'summary.json').write_text(json.dumps(summaries,default=serial,indent=2)+'\n',encoding='utf-8')
    report=render(summaries);(output/'comparison.md').write_text(report,encoding='utf-8');print(report)

if __name__=='__main__':main()
