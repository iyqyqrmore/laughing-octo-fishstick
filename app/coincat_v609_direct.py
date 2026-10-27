"""v60.9 authenticated product-ID crypto/crypto one-order research policy.

The spot catalog and rules must originate from authenticated Coinbase GETs.
This module does not connect to Coinbase, mutate enrollment, or submit orders.
USD pricebooks remain necessary to VALUE profit; they are not trade legs.
"""
from __future__ import annotations

NON_CRYPTO_QUOTES=frozenset({'USD','USDC','USDT','DAI','EUR','GBP','CAD','AUD','JPY','CHF','BRL','SGD','PYUSD','EURC','FDUSD','TUSD'})

def direct_crypto_pairs(catalog):
    products=[]
    for pair in catalog or ():
        if not isinstance(pair,str) or pair.count('-')!=1:continue
        base,quote=pair.upper().split('-')
        if base and quote and base!=quote and base not in NON_CRYPTO_QUOTES and quote not in NON_CRYPTO_QUOTES:
            products.append(pair.upper())
    return sorted(set(products))

def distinct_catalog_assets(catalog,balances,approved):
    """All unique spot-catalog assets, holdings first. Catalog rows never enroll."""
    assets={a for p in catalog or () if isinstance(p,str) and p.count('-')==1 for a in p.upper().split('-')}
    assets|={str(a).upper() for a in balances or ()}
    assets|={str(a).upper() for a in approved or ()}
    # Preserve enrolled/excluded zero-balance assets above unowned catalog rows;
    # actual positive available balance always has priority.
    def sort(asset):
        try:quantity=float((balances or {}).get(asset,0) or 0)
        except (ValueError,TypeError,OverflowError):quantity=0
        return (0 if quantity>0 else 1 if asset in approved else 2,asset)
    return sorted(assets,key=sort)

def direct_pair_count(catalog):
    return len(direct_crypto_pairs(catalog))
