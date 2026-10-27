"""CoinCat v30.3: exchange-pair-neutral PRE-EXECUTION review (READ ONLY).

This is the common language between AI Lab and the live broker for ANY
Coinbase-listed spot product. Passing this review DOES NOT authorize an order.
It never calls Coinbase, previews/orders, updates financial DBs or arms trading.
Current legacy live settlement is USD/USDC only; crossing that boundary must
await verified USD accounting, fee-currency and order-by-order lot migration.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from coincat_cross_quote import split_spot, usd_conversion, USD_QUOTES


def _d(value):
    try:
        v = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError('Missing or invalid numeric input') from None
    if not v.is_finite() or v < 0:
        raise ValueError('Non-finite or negative amount')
    return v


def inspect_pair(*, pair, side, catalog, product_rules, quotes, now,
                 authorized, verified, balance_age_s, usd_order_cap,
                 excluded=(), max_quote_age_s=120, max_balance_age_s=300):
    """Assess single BUY/SELL opportunity using actual listed product and FX.

    "authorized" and "verified" are mappings asset->quantity. Quote prices
    must be authenticated or REST best bid/ask (never a last-trade ticker).
    The method returns a proposed size and the true current live-scope status.
    It deliberately cannot cause Coinbase order creation or ledger writes.
    """
    res={'pair':str(pair), 'side':str(side), 'state':'BLOCKED', 'reason':'Not assessed',
         'candidate':False, 'live_eligible':False, 'usd_estimated':None}
    try:
        base, quote = split_spot(pair)
        if side not in ('BUY','SELL'):
            raise ValueError('Only spot BUY/SELL supported')
        if pair not in set(catalog or ()):
            raise ValueError('Pair absent from authenticated, eligible Coinbase spot catalog')
        if base in set(excluded) or quote in set(excluded):
            raise ValueError('Pair touches excluded funding/destination asset')
        rules=(product_rules or {}).get(pair)
        if not isinstance(rules,dict) or rules.get('product_id',pair)!=pair or rules.get('product_type','SPOT')!='SPOT':
            raise ValueError('Missing authenticated spot product rules')
        if any(rules.get(flag) for flag in ('view_only','trading_disabled','is_disabled','limit_only','cancel_only')):
            raise ValueError('Spot product currently not tradable')
        b, a, ts=(quotes or {})[pair]
        bid,ask=_d(b),_d(a)
        age=float(now)-float(ts)
        wallet_age=float(balance_age_s)
        if not (bid>0 and bid<=ask and 0<=age<=max_quote_age_s):
            raise ValueError('Stale or crossed executable bid/ask')
        if not (0<=wallet_age<=max_balance_age_s):
            raise ValueError('Verified available balances stale')
        if (ask-bid)/ask>Decimal('.0025'):
            raise ValueError('Spread exceeds 25 bps')
        cap=_d(usd_order_cap)
        if cap<1:raise ValueError('No authorized USD order budget')
        inc=_d(rules['base_increment'])
        base_min=_d(rules['base_min_size'])
        quote_min=_d(rules['quote_min_size'])
        if min(inc,base_min,quote_min)<=0:raise ValueError('Missing positive exchange size increments/minimums')
        maximum_base=_d(rules['base_max_size']) if rules.get('base_max_size') else None
        maximum_quote=_d(rules['quote_max_size']) if rules.get('quote_max_size') else None
        fx=usd_conversion(quote,quotes,now=now,max_age=max_quote_age_s,max_legs=3)
        if not fx or fx['rate']<=0:raise ValueError('No fresh USD valuation of quote currency')
        spend_asset=quote if side=='BUY' else base
        approved=min(_d((authorized or {}).get(spend_asset,0)),_d((verified or {}).get(spend_asset,0)))
        if approved<=0:raise ValueError('Funding asset not enrolled and Coinbase-available')
        price=ask if side=='BUY' else bid
        if side=='BUY':
            # Reserve quote for live fees, slippage and balance movement.
            quote_budget=min(approved/Decimal('1.10'),cap/fx['rate'])
            qty=(quote_budget/ask/inc).to_integral_value(rounding=ROUND_DOWN)*inc
            quote_notional=qty*ask
            if quote_notional>quote_budget:raise ValueError('Rounding exceeded quote budget')
        else:
            qty=(min(approved,cap/(bid*fx['rate']))/inc).to_integral_value(rounding=ROUND_DOWN)*inc
            quote_notional=qty*bid
        if qty<=0 or qty<base_min or quote_notional<quote_min:
            raise ValueError('Coinbase minimum after increment rounding not satisfied')
        if maximum_base is not None and qty>maximum_base:
            raise ValueError('Exceeds Coinbase base maximum')
        if maximum_quote is not None and quote_notional>maximum_quote:
            raise ValueError('Exceeds Coinbase quote maximum')
        usd=quote_notional*fx['rate']
        if usd>cap:raise ValueError('Exceeds USD-normalized per-order cap')
        res.update(candidate=True, state='VALIDATED_RESEARCH',
                   reason=('Cross-quote pair passes read-only sizing/FX validation; LIVE settlement NOT certified'
                           if quote not in USD_QUOTES else
                           'USD/USDC pair passes read-only sizing/FX validation; broker still independently validates'),
                   base=base,quote=quote,spend_asset=spend_asset,
                   base_size_estimate=str(qty),quote_notional_estimate=str(quote_notional),
                   usd_estimated=str(usd), usd_fx_path=fx['path'],
                   live_eligible=False)
    except (KeyError,TypeError,ValueError,OverflowError,InvalidOperation,ZeroDivisionError) as exc:
        res['reason']=str(exc)[:160] or 'Incomplete Coinbase pricebook/rules/authorization'
    return res
