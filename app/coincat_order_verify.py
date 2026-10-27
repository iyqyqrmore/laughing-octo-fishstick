"""CoinCat v40 read-only Coinbase order/fill cross-check.

No trades, cancels, transfers, ledger writes, or enrollment changes.
This is a communication diagnostic, NOT permission to start trading.
"""
from coincat_fill_units import summarize_fills,verify_order_totals
from coincat_live import as_dict


def verify_latest_filled_order(client, ledger):
    """Inspect the most recent locally FILLED order via GET and compare all fill pages."""
    previous=next((r for r in ledger.orders() if r.get('state')=='FILLED' and r.get('order_id')),None)
    if not previous:return {'state':'NONE','message':'No locally confirmed FILLED CoinCat order to verify'}
    oid=previous['order_id']
    response=as_dict(client.get_order(order_id=oid)).get('order') or {}
    if str(response.get('order_id') or '')!=str(oid):raise ValueError('Coinbase order ID did not match the local record')
    if response.get('product_id')!=previous['pair'] or str(response.get('side','')).upper()!=previous['side']:
        raise ValueError('Coinbase pair/side did not match the local record')
    if str(response.get('status','')).upper() not in ('FILLED','COMPLETED'):
        raise ValueError('Coinbase does not consider the local FILLED order completed')
    fills=[];cursor=None;seen=set()
    for _ in range(20):
        params={'order_ids':[oid],'limit':100}
        if cursor:params['cursor']=cursor
        page=as_dict(client.get_fills(**params))
        if not isinstance(page.get('fills'),list):raise ValueError('Invalid Coinbase fill response')
        fills.extend(page['fills'])
        if not page.get('has_next'):break
        cursor=page.get('cursor')
        if not cursor or cursor in seen:raise ValueError('Uncertain Coinbase fill pagination')
        seen.add(cursor)
    else:raise ValueError('More than 20 Coinbase fill pages; review manually')
    data=summarize_fills(fills,order_id=oid,pair=previous['pair'],side=previous['side'])
    verify_order_totals(response,data)
    return dict(state='MATCH',pair=previous['pair'],side=previous['side'],
                base_qty=str(data['base_qty']),gross_quote=str(data['quote_qty']),
                fees=str(data['fees']),n_fills=data['count'],
                message='Coinbase GET order and individual fills matched; no orders submitted')
