"""Fee-aware planning only; not a forecast or a guarantee of profit."""
from decimal import Decimal
from coincat_live import D,minimum_exit_price

def target_exit_for_dollars(entry_ask,stake,net_dollars,buy_fee_rate=None,sell_fee_rate=None,slippage_bps=15):
    if buy_fee_rate is None or sell_fee_rate is None:
        raise ValueError('Verified fees must be provided; no fixed default')
    entry_ask=D(entry_ask);stake=D(stake);net_dollars=D(net_dollars)
    if min(entry_ask,stake)<=0 or net_dollars<0:raise ValueError('positive price/stake, nonnegative target required')
    pct=net_dollars/stake
    bid=minimum_exit_price(entry_ask,D(buy_fee_rate),D(sell_fee_rate),pct,slippage_bps)
    return dict(target_bid=bid,required_move_pct=(bid/entry_ask-1)*100,net_target_usd=net_dollars)

