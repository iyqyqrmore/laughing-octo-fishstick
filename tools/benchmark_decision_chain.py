"""Reproducible SYNTHETIC planner CPU benchmark; never contacts Coinbase.

Run with Python 3.11: python -B tools/benchmark_decision_chain.py [--profile]
Includes the background SELL advisory to match the earlier comparison. Urgent
decisions defer that advisory. Timing excludes HTTP, GUI, fills and P&L export.
"""
from pathlib import Path
import cProfile
import json
import pstats
import sys
from decimal import Decimal as D
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from coincat_v605_shadow_bridge import shadow_screen


def fixture(total=804,targets=3):
    now=1800000000
    sources=[f'F{i:02}' for i in range(22)]
    destinations=[f'T{i:02}' for i in range(targets)]
    prices={a:D(50+i) for i,a in enumerate(sources)}
    prices.update({a:D(10+i) for i,a in enumerate(destinations)})
    prices['USD']=D(1)
    quotes={};rules={}
    def product(a,b):
        pair=a+'-'+b;price=prices[a]/prices[b]
        quotes[pair]=(price*D('.99995'),price*D('1.00005'),now)
        rules[pair]={'product_type':'SPOT','base_increment':'.00000001',
                     'base_min_size':'.00000001','quote_min_size':'.00001'}
    for a in sources+destinations:product(a,'USD')
    for a in destinations:
        for b in sources:product(a,b)
    i=0
    while len(rules)<total:
        a=f'Z{i:04}';prices[a]=D(1);product(a,'USD');i+=1
    balances={a:'2' for a in sources};balances['USD']='300'
    return dict(balances=balances,excluded=(),buy_signals=(),age_s=5,
        catalog=list(rules),quotes=quotes,product_rules=rules,
        portfolio_usd_cap=D('1e24'),now=now,
        fee_rates_by_pair={p:D('.009') for p in rules},
        relative_evidence=lambda *a,**kw:{'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0},
        exploratory_candidates=[{'pair':a+'-USD','momentum_pct':D('2.4'),
                                 'action':'EXPLORE_ONLY'} for a in destinations],
        direct_only=True,max_targets=targets)


if __name__=='__main__':
    args=fixture()
    profile=cProfile.Profile();start=perf_counter()
    result=profile.runcall(shadow_screen,**args)
    print(json.dumps({'fixture':'SYNTHETIC','products':len(args['catalog']),
        'funding_assets':len(args['balances']),'targets':3,
        'costed_size_attempts':result['exploratory_route_attempts'],
        'returned_ranked_ideas':len(result['ideas']),
        'profiled_planner_seconds':round(perf_counter()-start,4),
        'live_order_submissions':0},sort_keys=True))
    if '--profile' in sys.argv:pstats.Stats(profile).sort_stats('cumulative').print_stats(16)
