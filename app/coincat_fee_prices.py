"""Fee-aware displayed prices. These are cost benchmarks, not execution quotes."""
from decimal import Decimal as D,localcontext,ROUND_CEILING
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS


def ask_costs(pair,ask,fee_fraction,*,fee_currency,price_increment):
    if pair not in WATCH_PAIRS:raise ValueError('PRODUCT_NOT_APPROVED')
    base,quote=pair.split('-')
    if fee_currency!=quote:raise ValueError('QUOTE_FEE_UNITS_NOT_CONFIRMED')
    price,fee,tick=map(exact,(ask,fee_fraction,price_increment))
    if not price>0 or not tick>0 or not 0<=fee<D('.05'):raise ValueError('INVALID_PRICE_OR_FEE')
    with localcontext() as ctx:
        ctx.prec=60
        retain=price/(1-fee)
        return dict(pair=pair,base=base,quote=quote,market_ask=price,fee_fraction=fee,
            buy_cost_per_base=price*(1+fee),sell_net_per_base=price*(1-fee),
            sell_limit_retaining_market_ask=(retain/tick).to_integral_value(rounding=ROUND_CEILING)*tick,
            classification='FEE_COST_BENCHMARK_NOT_SUBMITTED_LIMIT')
