"""CoinCat v40.1: common, non-executable BUY/SELL spot-order intent.

This is the shared currency-aware contract for researching *all* eligible Coinbase
spot pairs. It does NOT request Coinbase API calls, submit orders, reserve funds,
or mutate any ledger. Existing live accounting has not yet migrated to this contract.

The USD value is a conservative *research mark*, not an executable FX quote.
Unknown taxable acquisition basis stays UNKNOWN. Confirmed fills, fee currencies,
residual balances and crash recovery must be integrated into a unified production
ledger before any cross-quote submission is permitted.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from coincat_broker_pair_review import inspect_pair


def _nonnegative(value, label):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0:
            raise ValueError()
        return n
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Invalid ' + label) from None


def plan_spot_intent(*, pair, side, catalog, product_rules, quotes, now,
                     authorized, verified, balance_age_s, usd_order_cap,
                     excluded=(), slippage_bps='20', fee_reserve_bps=None):
    """Return one currency-tagged, USD-normalized research intent, NEVER an order.

    A BUY reserves its quoted funding units against slippage and a conservative
    fee buffer. A SELL checks approved base funding and reports gross-notional
    risk separately from the (unknown) eventual quote asset proceeds.
    """
    try:
        slip = _nonnegative(slippage_bps,'slippage allowance')
        if fee_reserve_bps is None:raise ValueError('Verified Coinbase fee tier required for spot intent')
        fee = _nonnegative(fee_reserve_bps,'fee allowance')
        cap = _nonnegative(usd_order_cap,'USD order cap')
        if slip > 100 or fee > 500:
            raise ValueError('Research fee/slippage buffers exceed safety ceiling')
        # Size below the actual hard cap, leaving room for the conservative
        # worst-case estimate; never amend the user's authorized limit.
        reserved_cap = cap/(Decimal(1)+(slip+fee)/Decimal(10000))
    except (ValueError,TypeError,InvalidOperation) as exc:
        return dict(pair=pair,side=side,state='BLOCKED',reason=str(exc)[:200],
                    candidate=False,live_eligible=False,order_submitted=False,
                    unified_broker_path=True,production_settlement_ready=False)
    out = inspect_pair(pair=pair,side=side,catalog=catalog,product_rules=product_rules,
                       quotes=quotes,now=now,authorized=authorized,verified=verified,
                       balance_age_s=balance_age_s,usd_order_cap=reserved_cap,
                       excluded=excluded)
    out.update(unified_broker_path=True,order_submitted=False,
               production_settlement_ready=False,live_eligible=False)
    if not out.get('candidate'):
        return out
    try:
        gross = _nonnegative(out['quote_notional_estimate'],'quote notional')
        usd_gross = _nonnegative(out['usd_estimated'],'USD notional')
        base_qty = _nonnegative(out['base_size_estimate'],'base quantity')
        if min(gross, usd_gross, base_qty) <= 0:
            raise ValueError('No positive funding or order size')
        spend = out['spend_asset']
        wallet = min(_nonnegative((authorized or {}).get(spend,0),'approved balance'),
                     _nonnegative((verified or {}).get(spend,0),'Coinbase available balance'))
        # Fee currency is not inferred from the trade pair. This is a worst-case
        # hold estimation ONLY, not the Coinbase fee actually charged.
        if side == 'BUY':
            hold = gross * (Decimal(1)+(slip+fee)/Decimal(10000))
            if hold > wallet:
                raise ValueError('BUY funding buffer exceeds enrolled available quote wallet')
            hold_currency = out['quote']
        else:
            if base_qty > wallet:
                raise ValueError('SELL amount exceeds enrolled Coinbase-available base wallet')
            hold = base_qty
            hold_currency = out['base']
        stressed_usd = usd_gross*(Decimal(1)+(slip+fee)/Decimal(10000))
        if stressed_usd > cap:
            raise ValueError('Gross plus fee/slippage research buffer exceeds USD order cap')
        out.update(funding_reserve_units=format(hold,'f'),funding_reserve_currency=hold_currency,
                   observed_gross_usd=format(usd_gross,'f'),
                   stressed_usd_risk=format(stressed_usd,'f'),
                   assumed_fee_reserve_bps=format(fee,'f'),
                   assumed_slippage_reserve_bps=format(slip,'f'),
                   fee_currency='UNVERIFIED_FROM_COINBASE_PREVIEW',
                   quote_settlement_currency=out['quote'],
                   settlement_mode='UNIFIED_CURRENCY_TAGGED_PREFLIGHT',
                   tax_basis_state='UNKNOWN_UNTIL_VERIFIED_FIFO_USD_LOTS',
                   state='UNIFIED_RESEARCH_INTENT',
                   reason='Currency-tagged spot research intent only; execution requires independent broker risk and actual Coinbase fee/fill evidence')
    except (ValueError, TypeError, InvalidOperation) as exc:
        out.update(state='BLOCKED',reason=str(exc)[:200],candidate=False)
    return out
