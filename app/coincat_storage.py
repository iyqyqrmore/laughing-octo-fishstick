"""CoinCat v40 local storage safeguards (NO trading, NO deletion of financial records).

The 1 GiB aggregate AI Lab research soft ceiling is enforced by ForwardStore. Financial
SQLite order/fill/tax lot records are NOT rolling telemetry and must NOT be
pruned. At its 128 MB active warning/stop threshold trading fails closed until
an operator arranges verified offline archival/reconciliation and a safe ledger
rotation in a separate supervised migration. Backups alone do not free space.
"""
from __future__ import annotations
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

MB = 1024 * 1024
RESEARCH_LIMIT_MIB = 1024  # Binary MiB: 1 GiB across all AI Lab research SQLite files.
LIMITS_MB = {'research': RESEARCH_LIMIT_MIB, 'ledger': 128, 'gpu': 128, 'logs': 32,
             'tax_exports': 1024}


def sqlite_files_bytes(path):
    p = Path(path)
    return sum(f.stat().st_size for f in (p, Path(str(p)+'-wal'), Path(str(p)+'-shm')) if f.is_file())


def directory_bytes(folder):
    p = Path(folder)
    if not p.is_dir():return 0
    return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())


def research_sqlite_bytes(folder):
    """Count each research SQLite DB plus WAL/SHM; never include live financial ledger.

    New relative-USD and fee caches share the same AI Lab quota rather than
    silently receiving additional unreported allowances.
    """
    folder=Path(folder)
    if not folder.is_dir():return 0
    return sum(f.stat().st_size for f in folder.iterdir()
               if f.is_file() and (f.name.endswith('.sqlite3') or
                                   f.name.endswith('.sqlite3-wal') or
                                   f.name.endswith('.sqlite3-shm')))


def storage_health(root):
    base=Path(root)
    samples={
        'research':research_sqlite_bytes(base/'research_data'),
        'ledger':sqlite_files_bytes(base/'CoinCat_Live_Orders.sqlite3'),
        'gpu':directory_bytes(base/'gpu_research'),
        'logs':directory_bytes(base/'logs'),
        # User-created CSV tax backups are archival files, NOT the live ledger.
        # 80%-of-1-GiB warnings MUST NOT pause an otherwise safe trader.
        'tax_exports':directory_bytes(base/'tax_exports'),
    }
    return {key:{'used_mb':round(value/MB,3),'limit_mb':LIMITS_MB[key],
                 'warning':value>=int(.8*LIMITS_MB[key]*MB),
                 'over':value>=LIMITS_MB[key]*MB}
            for key,value in samples.items()}


def financial_storage_gate(root):
    """Never automatically delete real trades or tax lots to meet a quota."""
    state=storage_health(root)
    # Model/checkpoint capacity is research-only; it cannot veto historical data.
    ok=not any(state[key]['over'] for key in ('ledger','research'))
    return ok,state


def verified_ledger_backup(source,destination):
    """Create a *copy* using SQLite online backup, verify integrity and hash.

    Never rotates, vacuums, truncates or removes the original financial ledger.
    Destination must not exist. Archives can consume disk space; monitor them.
    """
    src=Path(source);dest=Path(destination)
    if not src.is_file():raise FileNotFoundError(src)
    if dest.exists() or Path(str(dest)+'.sha256.json').exists():
        raise FileExistsError('Archive already exists; do not overwrite verified financial history')
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=Path(str(dest)+'.incomplete')
    if tmp.exists():raise FileExistsError('A previous incomplete archive requires manual review')
    try:
        with closing(sqlite3.connect(f'{src.resolve().as_uri()}?mode=ro',uri=True)) as source_db:
            with closing(sqlite3.connect(str(tmp))) as backup_db:source_db.backup(backup_db)
        with closing(sqlite3.connect(f'{tmp.resolve().as_uri()}?mode=ro',uri=True)) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('Archive SQLite integrity check failed')
            counts={name:check.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                    for name in ('orders','fills','inventory_lots','inventory_disposals')}
        sha=hashlib.sha256()
        with tmp.open('rb') as data:
            for chunk in iter(lambda:data.read(1024*1024),b''):sha.update(chunk)
        digest=sha.hexdigest()
        manifest={'created_utc':int(time.time()),'sha256':digest,'counts':counts,'bytes':tmp.stat().st_size,
                  'original_untouched':True,'note':'Archive copy only; original ledger remains active.'}
        os.replace(tmp,dest)
        Path(str(dest)+'.sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        return manifest
    except Exception:
        if tmp.exists():tmp.unlink()
        raise
