"""READ-ONLY comparison of enrolled quantities to refreshed Coinbase AVAILABLE balances.

The user may trade manually outside CoinCat. This does not overwrite tax lots or
silently enroll deposits. A material SHORTFALL disarms/blocks until reconciled.
"""
from decimal import Decimal


def compare_managed_balances(approved, live):
    differences=[]
    for asset in approved:
        name=str(asset['asset'])
        if name in ('USD','USDC') or not asset.get('enabled',1):
            continue
        qty=Decimal(str(asset.get('remaining_qty') or '0'))
        if qty<=0:continue
        available=Decimal(str(live.get(name,0)))
        # Tolerance only covers rounding, not a sale or externally held quantity.
        tolerance=max(Decimal('0.00000001'), qty*Decimal('0.001'))
        if qty>available+tolerance:
            differences.append({'asset':name,'approved':str(qty),'available':str(available),
                                'shortfall':str(qty-available)})
    return differences
