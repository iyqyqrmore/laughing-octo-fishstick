"""CoinCat v40 observed order/fill-frequency counters. READ ONLY.

Measured throughput is descriptive, NEVER an auto-trading recommendation or
permission to increase the user's approved stage limits.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from coincat_live import sql,D


def frequency_report(ledger,now):
    """Uses verified LOCAL fills only, grouped by UTC date. No Coinbase calls."""
    day=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    with sql(ledger.path) as c:
        orders=c.execute('SELECT side,state,created_at FROM orders WHERE created_at>=?',(int(day),)).fetchall()
        fills=c.execute('''SELECT f.side,f.order_id,f.base_qty,f.price,f.fee_quote,
           f.performance_realized_quote,f.net_realized_quote FROM fills f
           WHERE f.at_utc>=?''',(int(day),)).fetchall()
    counters={'order_attempts':len(orders),
              'buy_attempts':sum(r['side']=='BUY' for r in orders),
              'sell_attempts':sum(r['side']=='SELL' for r in orders),
              'acknowledged_or_pending':sum(r['state'] not in ('FILLED','REJECTED','FAILED','CANCELLED','EXPIRED') for r in orders),
              'filled_buy_orders':len({r['order_id'] for r in fills if r['side']=='BUY'}),
              'filled_sell_orders':len({r['order_id'] for r in fills if r['side']=='SELL'}),
              'buy_fill_records':sum(r['side']=='BUY' for r in fills),
              'sell_fill_records':sum(r['side']=='SELL' for r in fills),
              'verified_sell_fees':str(sum((D(r['fee_quote']) for r in fills if r['side']=='SELL'),Decimal(0)))}
    pnl={}
    for r in fills:
        if r['side']=='SELL':
            v=r['performance_realized_quote'] if r['performance_realized_quote'] is not None else r['net_realized_quote']
            if v is not None:pnl[r['order_id']]=pnl.get(r['order_id'],Decimal(0))+D(v)
    counters['profitable_sell_orders']=sum(v>0 for v in pnl.values())
    counters['loss_or_even_sell_orders']=sum(v<=0 for v in pnl.values())
    counters['realized_after_fee_result']=str(sum(pnl.values(),Decimal(0)))
    counters['day_utc']=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
    return counters
