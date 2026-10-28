"""CoinCat v40 OFFLINE/READ-ONLY multi-currency spot rotation research.

A pair is an exchange edge, not a direction-independent symbol: A-B SELL
moves A -> B; A-B BUY moves B -> A. Never invent reverse products.

This module has NO Coinbase client, no order/ledger write, no trading triggers.
Its snapshots are research valuations, NOT bid/ask executable guarantees.
Missing FX, stale quotes, product minima/increments, cost-basis evidence,
preview fees, or validated forecasts MUST NOT be guessed into permission.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from collections import defaultdict
from coincat_cross_quote import split_spot, usd_conversion

MAX_LEGS = 2
MAX_PRICE_AGE_S = 120
MAX_BALANCE_AGE_S = 300
MAX_SPREAD = Decimal('.0025')
# The cross-currency planner has NO default fee. Authenticate the spot tier first.
DEFAULT_SLIPPAGE_BPS = Decimal('15')
# No discretionary profit reserve in research funding. BUY sizing accounts
# explicitly for modeled fee/slippage before rounding, and never exceeds the
# verified available wallet, order cap or authenticated product rules.


def _d(value, *, positive=False):
    try: v=Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):raise ValueError('Invalid decimal input') from None
    if not v.is_finite() or (positive and v<=0):raise ValueError('Non-finite or nonpositive amount')
    return v


def _snapshots(catalog, quotes, now, *, max_age=MAX_PRICE_AGE_S, max_spread=MAX_SPREAD):
    if not 0 < float(max_age) <= 300: raise ValueError('Price age ceiling outside research bounds')
    good={}
    for pair in sorted(set(catalog or ()) & set(quotes or ())):
        try:
            split_spot(pair)
            bid,ask,ts=quotes[pair]
            bid,ask=_d(bid,positive=True),_d(ask,positive=True)
            age=float(now)-float(ts)
            if 0 <= age <= max_age and bid<=ask and (ask-bid)/ask <= max_spread:
                good[pair]=(bid,ask,float(ts))
        except (ValueError,TypeError,KeyError,OverflowError):pass
    return good


def available_routes(source,target,catalog,quotes,*,now,max_legs=2):
    """Only catalog-listed and fresh-spread-validated SELL/BUY edges.

    Output route tuple: (pair, 'BUY'|'SELL', from_asset, to_asset).
    Synthetic inverse quote prices are never represented as an exchange pair.
    """
    if max_legs not in (1,2):raise ValueError('Unsupported route length')
    if source==target:return []
    valid=_snapshots(catalog,quotes,now)
    return _paths(source,target,set(catalog or ()),valid,max_legs)


def _paths(source,target,catalog,valid,max_legs):
    if max_legs not in (1,2):raise ValueError('Unsupported route length')
    if source==target:return []
    if max_legs==1:
        # Two real product IDs at most; an inverse edge uses BUY on its listed
        # product, never a fabricated reverse product or an intermediary.
        paths=[]
        pair=f'{source}-{target}'
        if pair in catalog and pair in valid:paths.append(((pair,'SELL',source,target),))
        pair=f'{target}-{source}'
        if pair in catalog and pair in valid:paths.append(((pair,'BUY',source,target),))
        return sorted(paths,key=lambda p:tuple((x[0],x[1]) for x in p))
    edges=defaultdict(list)
    for pair in valid:
        base,quote=split_spot(pair)
        edges[base].append((pair,'SELL',base,quote))
        edges[quote].append((pair,'BUY',quote,base))
    paths=[]
    def search(node,parts,visited):
        if node==target:
            if parts:paths.append(tuple(parts))
            return
        if len(parts)==max_legs:return
        for edge in sorted(edges.get(node,()),key=lambda x:(x[3],x[0],x[1])):
            if edge[3] not in visited:
                search(edge[3],parts+[edge],visited|{edge[3]})
    search(source,[],{source})
    return sorted(paths,key=lambda p:(len(p),tuple((x[0],x[1]) for x in p)))


class RotationContext:
    """One immutable decision's validated quotes and memoized USD paths.

    Never stored globally or across market events. Native quantities, price
    rules, fees and balances are still checked by evaluate_rotation per size.
    """
    def __init__(self,catalog,quotes,now,quote_age_s=MAX_PRICE_AGE_S):
        from types import MappingProxyType
        self.catalog=frozenset(catalog)
        self.now=now;self.quote_age_s=quote_age_s
        self.books=MappingProxyType(_snapshots(catalog,quotes,now,max_age=quote_age_s))
        self._fx={};self._routes={}

    def usd(self,asset):
        if asset not in self._fx:
            self._fx[asset]=usd_conversion(asset,self.books,now=self.now,
                                           max_age=self.quote_age_s,max_legs=2)
        return self._fx[asset]

    def routes(self,source,target,max_legs):
        key=(source,target,max_legs)
        if key not in self._routes:
            self._routes[key]=_paths(source,target,self.catalog,self.books,max_legs)
        return self._routes[key]


def _rule(product_rules,pair):
    """Rules must be an authenticated Coinbase product snapshot for strict estimates."""
    p=(product_rules or {}).get(pair)
    if not isinstance(p,dict):return None
    try:
        increment=_d(p['base_increment'],positive=True)
        minbase=_d(p['base_min_size'],positive=True)
        minquote=_d(p['quote_min_size'],positive=True)
        maxbase=_d(p['base_max_size'],positive=True) if p.get('base_max_size') else None
        maxquote=_d(p['quote_max_size'],positive=True) if p.get('quote_max_size') else None
    except (ValueError,KeyError):return None
    if maxbase is not None and maxbase<minbase:return None
    if maxquote is not None and maxquote<minquote:return None
    return increment,minbase,minquote,maxbase,maxquote


def _floor(value,increment):
    return (value/increment).to_integral_value(rounding=ROUND_DOWN)*increment


def evaluate_rotation(*,source,target,authorized_qty,verified_available_qty,
                      balance_age_s,catalog,quotes,now,usd_per_order_cap,
                      product_rules=None,fee_rate=None,fee_rates_by_pair=None,
                      slippage_bps=DEFAULT_SLIPPAGE_BPS,quote_age_s=MAX_PRICE_AGE_S,
                      excluded_assets=(),max_legs=2,crypto_only=False,_context=None):
    """Research-only planned SELL or BUY route with residual balances.

    Whole-holding disposition requires later capacity-approved capped slices,
    independent previews/reconciliation, and a validated FORWARD advantage.
    No paper estimates can trigger a live order.
    """
    if source in set(excluded_assets) or target in set(excluded_assets):
        return {'state':'BLOCKED','reason':'Explicitly excluded asset','routes':[]}
    try:
        amount=min(_d(authorized_qty,positive=True),_d(verified_available_qty,positive=True))
        cap=_d(usd_per_order_cap,positive=True)
        # No global fiat or crypto quote fee assumption. Caller may supply a
        # validated account-tier rate per pair; this remains research-only.
        if fee_rate is None and not fee_rates_by_pair:
            raise ValueError('Verified Coinbase fee evidence missing for cross-pair research')
        if fee_rate is not None:
            fee=_d(fee_rate)
            if not 0<=fee<Decimal('.05'):raise ValueError('Unsupported explicit research fee')
        slip=_d(slippage_bps)/Decimal(10000)
        if not 0<=slip<=Decimal('.005'):
            raise ValueError('Unsupported research slippage reserve')
        if not 0 <= float(balance_age_s) <= MAX_BALANCE_AGE_S:
            raise ValueError('Coinbase available-balance snapshot stale')
    except (ValueError,TypeError,OverflowError) as exc:
        return {'state':'WAIT','reason':str(exc),'routes':[]}
    context=_context or RotationContext(catalog,quotes,now,quote_age_s)
    if context.now!=now or context.quote_age_s!=quote_age_s:
        raise ValueError('A decision context cannot be reused at a different time/age policy')
    valid=context.books
    srcfx=context.usd(source)
    destfx=context.usd(target)
    if srcfx is None or destfx is None:
        return {'state':'WAIT','reason':'No fresh conservative USD conversion for source and destination','routes':[]}
    if crypto_only:
        from coincat_v609_direct import NON_CRYPTO_QUOTES, direct_crypto_pairs
        if source in NON_CRYPTO_QUOTES or target in NON_CRYPTO_QUOTES:
            return {'state':'WAIT','reason':'Direct crypto-only research excludes cash and stablecoin assets','routes':[]}
        route_catalog=direct_crypto_pairs(catalog)
    else:
        route_catalog=catalog
    paths=(available_routes(source,target,route_catalog,valid,now=now,max_legs=max_legs)
           if crypto_only else context.routes(source,target,max_legs))
    if not paths:return {'state':'WAIT','reason':'No fresh, listed Coinbase direct crypto spot pair' if crypto_only else 'No fresh, listed Coinbase spot route within requested leg limit','routes':[]}
    results=[]; missing_rules=0; blocked_reasons={}
    for path in paths:
        # Never use an excluded intermediary as a temporary funding wallet.
        if any(edge[2] in set(excluded_assets) or edge[3] in set(excluded_assets)
               for edge in path):
            continue
        wallet={source:amount}
        start_amount=None;receipts=[];failed=None
        for index,(pair,side,from_asset,to_asset) in enumerate(path):
            rules=_rule(product_rules,pair)
            if rules is None:
                missing_rules+=1;failed='Product increments/minimums not verified';break
            inc,minbase,minquote,maxbase,maxquote=rules
            # Account-tier estimates cover all spot quotes without inventing
            # a distinct fee for each pair. An absent rate blocks this route.
            try:
                leg_fee=_d((fee_rates_by_pair or {})[pair] if fee_rates_by_pair is not None else fee_rate)
                if not 0<=leg_fee<Decimal('.05'):raise ValueError('Invalid fee rate')
            except (KeyError,TypeError,ValueError):
                failed='Authenticated fee evidence missing for route leg';break
            bid,ask,_=valid[pair]
            available=wallet.get(from_asset,Decimal(0))
            if available<=0:failed='No planned input asset remaining';break
            fx=context.usd(from_asset)
            if fx is None:failed='Missing quote currency USD mark';break
            # Every single simulated leg must fit the unchanged USD stage cap.
            usd_max=cap/fx['rate']
            if side=='SELL':
                qty=_floor(min(available,usd_max),inc)
                trade_quote=qty*bid*(1-slip)
                if qty<minbase or trade_quote<minquote or (maxbase and qty>maxbase) or (maxquote and trade_quote>maxquote):
                    failed='Coinbase pair minimum/maximum or rounded size blocks SELL';break
                received=trade_quote*(1-leg_fee)
                spent=qty
            else:
                # No extra 10% holding reserve: fee/slippage are already paid
                # from this exact budget via the denominator below. Preserve
                # every Coinbase minimum, increment and verified funding cap.
                budget=min(available,usd_max)
                qty=_floor(budget/(ask*(1+slip)*(1+leg_fee)),inc)
                spent=qty*ask*(1+slip)*(1+leg_fee)
                gross_quote=qty*ask*(1+slip)
                if qty<minbase or gross_quote<minquote or (maxbase and qty>maxbase) or (maxquote and gross_quote>maxquote):
                    failed='Coinbase pair minimum/maximum or rounded size blocks BUY';break
                received=qty
            if spent<=0 or spent>available or spent*fx['rate']>cap:
                failed='Per-order USD cap or funding balance exceeded';break
            wallet[from_asset]=available-spent
            wallet[to_asset]=wallet.get(to_asset,Decimal(0))+received
            receipts.append({'pair':pair,'side':side,'input_asset':from_asset,'output_asset':to_asset,
                             'input_quantity':spent,'output_quantity':received,
                             'gross_base_quantity':qty,'approx_usd_notional':spent*fx['rate'],
                             'output_usd_mark':(received*context.usd(to_asset)['rate']
                                                if context.usd(to_asset) is not None else None),
                             'assumed_fee_currency_for_research':pair.split('-')[1],
                             'fee_rate_source':'AUTHENTICATED_ACCOUNT_TIER_ESTIMATE_NOT_PAIR_PREVIEW',
                             'fee_rate_used':leg_fee})
            if index==0:start_amount=spent
        if failed:
            blocked_reasons[failed]=blocked_reasons.get(failed,0)+1
            continue
        before=amount*srcfx['rate']
        total_after=Decimal(0); unknown=False
        for asset,units in wallet.items():
            if units<=0:continue
            fx=context.usd(asset)
            if fx is None:unknown=True;break
            total_after+=units*fx['rate']
        if unknown:
            blocked_reasons['Missing residual asset USD conversion']=blocked_reasons.get('Missing residual asset USD conversion',0)+1
            continue
        results.append({'route':tuple((p,s) for p,s,_,_ in path),
                        'steps':receipts,'input_asset':source,
                        'input_units_planned':start_amount,
                        'destination_asset':target,
                        'destination_units_estimate':wallet.get(target,Decimal(0)),
                        'residual_wallet_estimate':{k:v for k,v in wallet.items() if v>0},
                        'initial_wallet_usd_mark':before,'post_route_wallet_usd_mark':total_after,
                        'immediate_change_usd':total_after-before,
                        'state':'RESEARCH ONLY','forecast':'UNVALIDATED; no forward gain claimed',
                        'warning':'Not executable: account-tier fee estimate, independent bid/ask and assumed slippage; no pair preview, production USD FIFO or POST recovery'})
    results.sort(key=lambda r:(-r['post_route_wallet_usd_mark'],len(r['route']),str(r['route'])))
    return {'state':'RESEARCH ONLY' if results else 'WAIT',
            'reason':('Requires forward evidence plus independent broker/ledger verification' if results
                     else 'Missing Coinbase product rules, increments or safe capped route' if missing_rules
                     else 'No route passes validated product-size/fee/cap checks; see typed rejections'),
            'route_rejections':dict(sorted(blocked_reasons.items())),
            'routes':results}
