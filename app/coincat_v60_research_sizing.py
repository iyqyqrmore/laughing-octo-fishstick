"""CoinCat v60.3 read-only per-holding research eligibility.

Research funding is the sum of individually *verified*, *available*, *enrolled*
coin quantities with fresh strict executable-style USD marks. One excluded or
unpriceable holding MUST NOT collapse the capacity of another eligible holding.
This is a research inventory snapshot, NOT a complete portfolio valuation,
order budget, authorization, or a guarantee of executable liquidity.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from coincat_cross_quote import usd_conversion
from coincat_multicurrency import _snapshots


def funding_inventory_snapshot(holdings, verified_balances, quotes, catalog, *, now):
    books=_snapshots(catalog, quotes, now, max_age=120)
    inventory=[]
    reasons={'STALE_OR_WIDE_USD_BOOK':0, 'INVALID_QUANTITY':0,
             'NO_VERIFIED_AVAILABLE_BALANCE':0,'ZERO_QUANTITY':0}
    considered=0
    for row in holdings or ():
        if not row.get('enabled',1):continue
        asset=str(row.get('asset','')).upper()
        if not asset:continue
        considered+=1
        try:
            owned=Decimal(str(row.get('remaining_qty',0)))
            available=Decimal(str((verified_balances or {}).get(asset,0)))
            if not (owned.is_finite() and available.is_finite()) or owned<0 or available<0:
                reasons['INVALID_QUANTITY']+=1;continue
            if available==0 and owned>0:
                reasons['NO_VERIFIED_AVAILABLE_BALANCE']+=1;continue
            qty=min(owned,available)
            if qty<=0:reasons['ZERO_QUANTITY']+=1;continue
            fx=usd_conversion(asset,books,now=now,max_age=120,max_legs=2)
            if fx is None:
                reasons['STALE_OR_WIDE_USD_BOOK']+=1;continue
            rate=Decimal(str(fx['rate']))
            if not rate.is_finite() or rate<=0:
                reasons['STALE_OR_WIDE_USD_BOOK']+=1;continue
            inventory.append({'asset':asset,'quantity':qty,'usd_rate':rate,'usd_value':qty*rate})
        except (InvalidOperation,ValueError,TypeError,OverflowError,KeyError,IndexError):
            reasons['INVALID_QUANTITY']+=1
    inventory.sort(key=lambda x:x['asset'])
    total=sum((x['usd_value'] for x in inventory),Decimal(0))
    return {'eligible':inventory,'funding_usd':total,'eligible_count':len(inventory),
            'considered_count':considered,'ineligible_count':considered-len(inventory),
            'ineligible_reasons':reasons,'partial':len(inventory)<considered,
            'state':('RESEARCH_PARTIAL' if inventory and len(inventory)<considered else
                     'RESEARCH_ELIGIBLE' if inventory else 'RESEARCH_WAIT')}


def available_enrolled_usd_ceiling(holdings,verified_balances,quotes,catalog,*,now):
    """Value only individually research-eligible inventory; never a live order cap."""
    return funding_inventory_snapshot(holdings,verified_balances,quotes,catalog,now=now)['funding_usd']
