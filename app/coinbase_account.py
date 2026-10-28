"""Read-only Coinbase Advanced Trade account adapter + Windows-user DPAPI vault.

This module deliberately has NO authenticated order, transfer, or write endpoints.
Secrets are only sent by Coinbase's official SDK to api.coinbase.com.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path


def as_dict(response):
    if isinstance(response, dict):
        return response
    if hasattr(response, 'to_dict'):
        return response.to_dict()
    raise ValueError('Unexpected Coinbase SDK response format')


def parse_key_json(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError('Choose a CDP JSON key file downloaded from Coinbase Developer Platform.') from exc
    name = str(value.get('name') or value.get('apiKeyName') or '').strip()
    key = str(value.get('privateKey') or value.get('private_key') or '').strip()
    if not name.startswith('organizations/') or '/apiKeys/' not in name:
        raise ValueError('Missing CDP key name (organizations/.../apiKeys/...).')
    if not key or (len(key) < 30):
        raise ValueError('Missing CDP privateKey. Please select the JSON file with both fields.')
    return {'name': name, 'privateKey': key.replace('\\n', '\n')}


def decimal_or_zero(value):
    try:
        n=Decimal(str(value or '0'))
        return n if n.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def read_account_snapshot(credentials: dict, include_fills: bool = True) -> dict:
    """Read-only SDK methods; paginates balances, fetches first page of trade fills."""
    from coinbase.rest import RESTClient
    client=RESTClient(api_key=credentials['name'], api_secret=credentials['privateKey'], timeout=16, verbose=False)
    try:
        permissions = as_dict(client.get_api_key_permissions())
    except Exception:
        permissions = {}  # Permission endpoint may be unavailable; never presume missing = disabled.
    accounts=[]; cursor=None; seen=set(); complete=False
    for _ in range(30):
        result=as_dict(client.get_accounts(limit=250, **({'cursor':cursor} if cursor else {})))
        if not isinstance(result.get('accounts'), list):
            raise ValueError('Coinbase did not supply a recognized accounts list')
        accounts.extend(result['accounts'])
        if not result.get('has_next'):
            complete=True
            break
        cursor=result.get('cursor')
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    fills=[]; fills_message='Not requested'
    if include_fills:
        try:
            data=as_dict(client.get_fills(limit=50))
            fills=data.get('fills',[])
            if not isinstance(fills,list): fills=[]
            fills_message='Most recent 50 fills, not a complete tax ledger'
        except Exception:
            fills_message='Fill history unavailable with this key; balances may still work'
    return {'accounts':accounts, 'complete':complete, 'permissions':permissions,
            'fills':fills, 'fills_message':fills_message}


def aggregate_balances(accounts):
    """Merge account rows without counting the same holding twice within a row."""
    merged={}
    for item in accounts:
        currency=str(item.get('currency') or '').upper().strip()
        if not currency: continue
        avail=decimal_or_zero((item.get('available_balance') or {}).get('value'))
        hold=decimal_or_zero((item.get('hold') or {}).get('value'))
        entry=merged.setdefault(currency, {'available':Decimal(0),'hold':Decimal(0),'account_count':0})
        entry['available'] += avail
        entry['hold'] += hold
        entry['account_count'] += 1
    for entry in merged.values():
        entry['total'] = entry['available'] + entry['hold']
    return merged


def key_permission_text(permissions: dict) -> str:
    # Coinbase response versions may vary; avoid assuming a missing field means 'No'.
    words=[]
    for flag in ('can_view','can_trade','can_transfer'):
        raw=permissions.get(flag)
        if isinstance(raw,bool):
            words.append(f"{flag.replace('can_', '').upper()}: {'YES' if raw else 'NO'}")
        else:
            words.append(f"{flag.replace('can_', '').upper()}: unreported")
    return '   •   '.join(words)


def encrypted_key_path() -> Path:
    from coincat_state_v50 import data_root
    folder=data_root()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'coinbase_key.dpapi'


class _DATA_BLOB(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_char))]


def _blob_from_bytes(value: bytes):
    buffer=ctypes.create_string_buffer(value)
    return _DATA_BLOB(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_char))),buffer


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    if os.name != 'nt':
        raise OSError('Encrypted credential saving is available on Windows only.')
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kern=ctypes.WinDLL('kernel32',use_last_error=True)
    operation=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.restype=wintypes.BOOL
    if decrypt:
        operation.argtypes=[ctypes.POINTER(_DATA_BLOB),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_DATA_BLOB)]
    else:
        operation.argtypes=[ctypes.POINTER(_DATA_BLOB),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_DATA_BLOB)]
    kern.LocalFree.argtypes=[ctypes.c_void_p]
    kern.LocalFree.restype=ctypes.c_void_p
    source,keeper=_blob_from_bytes(data)
    dest=_DATA_BLOB()
    ok=operation(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(dest.pbData,dest.cbData)
    finally:
        kern.LocalFree(ctypes.cast(dest.pbData,ctypes.c_void_p))


def save_encrypted(credentials: dict):
    blob=_dpapi(json.dumps(credentials,separators=(',',':')).encode('utf-8'),False)
    target=encrypted_key_path()
    temporary=target.with_suffix('.tmp')
    temporary.write_bytes(blob)
    temporary.replace(target)


def load_encrypted() -> dict | None:
    target=encrypted_key_path()
    if not target.exists(): return None
    payload=_dpapi(target.read_bytes(),True)
    return parse_key_json(payload.decode('utf-8'))


def remove_saved_key():
    encrypted_key_path().unlink(missing_ok=True)
