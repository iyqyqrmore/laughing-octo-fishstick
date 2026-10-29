"""One full-available native receipt per direction, ranked by immediate USD W.

The existing canonical pricing/receipt calculation owns all economics. No
portfolio cap, fractional size search, forecast, order call or modeled wallet.
"""
from collections import Counter
from decimal import Decimal, localcontext

from coincat_cross_quote import usd_conversion, split_spot
from coincat_v703_chain import approved_pairs
from coincat_v80_immediate import _prepare, _frame, exact


def rank_full_balances(*, balances, catalog, rules, quotes, fee_rate, now,
                       balances_at, excluded=()):
    result={'at':float(now),'policy':'GREATEST_IMMEDIATE_USD_ADVANTAGE_FULL_AVAILABLE',
        'state':'WAIT','reason':'NO_POSITIVE_IMMEDIATE_ADVANTAGE','best':None,'ranked':[],
        'eligible_directions':0,'priced_directions':0,'positive_directions':0,
        'blockers':{},'live_order_permission':False}
    if balances_at is None or not 0<=now-balances_at<=120:
        return dict(result,reason='AVAILABLE_BALANCES_STALE_OR_UNOBSERVED')
    try:
        fee=exact(fee_rate)
        if not 0<=fee<Decimal('.05'):raise ValueError()
    except (ValueError,TypeError,ArithmeticError):
        return dict(result,reason='FEE_ESTIMATE_UNAVAILABLE')
    excluded=set(excluded)
    blockers=Counter()
    with localcontext() as ctx:
        ctx.prec=60
        prepared=_prepare(quotes,rules,now)
        clean=prepared['books']
        for pair in approved_pairs(catalog,rules,excluded):
            base,quote=split_spot(pair)
            for side,source,target in (('BUY',quote,base),('SELL',base,quote)):
                if source in excluded or target in excluded:continue
                try:available=exact(balances.get(source,'0'))
                except (ValueError,TypeError,ArithmeticError):
                    blockers['INVALID_AVAILABLE_QUANTITY']+=1;continue
                if available<=0:continue
                result['eligible_directions']+=1
                if pair not in clean:
                    blockers['CONVERSION_BOOK_MISSING_STALE_OR_WIDE']+=1;continue
                cache=prepared.setdefault('wallet_fx',{})
                if source not in cache:cache[source]=usd_conversion(source,{p:clean[p] for p in sorted(clean)},now=now,max_age=30,max_legs=2)
                fx=cache[source]
                if fx is None:
                    blockers['INDEPENDENT_USD_PATH_MISSING']+=1;continue
                # The cap is exactly the full source's current mark, never an
                # arbitrary USD budget or an attempted smaller size.
                cap=available*fx['rate']
                idea={'source':source,'target':target,'source_units':available,
                    'research_size_cap_usd':cap,'sends_live_orders':False,
                    'route':[(pair,side,source,target)],'shadow_fifo_steps':[
                        {'pair':pair,'side':side,'fee_rate_used':fee,'approx_usd_notional':cap}]}
                try:
                    frame=_frame(idea,quotes,rules,float(now),prepared=prepared,include_liquidation=False,valuation_policy='CONSISTENT_WALLET_MARKS')
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'FULL_SIZE_PRODUCT_OR_FRAME_BLOCK'
                    blockers[reason]+=1;continue
                receipt=frame['idea']['shadow_fifo_steps'][0]
                result['ranked'].append({'pair':pair,'side':side,'source':source,'target':target,
                    'available':available,'spent':receipt['input_quantity'],
                    'residual':available-receipt['input_quantity'],
                    'received':receipt['output_quantity'],'w':frame['w'],'frame':frame,
                    'state':'MODELED_POSITIVE_UNVERIFIED' if frame['w']>0 else 'NO_IMMEDIATE_ADVANTAGE',
                    'estimated_fee_usd':frame['entry_fee_usd_estimate'],
                    'spread_pct':(clean[pair][1]-clean[pair][0])/clean[pair][1]*100,
                    'slippage_reserve_pct':receipt['modeled_slippage_fraction']*100,
                    'depth_impact':'UNKNOWN','fee_units_verified':False})
        result['ranked'].sort(key=lambda row:(-row['w'],row['pair'],row['side']))
    result['priced_directions']=len(result['ranked'])
    result['positive_directions']=sum(row['w']>0 for row in result['ranked'])
    result['blockers']=dict(blockers)
    if result['positive_directions']:
        result.update(state='MODELED_POSITIVE_UNVERIFIED',reason='POSITIVE_FULL_BALANCE_ESTIMATE',best=result['ranked'][0])
    elif result['ranked']:
        result['state']='HOLD'
    return result
