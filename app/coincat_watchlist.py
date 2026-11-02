"""Owner-approved seven-market scope; six-book rotation, never extra markets."""
from coincat_multicurrency import _rule
from coincat_v6010_registry import REJECT_FLAGS
from coincat_v80_immediate import exact

WATCH_PAIRS=('ADA-ETH','ETH-BTC','LINK-ETH','SOL-ETH','LINK-BTC','SOL-BTC','ADA-BTC')
WATCH_ASSETS=('ETH','BTC','ADA','LINK','SOL')
ETH_PAIRS=WATCH_PAIRS[:4]
BTC_PAIRS=WATCH_PAIRS[4:]


def product_eligibility(pair,rules):
    """Same authenticated spot/rule requirements for either quote currency."""
    p=rules.get(pair,{})
    if (p.get('product_id')!=pair or str(p.get('product_type','')).upper()!='SPOT'
            or str(p.get('status','')).lower()!='online'):
        return 'PRODUCT_ID_TYPE_OR_STATUS_UNVERIFIED'
    if p.get('view_only') is not False:return 'ACCOUNT_TRADABILITY_UNVERIFIED'
    if any(p.get(flag) is True for flag in REJECT_FLAGS):return 'PRODUCT_RESTRICTED'
    try:
        base,quote=pair.split('-')
        if (_rule(rules,pair) is None or exact(p.get('price_increment',p.get('quote_increment')))<=0
                or exact(p['quote_increment'])<=0 or p.get('base_currency_id',base)!=base
                or p.get('quote_currency_id',quote)!=quote):raise ValueError()
    except (ValueError,TypeError,KeyError,ArithmeticError):return 'PRODUCT_RULES_UNVERIFIED'
    return None


def eligible_watchlist(catalog,rules,excluded=()):
    available=set(catalog);excluded=set(excluded);qualified=[];rejected={}
    for pair in WATCH_PAIRS:
        reason=('EXCLUDED' if excluded.intersection(pair.split('-')) else
                'NOT_IN_AUTHENTICATED_CATALOG' if pair not in available else product_eligibility(pair,rules))
        if reason:rejected[pair]=reason
        else:qualified.append(pair)
    return tuple(qualified),rejected


def schedule_books(qualified,sequence):
    allowed=set(qualified)&set(WATCH_PAIRS)
    anchors=[p for p in ETH_PAIRS if p in allowed]
    cross=[p for p in BTC_PAIRS if p in allowed]
    offset=sequence%len(cross) if cross else 0
    rotated=cross[offset:]+cross[:offset]
    selected=tuple(anchors+rotated[:6-len(anchors)])
    return selected,tuple(p for p in WATCH_PAIRS if p in allowed and p not in selected)
