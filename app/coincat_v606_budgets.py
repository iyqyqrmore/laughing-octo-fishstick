"""v60.6 explicit SHADOW manual budgeting; preference only, NEVER broker ARM authorization.

The accepted user input is not an account balance. SHADOW must compute a
separate actual-wallet effective limit before each modeled route. The backend
broker retains ALL independent hard controls if live posting is ever certified.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json

DEFAULT = {"per_order_usd":"10", "daily_buy_usd":"30", "added_exposure_usd":"30", "attempts_24h":"12", "mode":"MANUAL"}
MAX_INPUT = Decimal('1000000000')


def validate(values):
    if not isinstance(values,dict):raise ValueError('Invalid manual budget format')
    mode=str(values.get('mode','MANUAL')).strip().upper()
    if mode not in ('MANUAL','FULL_AVAILABLE'):
        raise ValueError('SHADOW budget mode must be MANUAL or FULL_AVAILABLE')
    answer={'mode':mode}
    for key in ('per_order_usd','daily_buy_usd','added_exposure_usd'):
        try: v=Decimal(str(values[key]).strip())
        except (KeyError,InvalidOperation,TypeError,ValueError):raise ValueError(f'Invalid {key}') from None
        if not v.is_finite() or not Decimal('0.01')<=v<=MAX_INPUT:
            raise ValueError(f'{key} must be from $0.01 to $1 billion')
        answer[key]=format(v,'f')
    raw=str(values.get('attempts_24h','')).strip()
    if not raw.isdecimal() or not 0<int(raw)<=1000000:
        raise ValueError('24-hour conversion attempts must be a positive whole number up to 1 million')
    answer['attempts_24h']=str(int(raw))
    return answer


def load(path):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        return validate(data)
    except (OSError,ValueError,TypeError):
        return dict(DEFAULT)


def save(path,values):
    data=validate(values)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)
    return data


def effective(values,verified_funding_usd):
    """SHADOW-only caps. Clamp order/exposure amounts to verified modeled fuel.

    No capital emerges from typing big numbers; positive FX funding is required.
    Caps are never enlarged by AI Lab suggestions, training or event signals.
    """
    settings=validate(values)
    try:fund=Decimal(str(verified_funding_usd))
    except (InvalidOperation,TypeError,ValueError):return None
    if not fund.is_finite() or fund<=0:return None
    # Attempts are counts, not dollars. Turnover may recycle the same fuel;
    # honor the user's explicit 24h limits instead of inventing wallet-sized
    # daily turnover or one-attempt-per-dollar limits. No LIVE change.
    attempts=int(settings['attempts_24h'])
    if settings['mode']=='FULL_AVAILABLE':
        # Operator chooses full AVAILABLE fuel, not a fictitious balance.
        # Recompute from newly modeled SHADOW wallet per scan, never the broker.
        return {'mode':'FULL_AVAILABLE',
                'per_order_usd':str(fund), 'daily_buy_usd':settings['daily_buy_usd'],
                'incremental_exposure_usd':str(fund),'max_attempts':str(attempts),
                'verified_funding_usd':str(fund),
                'clamped':False}
    return {'mode':'MANUAL',
            'per_order_usd':str(min(fund,Decimal(settings['per_order_usd']))),
            'daily_buy_usd':settings['daily_buy_usd'],
            'incremental_exposure_usd':str(min(fund,Decimal(settings['added_exposure_usd']))),
            'max_attempts':str(attempts),'verified_funding_usd':str(fund),
            'clamped':fund<max(Decimal(settings['per_order_usd']),Decimal(settings['added_exposure_usd']))}
