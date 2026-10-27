"""Read-only authenticated account reconciliation, usable while CoinCat is armed.

A balance snapshot is NOT an acquisition, a tax lot, an approval, a price signal,
or a fill. Existing authorization is never replenished by this component.
"""
from decimal import Decimal
from coincat_external_check import compare_managed_balances

def reconcile_authorized(ledger, fresh_balances, previous_balances=None):
    if not isinstance(fresh_balances,dict):raise ValueError('Coinbase balances unavailable')
    enrolled=ledger.assets()
    if not fresh_balances and any(row.get('enabled',1) and Decimal(str(row['remaining_qty']))>0 for row in enrolled):
        raise ValueError('Empty Coinbase balance response cannot verify existing inventory')
    missing=compare_managed_balances(enrolled,fresh_balances)
    # USD/USDC are spendable quote currency; a shortfall may follow a real order,
    # so do not claim it proves tax-lot mismatch. Broker revalidates per order.
    permitted={row['asset']:Decimal(str(row['remaining_qty'])) for row in enrolled if row.get('enabled',1)}
    registered={row['asset'] for row in enrolled}
    return {'safe':not missing,'shortfalls':missing,'balances':dict(fresh_balances),
            'authorized':{k:str(v) for k,v in permitted.items()},
            'new_coins':sorted(set(fresh_balances)-registered),
            'not_reenrolled':True,'not_repriced':True}
