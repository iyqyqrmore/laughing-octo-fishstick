"""Archived advisory SYNTHETIC selection replay; NOT primary v80 movement.

Run: python -B tools/replay_cost_selection.py
Both policies use the canonical Decimal planner and segregated RAM FIFO.
The archived repeat-momentum rule is called only by this offline comparator.
Prices/features are artificial; outputs cannot establish predictive value.
"""
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import json,sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from coincat_live_forward_store import ForwardStore
from coincat_multicurrency import evaluate_rotation
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio
from coincat_v703_chain import rank_experimental,legacy_repeat_score
from coincat_v706_selection import assess

START=1800000000
FEE=D('.009')
PRINCIPAL=D(1000)
CAP=D(10)
RULES={'BTC-USD':dict(product_type='SPOT',status='online',
    base_increment='.00000001',base_min_size='.00000001',quote_min_size='.00001')}


def path(name,steps=240):
    if name=='flat':return [D(100)]*(steps+1)
    if name=='reversing_rebounds':
        # Every positive 30-second jump reverses at the next observation.
        return [D(100)*(D('1.025') if n%2 else 1) for n in range(steps+1)]
    if name=='artificial_continuation':return [D(100)*D('1.006')**n for n in range(steps+1)]
    if name=='continuation_then_reversal':
        return [D(100)*D('1.006')**min(n,100)*D('.994')**max(0,n-100) for n in range(steps+1)]
    if name=='one_jump_then_flat':return [D(100)]+[D(103)]*steps
    raise ValueError(name)


def costed(wallet,quotes,stamp,momentum):
    amount=wallet.balances().get('USD',D(0))
    if amount<=0:return None
    result=evaluate_rotation(source='USD',target='BTC',authorized_qty=amount,
        verified_available_qty=amount,balance_age_s=0,catalog=list(RULES),quotes=quotes,
        now=stamp,usd_per_order_cap=min(CAP,amount),product_rules=RULES,
        fee_rate=FEE,max_legs=1)
    if not result['routes']:return None
    r=result['routes'][0]
    return dict(source='USD',target='BTC',trigger_pair='BTC-USD',route=r['route'],
        shadow_fifo_steps=r['steps'],input_units_planned=r['input_units_planned'],
        destination_units_estimate=r['destination_units_estimate'],
        immediate_change_usd=r['immediate_change_usd'],research_size_cap_usd=CAP,
        observed_momentum_pct=momentum,sends_live_orders=False,oos_validated=False)


def replay(name):
    prices=path(name);counts={'repeat_momentum':0,'forward_cost':0};used=set()
    timings=[]
    with TemporaryDirectory(prefix='coincat-synthetic-replay-') as folder:
        store=ForwardStore(Path(folder)/'public.sqlite')
        wallets={label:ShadowFIFOPortfolio({'USD':str(PRINCIPAL)},{'USD':'1'},label=label) for label in counts}
        try:
            for n,price in enumerate(prices):
                stamp=START+n*30
                quotes={'BTC-USD':(price,price*D('1.0001'),stamp)}
                momentum=(price/prices[n-1]-1)*100 if n else D(0)
                stream={'rows':[dict(pair='BTC-USD',change_30s_pct=momentum,age_ms=0)]}
                tick=perf_counter()
                store.selection.observe(catalog=list(RULES),quotes=quotes,snapshot=stream,
                    now=stamp,observed_pairs=quotes)
                evidence=store.selection.forecasts(pairs=quotes,snapshot=stream,now=stamp)
                timings.append((perf_counter()-tick)*1000)
                rates={'USD':D(1),'BTC':price}
                for label,wallet in wallets.items():
                    idea=costed(wallet,quotes,stamp,momentum)
                    if idea is None:continue
                    idea=rank_experimental([idea],quotes,stamp,forward_evidence=evidence)[0]
                    if label=='repeat_momentum':
                        score=legacy_repeat_score(idea);key=None
                    else:
                        decision=assess(idea,now=stamp);score=decision['score_usd'];key=decision['evidence_key']
                    if score is None or score<=0 or (key is not None and key in used):continue
                    data=wallet.post_hypothetical_route(session_id=f'SHADOW-SYNTHETIC-{label}-{n}',
                        steps=idea['shadow_fifo_steps'],usd_rates=rates,at_utc=stamp)
                    if data['state']=='SHADOW_FIFO_POSTED':
                        counts[label]+=1
                        if key is not None:used.add(key)
            output={'scenario':name,'data':'ARTIFICIAL_SYNTHETIC_NOT_MARKET_DATA',
                'policy_role':'ARCHIVED_ADVISORY_COUNTERFACTUAL_NOT_PRIMARY_V80',
                'connected_strict_qualification_available':False,
                'minutes':(len(prices)-1)*.5,'taker_fee_rate':str(FEE),
                'slippage_bps':'15','spread_fraction':'.0001','initial_usd':str(PRINCIPAL),
                'observation_summary':store.selection.summary()['observations'],'policies':{}}
            for label,wallet in wallets.items():
                totals=wallet.mark_vs_hold({'USD':D(1),'BTC':prices[-1]})
                output['policies'][label]={'conversions':counts[label],
                    'estimated_fees_usd':wallet.fees_estimated_usd,
                    'wallet_vs_hold_usd':totals['delta_usd'],
                    'quantity_parity':wallet.quantity_parity()}
            timings.sort()
            output['passive_learning_ms']={'median':round(timings[len(timings)//2],3),
                'p95':round(timings[int((len(timings)-1)*.95)],3)}
            return output
        finally:
            for wallet in wallets.values():wallet.close()


def run():
    return {'warning':'Synthetic causal plumbing/comparison only; no profit or forecast validation.',
        'real_order_submissions':0,'scenarios':[replay(name) for name in
        ('flat','one_jump_then_flat','reversing_rebounds','artificial_continuation','continuation_then_reversal')]}


if __name__=='__main__':print(json.dumps(run(),indent=2,default=str))
