"""Pure approval, ranking and unit contracts shared by the decision chain.

No network, credentials, financial writes, arming or order interface.
"""
from decimal import Decimal, InvalidOperation
from coincat_v6010_registry import one_order_catalog
from coincat_multicurrency import _rule


def approved_pairs(catalog,rules,excluded=(),*,funding=None):
    excluded=set(excluded)
    funding=None if funding is None else set(funding)
    out=[]
    for pair in one_order_catalog(catalog,rules):
        base,quote=pair.split('-')
        rec=(rules or {}).get(pair)
        if base in excluded or quote in excluded:continue
        if not isinstance(rec,dict) or _rule(rules,pair) is None:continue
        if rec.get('product_id',pair)!=pair:continue
        status=str(rec.get('status') or '').lower()
        if status and status!='online':continue
        if funding is not None and not ({base,quote}&funding):continue
        out.append(pair)
    return out
