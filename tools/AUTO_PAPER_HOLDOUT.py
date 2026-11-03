"""Chronological SYNTHETIC holdout stress comparison, never market backtest proof."""
import argparse
import json
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]


def observations(*,adverse):
    from coincat_adaptive_eth import Frame
    from coincat_watchlist import WATCH_PAIRS,schedule_books
    start=1800000000
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,
        base_increment='.0001',quote_increment='.00000001',price_increment='.0001',
        base_min_size='.0001',quote_min_size='.00000001') for p in WATCH_PAIRS}
    for index,offset in enumerate(range(0,7231,30)):
        at=start+offset;selected,_=schedule_books(WATCH_PAIRS,index)
        # Prices are fixed before evaluation; no scenario inspects strategy
        # positions or selects a favorable later exit. The first 600 seconds
        # are a declared development-only prefix and are never scored.
        if offset<690:price=D(1)
        elif adverse or offset<4200:price=D('1.02')
        else:price=D('.95')
        books={p:(price,price+D('.001'),at) if p=='ETH-BTC' else (D(1),D('1.001'),at) for p in selected}
        yield Frame(at,WATCH_PAIRS,rules,books,dict(fresh=True,captured_at=at,maker=D('.005'),taker=D('.009')))


def evaluate(*,seeds=(1,7,19),models=None,emit=print,policy='PATIENT_MAKER_ETH_V1'):
    from coincat_auto_paper import AutoPaper
    from coincat_paper_policy import AutoConfig,MODELS,direction_defaults
    from coincat_working_allocation import AllocationRow
    from unittest.mock import patch
    models=MODELS if models is None else tuple(models)
    results=[]
    for adverse in (False,True):
        dataset=tuple(observations(adverse=adverse));development=dataset[:20];holdout=dataset[20:]
        assert development[-1].at<holdout[0].at
        for model in models:
            for seed in seeds:
                # Shared run ID makes seed/model comparisons reproducible. Each
                # run has ONE wallet for all 14 views, not 14 funded accounts.
                with TemporaryDirectory(prefix='CoinCat_Holdout_') as folder,patch(
                        'coincat_auto_paper.uuid.uuid4',return_value=uuid.UUID(int=1)):
                    cfg=AutoConfig(D(1),direction_defaults(),opt_in=True,model=model,seed=seed,duration_s=6600,policy=policy)
                    manager=AutoPaper(Path(folder));manager.create(cfg,at=holdout[0].at,
                        funding=dict(balances={'ETH':D(1)},balances_at=holdout[0].at,draft=(AllocationRow('ETH',D(1)),)))
                    frozen=manager.engine.private_state()['auto']['config']
                    evaluation_state=None;evaluation_public=None
                    for frame in holdout:
                        manager.on_frame(frame)
                        snapshot=manager.engine.private_state()
                        if evaluation_state is None and snapshot['auto']['horizon'] is not None:
                            evaluation_state=snapshot;evaluation_public=manager.public()
                    state=evaluation_state or manager.engine.private_state();context=state['auto']
                    performance=(context['horizon'] or {}).get('metrics') or context['performance']
                    assert context['config']==frozen
                    partial_events=0;partial_orders=set();completion_times=[]
                    for reference,order in state['orders'].items():
                        fills=sorted((f for f in state['fills'].values() if f['settled'] and f['reference']==reference),
                            key=lambda f:f['settle_index'])
                        cumulative=D(0)
                        for fill in fills:
                            cumulative+=fill['raw']['size']
                            if cumulative<order['base_size']:
                                partial_events+=1;partial_orders.add(reference)
                        if order['state']=='FILLED':completion_times.append(fills[-1]['raw']['at']-order['created_at'])
                    result=dict(scenario='ADVERSE_UNRECOVERED' if adverse else 'LATER_PRICE_RETURN',model=model,seed=seed,policy=policy,
                        observations=len(holdout),development_observations=len(development),
                        **{k:v for k,v in (evaluation_public or manager.public()).items() if k in ('orders','fills','non_fills','partials','gaps','state')},
                        partial_fill_events=partial_events,orders_with_partial_fills=len(partial_orders),
                        orders_with_no_fills=sum(o['filled_base']==0 for o in state['orders'].values()),
                        open_orders=sum(o['state'] not in ('FILLED','CANCELED','REJECTED') for o in state['orders'].values()),
                        completed_order_times_s=completion_times,
                        horizon=context['horizon'],realized_paper_delta_eth=performance['realized_paper_delta_eth'],
                        midpoint_delta_eth=performance['midpoint_delta_eth'],max_midpoint_drawdown_pct=performance['max_midpoint_drawdown_pct'],
                        observed_underwater_s=performance['observed_underwater_s'],fees=performance['fees'],
                        recoverable_eth=performance['recoverable_eth'],unobserved_s=performance['unobserved_s'],
                        actual_profit_eth=None,edge='NO_DEMONSTRATED_EDGE',review_required=manager.last_problem is not None,
                        final_reason=context['last_reason'])
                    results.append(result);emit(result)
    return results


def main():
    from coincat_paper_policy import POLICY,POLICIES
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true',required=True,
        help='Acknowledge these are declared fictitious prices, fees and scenario executions')
    parser.add_argument('--policy',choices=POLICIES,default=POLICY)
    args=parser.parse_args()
    print('CoinCat v1.02 — SYNTHETIC uncalibrated holdout exercise. No account or network.')
    print('Historical policy harness, not the global USD admission gate. Selected policy:',args.policy)
    print('Policy/model parameters fixed before chronological holdout; no tuning or future-price selection.')
    results=evaluate(policy=args.policy,emit=lambda row:print(json.dumps(row,default=str,sort_keys=True)))
    print('Runs:',len(results),'Actual verified exchange fills: 0. NO DEMONSTRATED EDGE.')
    print('Marked deltas are midpoint references; missing depth/fee units/dust keeps recoverable ETH UNKNOWN.')
    return 0


if __name__=='__main__':raise SystemExit(main())
