"""Verified ETH route/quote/receipt blockers, without native quantities.

This diagnoses the existing canonical model. It cannot select a trade, change
costs, invent a route, relax quote rules or authorize an allocation.
"""
from collections import Counter
from decimal import Decimal, ROUND_DOWN

from coincat_multicurrency import _paths, _rule
from coincat_cross_quote import split_spot
from coincat_v6010_registry import REJECT_FLAGS
from coincat_v703_chain import approved_pairs
from coincat_v80_discovery import book_status, listed_usd_paths
from coincat_working_allocation import public_asset

D = Decimal


def structural_details(asset, *, catalog, rules, excluded=()):
    """Reasons are limited to the supplied authenticated catalog snapshot.

    The broker may already have removed unavailable products. Absence here is
    not evidence of delisting, regional restriction or an exchange-wide absence.
    """
    raw=set()
    for pair in catalog:
        try:
            split_spot(pair);raw.add(pair)
        except (ValueError,TypeError):
            continue
    listed=set(approved_pairs(raw,rules,excluded));marks=listed_usd_paths(listed)
    if asset in excluded:
        return {'asset':public_asset(asset),'supported':False,'blockers':['EXCLUDED_ASSET'],'route':[]}
    paths=[] if asset=='ETH' else _paths(asset,'ETH',listed,listed,2)
    blockers=[];rejected=[]
    if asset!='ETH' and not paths:
        raw_paths=_paths(asset,'ETH',raw,raw,2)
        if not raw_paths:
            blockers.append('NO_ETH_ROUTE_WITHIN_TWO_LEGS_IN_CATALOG')
        else:
            blockers.append('ETH_ROUTE_PRODUCTS_NOT_APPROVED')
            for pair in sorted({leg[0] for path in raw_paths for leg in path}-listed):
                rec=rules.get(pair)
                reasons=[]
                if set(pair.split('-'))&set(excluded):reasons.append('PATH_INCLUDES_EXCLUDED_ASSET')
                if not isinstance(rec,dict):reasons.append('PRODUCT_RULES_UNVERIFIED')
                else:
                    if _rule(rules,pair) is None:reasons.append('PRODUCT_SIZE_RULES_UNVERIFIED')
                    if rec.get('product_id',pair)!=pair:reasons.append('PRODUCT_ID_CONFLICT')
                    if str(rec.get('product_type','SPOT')).upper()!='SPOT':reasons.append('PRODUCT_NOT_SPOT')
                    if any(rec.get(flag) is True for flag in REJECT_FLAGS):reasons.append('PRODUCT_RESTRICTED')
                    if str(rec.get('status') or '').lower() not in ('','online'):reasons.append('PRODUCT_NOT_ONLINE')
                rejected.append({'product':pair,'blockers':reasons or ['PRODUCT_NOT_APPROVED']})
    path=paths[0] if paths else ()
    if (asset not in ('USD','ETH') and asset not in marks) or any(leg[2] not in marks for leg in path):
        blockers.append('USD_MARK_ROUTE_NOT_LISTED')
    if 'ETH-USD' not in listed:
        blockers.append('ETH_REFERENCE_PRODUCT_NOT_APPROVED')
    return {'asset':public_asset(asset),'supported':not blockers,'blockers':blockers,
            'route':[leg[0] for leg in path],'rejected_products':rejected,
            'evidence_scope':'SUPPLIED_AUTHENTICATED_CATALOG_ONLY'}


def missing_route_blockers(asset, *, catalog, rules, observed, now, excluded=()):
    detail=structural_details(asset,catalog=catalog,rules=rules,excluded=excluded)
    if not detail['supported']:
        return detail['blockers']
    states=[book_status(observed.get(pair),now) for pair in detail['route']]
    reasons=['QUOTE_'+state for state in states if state!='FRESH']
    return sorted(set(reasons)) or ['NO_VALID_OBSERVED_ETH_ROUTE']


def receipt_blockers(*,pair,side,available,book,rules,fee,slip):
    """Explain a canonical rejection using its verified size constraints.

    Never size a replacement order. All violated constraints are reported;
    unknown failures retain an explicit unclassified canonical rejection.
    """
    verified=_rule(rules,pair)
    if verified is None:return ['PRODUCT_SIZE_RULES_UNVERIFIED']
    increment,minbase,minquote,maxbase,maxquote=verified
    try:
        budget=available
        quote_increment=rules[pair].get('quote_increment')
        if side=='BUY' and quote_increment is not None:
            quantum=D(str(quote_increment));budget=(budget/quantum).to_integral_value(rounding=ROUND_DOWN)*quantum
        units=budget/(book[1]*(1+slip)*(1+fee)) if side=='BUY' else budget
        units=(units/increment).to_integral_value(rounding=ROUND_DOWN)*increment
        gross=units*(book[1]*(1+slip) if side=='BUY' else book[0]*(1-slip))
        reasons=[]
        if not units:reasons.append('PRECISION_BELOW_BASE_INCREMENT')
        if units<minbase:reasons.append('BELOW_BASE_MINIMUM')
        if gross<minquote:reasons.append('BELOW_QUOTE_MINIMUM')
        if maxbase and units>maxbase:reasons.append('ABOVE_BASE_MAXIMUM')
        if maxquote and gross>maxquote:reasons.append('ABOVE_QUOTE_MAXIMUM')
        return reasons or ['CANONICAL_RECEIPT_REJECTED_UNCLASSIFIED']
    except (ValueError,TypeError,ArithmeticError):
        return ['RECEIPT_CONSTRAINTS_UNVERIFIED']


def conversion_diagnostics(details, *, reference_state='FRESH', balances_fresh=True, quote_span=None):
    """Details are deliberately constructed from controlled fields/reason codes."""
    rows=[];counts=Counter()
    for detail in details:
        blockers=set(detail['blockers'])
        if reference_state!='FRESH':blockers.add('ETH_REFERENCE_'+reference_state)
        if not balances_fresh:blockers.add('AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED')
        if quote_span is not None and quote_span>12:blockers.add('ETH_MEASUREMENT_PRICE_SKEW')
        counts.update(blockers)
        rows.append({'asset':public_asset(detail['asset']),'state':detail['state'],
            'blockers':sorted(blockers),'route':detail.get('route',[]),
            'residue_assets':[public_asset(a) for a in detail.get('residue_assets',())]})
    return {'scope':'ACCOUNT_AVAILABLE_NOT_COINCAT_ALLOCATION','holdings':rows,
            'blocker_asset_counts':dict(sorted(counts.items())),
            'complete_total_available':not any(row['blockers'] for row in rows),
            'quote_evidence_scope':'LAST_OBSERVED_QUOTES_NOT_CURRENT_MARKET_PROOF',
            'quantities_exported':False}
