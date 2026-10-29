"""Canonical immediate wallet/optional liquidation frame; no order or wallet posting.

Historical receipt-key names remain compatibility carriers, not active shadow modes.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib

from coincat_cross_quote import split_spot, usd_conversion
from coincat_multicurrency import research_order, ResearchDepthError
from coincat_v701_quotes import valid_book

D = Decimal


def exact(value):
    if isinstance(value,(float,bool)):raise ValueError('Exact decimal required')
    n=D(str(value))
    if not n.is_finite():raise ValueError('Nonfinite financial input')
    return n


def _prepare(quotes,rules,now):
    from coincat_v703_chain import approved_pairs
    listed=set(approved_pairs(list(quotes),rules))
    return {'books':{p:b for p,raw in quotes.items() if p in listed and
        (b:=valid_book(raw,now,30,D('.0025'))) is not None},'fx':{},'at':float(now)}


def _frame(idea, quotes, rules, now, depth=None,prepared=None,*,include_liquidation=True,valuation_policy='INDEPENDENT_ROUTE_PATHS'):
    """Reprice through the SAME canonical native order-receipt implementation."""
    steps=idea.get('shadow_fifo_steps') or ()
    if len(steps)!=1 or idea.get('sends_live_orders') is not False:raise ValueError('NOT_SINGLE_RESEARCH_ORDER')
    original=steps[0];pair=original['pair'];base,quote=split_spot(pair)
    side=original['side'];src=quote if side=='BUY' else base
    dst=base if side=='BUY' else quote
    if side not in ('BUY','SELL') or (src,dst)!=(idea.get('source'),idea.get('target')):
        raise ValueError('RECEIPT_CURRENCY_CONFLICT')
    prepared=_prepare(quotes,rules,now) if prepared is None else prepared
    if prepared['at']!=float(now):raise ValueError('STALE_DECISION_CONTEXT')
    clean=prepared['books']
    if pair not in clean:raise ValueError('CONVERSION_BOOK_MISSING_STALE_OR_WIDE')
    forbidden=() if 'USD' in (base,quote) else (pair,)
    fx_cache=prepared['fx']
    def fx(asset):
        if valuation_policy=='CONSISTENT_WALLET_MARKS':
            wallet_cache=prepared.setdefault('wallet_fx',{})
            if asset not in wallet_cache:
                wallet_cache[asset]=usd_conversion(asset,{p:clean[p] for p in sorted(clean)},now=now,max_age=30,max_legs=2)
            mark=wallet_cache[asset]
            if mark is None:raise ValueError('INDEPENDENT_USD_PATH_MISSING')
            if forbidden and pair in mark['path']:raise ValueError('CIRCULAR_WALLET_MARK_PATH')
            return mark
        key=(asset,pair)
        if key not in fx_cache:
            fx_cache[key]=usd_conversion(asset,clean,now=now,max_age=30,max_legs=2,excluded_pairs=(pair,))
            if fx_cache[key] is None and not forbidden:
                fx_cache[key]=usd_conversion(asset,clean,now=now,max_age=30,max_legs=2)
        if fx_cache[key] is None:raise ValueError('INDEPENDENT_USD_PATH_MISSING')
        return fx_cache[key]
    source_fx=fx(src);target_fx=fx(dst)
    dependency=set((pair,)+source_fx['path']+target_fx['path'])
    stamps=[clean[p][2] for p in dependency]
    if max(stamps)-min(stamps)>12:raise ValueError('PRICE_SKEW')
    fee=exact(original['fee_rate_used'])
    available=exact(idea.get('source_units',idea.get('input_units_planned')))
    cap=exact(idea.get('research_size_cap_usd',original['approx_usd_notional']))
    allocated=min(available,cap/source_fx['rate'])
    orders=[];retained=[]
    def order(product,direction,quantity,rate):
        if product not in clean:raise ValueError('PATH_BOOK_MISSING')
        level=None
        if depth is not None:
            row=depth.get(product)
            if row is None:raise ResearchDepthError('DEPTH_MISSING')
            if row.get('pair')!=product or float(row.get('observed_at',-1))!=clean[product][2]:
                raise ResearchDepthError('DEPTH_FRAME_CONFLICT')
            level=row.get('asks' if direction=='BUY' else 'bids')
        r=research_order(pair=product,side=direction,available=quantity,
            cap=quantity*rate,usd_rate=rate,book=clean[product],
            product_rules=rules,fee=fee,levels=level)
        orders.append(dict(r,observed_at=clean[product][2]))
        return r
    entry=order(pair,side,allocated,source_fx['rate'])
    entry['output_usd_mark']=entry['output_quantity']*target_fx['rate']
    def liquidation(asset,quantity):
        if quantity==0:return D(0)
        if asset=='USD':return quantity
        result=D(0)
        for product in fx(asset)['path']:
            a,b=split_spot(product)
            direction='SELL' if asset==a else 'BUY'
            next_asset=b if direction=='SELL' else a
            rate=fx(asset)['rate']
            try:r=order(product,direction,quantity,rate)
            except ResearchDepthError:raise
            except ValueError as exc:
                if 'minimum/maximum' not in str(exc):raise
                # Exact unconverted dust is retained, not silently made cash or
                # zero. The comparison explicitly includes its conservative mark.
                retained.append({'asset':asset,'quantity':quantity,'usd_mark':quantity*rate})
                return result+quantity*rate
            remainder=quantity-r['input_quantity']
            if remainder:
                retained.append({'asset':asset,'quantity':remainder,'usd_mark':remainder*rate})
                result+=remainder*rate
            quantity=r['output_quantity'];asset=next_asset
        if asset!='USD':raise ValueError('USD_PATH_INCOMPLETE')
        return result+quantity
    w=entry['output_usd_mark']-entry['approx_usd_notional']
    residual=allocated-entry['input_quantity']
    before=liquidation(src,allocated) if include_liquidation else None
    after=(liquidation(dst,entry['output_quantity'])+liquidation(src,residual)) if include_liquidation else None
    l=after-before if include_liquidation else None
    identity=repr((pair,side,tuple(sorted((p,tuple(map(str,clean[p]))) for p in dependency)),
        tuple(sorted((p,tuple(sorted((k,str(v)) for k,v in rules[p].items()))) for p in dependency)),
        str(allocated),str(cap),str(fee),include_liquidation,valuation_policy)).encode()
    changed=dict(idea,shadow_fifo_steps=[entry],input_units_planned=entry['input_quantity'],
        destination_units_estimate=entry['output_quantity'],immediate_change_usd=w,
        snowball_state='IMMEDIATE_ESTIMATE',snowball_immediate_usd=str(l),
        selection_asof=now,sends_live_orders=False)
    ratio=target_fx['rate']/source_fx['rate']
    cross=(1-clean[pair][1]/ratio)*100 if side=='BUY' else (clean[pair][0]*target_fx['rate']/source_fx['rate']-1)*100
    return {'id':hashlib.sha256(identity).hexdigest(),'at':float(now),'pair':pair,'side':side,
        'w':w,'l':l,'before_liquidation_usd':before,'after_liquidation_usd':after,
        'source_rate':source_fx['rate'],'target_rate':target_fx['rate'],'valuation_policy':valuation_policy,
        'source_path':source_fx['path'],'target_path':target_fx['path'],
        'book_span_s':max(stamps)-min(stamps),'oldest_book_age_s':now-min(stamps),
        'dependencies':tuple(sorted(dependency)),'orders':orders,'retained_residuals':retained,
        'cross_market_discrepancy_pct':cross,'fee_currency_assumption':quote,
        'entry_fee_usd_estimate':entry['fee_amount_estimate']*fx(quote)['rate'],
        'usd_mark_source':'PUBLIC_REST_CONSERVATIVE_BID_OR_INVERSE_ASK',
        'exchange_time_verified':False,'liquidation_model':'USD_CASH_PLUS_RETAINED_NATIVE_RESIDUAL_MARKS' if include_liquidation else 'NOT_REQUESTED_WALLET_VALUE_ONLY',
        'idea':changed,'books':{p:clean[p] for p in dependency},
        'rules':{p:deepcopy(rules[p]) for p in dependency if p in rules}}
