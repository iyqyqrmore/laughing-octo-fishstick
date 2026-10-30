"""ETH funding/settlement topology for every approved market direction.

No quantities, quotes, requests, costs, ranking or execution authority. Connected
does not mean executable or profitable. Every reported cycle starts/ends in ETH.
"""
from collections import deque
from coincat_v703_chain import approved_pairs


def eth_cycle_inventory(*,catalog,rules,excluded=(),sample_limit=12):
    listed=approved_pairs(catalog,rules,excluded)
    edges={};directions=[]
    for pair in listed:
        base,quote=pair.split('-')
        for side,source,target in (('SELL',base,quote),('BUY',quote,base)):
            leg=(pair,side,source,target)
            edges.setdefault(source,[]).append(leg);directions.append(leg)
    # Stable, price-independent shortest listed funding paths. Reverse legs
    # use BUY/SELL on the same real product, never invented inverse products.
    funding={'ETH':()};queue=deque(['ETH'])
    while queue:
        source=queue.popleft()
        for leg in sorted(edges.get(source,())):
            if leg[3] not in funding:
                funding[leg[3]]=funding[source]+(leg,);queue.append(leg[3])
    possible=[];blocked=[];results=[];connected=bounded=beyond=disconnected=0
    for candidate in sorted(directions):
        pair,side,source,target=candidate
        row={'product':pair,'side':side,'source':source,'target':target}
        if source not in funding or target not in funding:
            disconnected+=1;row.update(state='DISCONNECTED',reason='NO_ETH_CONNECTION_IN_APPROVED_CATALOG')
            results.append(dict(row))
            if len(blocked)<sample_limit:blocked.append(row)
            continue
        connected+=1
        prefix=funding[source];outward=funding[target]
        if len(prefix)>2 or len(outward)>2:
            beyond+=1;row.update(state='CONNECTED_BEYOND_MODEL',reason='CONNECTED_BUT_BEYOND_TWO_LEG_BRIDGE_MODEL',
                funding_legs=len(prefix),return_legs=len(outward))
            results.append(dict(row))
            if len(blocked)<sample_limit:blocked.append(row)
            continue
        suffix=tuple((p,'BUY' if s=='SELL' else 'SELL',t,f) for p,s,f,t in reversed(outward))
        cycle=prefix+(candidate,)+suffix
        assets=['ETH']
        for product,direction,from_asset,to_asset in cycle:
            if from_asset!=assets[-1]:raise ValueError('ETH_CYCLE_TOPOLOGY_DISCONTINUITY')
            assets.append(to_asset)
        if assets[-1]!='ETH' or 'ETH' in assets[1:-1]:
            raise ValueError('ETH_CYCLE_TERMINAL_CONFLICT')
        bounded+=1
        row.update(state='BOUNDED_TOPOLOGY_ONLY',funding_legs=len(prefix),return_legs=len(suffix),total_legs=len(cycle))
        results.append(dict(row))
        if len(possible)<sample_limit:
            row.update(assets=assets,legs=[{'product':p,'side':s,'source':f,'target':t} for p,s,f,t in cycle],
                funding_legs=len(prefix),return_legs=len(suffix),total_legs=len(cycle))
            possible.append(row)
    return {'state':'TOPOLOGY_ONLY_NOT_TRADE_QUALIFICATION','funding_asset':'ETH','terminal_asset':'ETH',
        'scope':'ALL_APPROVED_MARKET_DIRECTIONS_REGARDLESS_OF_ACCOUNT_HOLDINGS',
        'approved_markets':len(listed),'directions_checked':len(directions),
        'eth_connected_directions':connected,'bounded_eth_cycles':bounded,
        'beyond_bridge_model_directions':beyond,'disconnected_directions':disconnected,
        'all_directions_classified':bounded+beyond+disconnected==len(directions),
        'direction_results':results,'cycle_examples':possible,'blocked_examples':blocked,'example_limit':sample_limit,
        'all_cycles_start_and_end_in_eth':True,'max_bridge_legs':2,'max_total_legs':5,
        'costs_and_native_sizing':'UNVERIFIED','funding_authorization':'NOT_ESTABLISHED_BY_TOPOLOGY',
        'eth_profit_selection_enabled':False,'live_order_permission':False}
