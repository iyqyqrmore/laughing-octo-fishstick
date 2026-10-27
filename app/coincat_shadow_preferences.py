"""Read-only research settings (NOT financial lots, Coinbase trading limits or ARM)."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json, os

DEFAULT = Decimal('0.10')

def validate_amount(amount):
    raw=str(amount)
    if 'e' in raw.lower() or raw.count('.')>1:
        raise ValueError('Use ordinary dollar decimals')
    try: number=Decimal(raw)
    except (InvalidOperation,TypeError,ValueError) as e: raise ValueError('Invalid research floor') from e
    if not number.is_finite() or not Decimal('.01') <= number <= Decimal('10000') or number.as_tuple().exponent < -2:
        raise ValueError('Research floor must be between $0.01 and $10,000.00, in whole cents')
    return number

def load(path):
    try:
        payload=json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('schema')!='shadow-preference-v1':raise ValueError('Unknown preference file')
        mode=payload['mode']
        if mode not in ('MANUAL','AI_SUGGESTED'):raise ValueError('Invalid mode')
        return {'mode':mode,'manual_usd':validate_amount(payload['manual_usd'])}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,OverflowError):
        return {'mode':'MANUAL','manual_usd':DEFAULT}

def save(path,mode,manual_usd):
    if mode not in ('MANUAL','AI_SUGGESTED'):raise ValueError('Invalid mode')
    amount=validate_amount(manual_usd)
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp')
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump({'schema':'shadow-preference-v1','mode':mode,'manual_usd':format(amount,'.2f')},f,sort_keys=True)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if tmp.exists():tmp.unlink()
    return {'mode':mode,'manual_usd':amount}

# Critical invariant: no importing CoinCat's production broker or financial ledger.
