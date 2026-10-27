"""Bounded authenticated read-only bid/ask and depth ADVISORY.

No new price journal, trained labels, financial writes, or order authority.
A stale/missing extra GET never gets treated as executable liquidity evidence.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from coincat_cross_quote import split_spot

def _d(v):
    if isinstance(v,bool):raise ValueError('boolean is not a quantity')
    try:d=Decimal(str(v))
    except (ValueError,InvalidOperation,TypeError):raise ValueError('missing/invalid quote') from None
    if not d.is_finite() or d<=0:raise ValueError('nonpositive book level')
    return d

def top_of_book(response,pair):
    data=response if isinstance(response,dict) else response.to_dict()
    rows=data.get('pricebooks') or []
    for book in rows:
        if book.get('product_id')!=pair:continue
        bids,asks=book.get('bids') or [],book.get('asks') or []
        if not bids or not asks:raise ValueError('empty authenticated quote')
        bid,ask=_d(bids[0]['price']),_d(asks[0]['price'])
        if bid>ask:raise ValueError('crossed authenticated quote')
        return {'pair':pair,'bid':bid,'ask':ask,'spread_bps':(ask-bid)/ask*10000,
                'bid_size':_d(bids[0]['size']),'ask_size':_d(asks[0]['size']),
                'origin':'AUTHENTICATED_BEST_BID_ASK_ADVISORY_ONLY'}
    raise ValueError('missing requested authenticated product')

def depth_advisory(response,pair,*,max_levels=10):
    data=response if isinstance(response,dict) else response.to_dict()
    book=data.get('pricebook') or {}
    if book.get('product_id')!=pair:raise ValueError('wrong product depth')
    totals=[]
    for side in ('bids','asks'):
        levels=book.get(side) or []
        total=Decimal(0)
        for level in levels[:max_levels]:
            total+=_d(level['price'])*_d(level['size'])
        if not levels:raise ValueError('empty depth')
        totals.append(total)
    bid,ask=totals
    return {'pair':pair,'bid_depth_quote':bid,'ask_depth_quote':ask,
            'imbalance':(bid-ask)/(bid+ask), 'levels_max':max_levels,
            'source':'AUTHENTICATED_LEVEL2_SNAPSHOT_DESCRIPTIVE_ONLY',
            'not_a_fill_or_slippage_guarantee':True}

def bounded_readonly_probe(client,pair,*,want_depth=True):
    """Only SDK read methods, on an existing worker, at most one pair per cycle.

    Errors are typed, never include credential-bearing SDK exceptions.
    This supplementary evidence is not injected into the canonical REST quote DB.
    """
    split_spot(pair)
    result={'pair':pair,'state':'NO_AUTHENTICATED_EVIDENCE','read_only':True,'order_authorized':False,
            'extra_gets':0,'depth':None,'top':None}
    if client is None:return result
    try:
        if hasattr(client,'get_best_bid_ask'):
            result['extra_gets']+=1
            result['top']=top_of_book(client.get_best_bid_ask(product_ids=[pair]),pair)
    except Exception:
        result['top']=None
        result['top_issue']='BID_ASK_UNAVAILABLE'
    try:
        if want_depth and hasattr(client,'get_product_book'):
            result['extra_gets']+=1
            result['depth']=depth_advisory(client.get_product_book(product_id=pair,limit=10),pair)
    except Exception:
        result['depth']=None
        result['depth_issue']='PRODUCT_BOOK_UNAVAILABLE'
    result['state']='READ_ONLY_EVIDENCE' if result['top'] or result['depth'] else 'NO_AUTHENTICATED_EVIDENCE'
    return result
