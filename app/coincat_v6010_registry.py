"""v60.10 authoritative one-order authenticated Coinbase SPOT research universe.

Products are sourced ONLY from the paginated account-authenticated List Products
response. The registry never constructs synthetic conversion products and cannot
submit orders. It is scoped to order types the existing research planner models:
marketable BUY/SELL; limit-only or post-only requires separate mechanics.
"""
from __future__ import annotations
from collections import Counter
from coincat_cross_quote import split_spot

REJECT_FLAGS=('view_only','trading_disabled','is_disabled','cancel_only','limit_only','post_only','auction_mode')
STABLE_AND_FIAT=frozenset({'USD','USDC','USDT','DAI','EUR','GBP','CAD','AUD','JPY','CHF','BRL','SGD','PYUSD','EURC','FDUSD','TUSD'})

def eligible_product(product):
    if not isinstance(product,dict):return False
    pair=str(product.get('product_id') or '').upper()
    try:base,quote=split_spot(pair)
    except (ValueError,TypeError):return False
    if not base or not quote or base==quote:return False
    if str(product.get('product_type','SPOT')).upper()!='SPOT':return False
    return not any(product.get(flag) is True for flag in REJECT_FLAGS)

def spot_registry(products):
    """Return (canonical IDs, rule map, counters) after complete pagination.

    Does not infer price freshness or account execution permission from a listing.
    A missing view_only value must be marked unverified by the caller, rather
    than represented as a product's authenticated tradability proof.
    """
    products=list(products or ())
    ids=set();rules={};reasons=Counter();type_counts=Counter()
    for record in products:
        if not isinstance(record,dict):reasons['INVALID_RECORD']+=1;continue
        pid=str(record.get('product_id') or '').upper()
        type_counts[str(record.get('product_type','UNKNOWN'))]+=1
        if not eligible_product(record):
            if str(record.get('product_type','SPOT')).upper()!='SPOT':category='NOT_SPOT'
            elif any(record.get(k) is True for k in REJECT_FLAGS):category='RESTRICTED'
            else:category='INVALID_PAIR'
            reasons[category]+=1;continue
        if pid in ids:reasons['DUPLICATE_ID']+=1;continue
        ids.add(pid);rules[pid]=dict(record)
    ids=sorted(ids)
    quote_counts=Counter(pid.split('-')[1] for pid in ids)
    return ids,rules,{'raw_count':len(products),'eligible_count':len(ids),
        'filtered_count':len(products)-len(ids),'reject_reasons':dict(reasons),
        'quote_currencies':dict(sorted(quote_counts.items())),
        'usd_usdc':sum(quote_counts.get(x,0) for x in ('USD','USDC')),
        'usdt_dai':sum(quote_counts.get(x,0) for x in ('USDT','DAI')),
        'other_quoted':sum(n for q,n in quote_counts.items() if q not in ('USD','USDC','USDT','DAI'))}

def one_order_catalog(catalog,product_rules=None):
    """No mandatory intermediary: a listed A-B BUY spends B and SELL spends A.

    Catalog IDs originate from authenticated eligibility. When detailed rules
    are available, recheck restrictions; never add a pair absent from catalog.
    """
    valid=[]
    rules=product_rules or {}
    for pair in catalog or ():
        try:base,quote=split_spot(pair)
        except (ValueError,TypeError):continue
        if base==quote:continue
        rec=rules.get(pair)
        if rec is not None and not eligible_product(dict(rec,product_id=pair)):
            continue
        valid.append(pair)
    return sorted(set(valid))
