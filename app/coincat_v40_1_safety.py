"""CoinCat v40.1: PURE, fail-closed observation health + quote-neutral pilot rehearsal.

No Coinbase requests, database mutations, arm controls, or order submissions.
This is not a live crypto-quote settlement implementation.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import math


def _age_is_fresh(age, limit):
    try:
        v = float(age)
        return math.isfinite(v) and 0 <= v <= limit
    except (TypeError, ValueError, OverflowError):
        return False


def live_data_health(*, catalog_age_s, portfolio_age_s, scan_age_s,
                     valuation_age_s, connected, poll_age_s=None,
                     tick_age_s=None, history_in_progress=False,
                     scan_processing=False, portfolio_sync_running=False):
    """Independent, current snapshot; never trusts an old green GUI status.

    Historical candle catch-up is not a substitute for live executable quotes.
    A running background task is reported as context, not proof of freshness.
    """
    blockers=[]
    if not connected:
        blockers.append('No authenticated broker connection')
    for age, threshold, description in (
        (catalog_age_s, 7200, 'Authenticated Coinbase spot catalog older than 2h'),
        (portfolio_age_s, 300, 'Coinbase available balances older than 5m'),
        (scan_age_s, 180, 'Completed REST bid/ask scan older than 3m'),
        (valuation_age_s, 300, 'Portfolio USD pricebooks older than 5m'),
    ):
        if not _age_is_fresh(age, threshold):
            blockers.append(description)
    if poll_age_s is not None and not _age_is_fresh(poll_age_s, 15):
        blockers.append('GUI poll callback not recently running')
    if tick_age_s is not None and not _age_is_fresh(tick_age_s, 15):
        blockers.append('Research timer callback not recently running')
    return dict(ready=not blockers,blockers=blockers,
                history_in_progress=bool(history_in_progress),
                scan_processing=bool(scan_processing),
                portfolio_sync_running=bool(portfolio_sync_running),
                cross_quote_live_ready=False)


def _positive(value, label, *, zero_ok=False):
    try:
        x=Decimal(str(value))
        if not x.is_finite() or x < 0 or (x == 0 and not zero_ok):raise ValueError()
        return x
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Invalid '+label) from None


def rehearse_cross_preview(*, side, quote_currency, funding_asset, funding_available,
                           estimated_gross_usd, fee_amount, fee_currency, usd_per_fee,
                           usd_limit, quoted_funding_units, proposed_base_units=None, slippage_bps='20'):
    """USD stress test of authenticated preview, NON-EXECUTABLE.

    Requires actual Coinbase fee in quote currency (the only fee currency
    supported by existing verified_cross_order), plus an additional slippage
    reserve, *and* a finite total funding debit within the enrolled wallet.
    No assumption that a USDT, USDC, BTC or ETH equals USD.
    """
    side=str(side).upper(); quote=str(quote_currency).upper()
    if side not in ('BUY','SELL'):
        raise ValueError('Cross rehearsal requires BUY or SELL')
    if str(fee_currency).upper()!=quote:
        raise ValueError('Fee currency differs from quote; production settlement unsupported')
    if side=='BUY' and str(funding_asset).upper()!=quote:
        raise ValueError('BUY funding must be the explicit quoted currency')
    fee=_positive(fee_amount,'fee amount',zero_ok=True)
    fx=_positive(usd_per_fee,'fee/USD conversion')
    gross=_positive(estimated_gross_usd,'USD gross')
    limit=_positive(usd_limit,'per-order USD cap')
    slip=_positive(slippage_bps,'slippage reserve bps',zero_ok=True)
    if slip>Decimal('100'):raise ValueError('Excessive slippage reserve request')
    fee_usd=fee*fx
    if fee_usd>gross*Decimal('.05'):
        raise ValueError('Coinbase preview fee exceeds 5% safety ceiling')
    stressed=gross*(1+slip/Decimal(10000))+fee_usd
    if stressed>limit:
        raise ValueError('Preview fee + slippage exceed USD-normalized per-order cap')
    available=_positive(funding_available,'enrolled/current funding quantity')
    spend=_positive(quoted_funding_units,'quote notional')
    if side=='BUY':
        if spend*(1+slip/Decimal(10000))+fee>available:
            raise ValueError('Insufficient authorized quote wallet after fee and slippage')
    else:
        base=_positive(proposed_base_units,'proposed SELL base units')
        if base>available:
            raise ValueError('SELL exceeds approved/current available base inventory')
        if fee>spend:
            raise ValueError('SELL quote fee exceeds preview gross proceeds')
    return {'state':'REHEARSAL_PASS_NO_POST','live_eligible':False,
            'order_submitted':False,'fee_currency':quote,
            'preview_fee_usd':format(fee_usd,'f'),
            'stressed_commitment_usd':format(stressed,'f'),
            'usd_cap':format(limit,'f'),
            'caveat':'No real Coinbase order; no production FIFO settlement or recovery authorization'}
