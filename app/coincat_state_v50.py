"""CoinCat v60 independent local state bootstrap, COPY-only from older data.

Never touches Coinbase and never deletes/rewrites source financial records.
Moving legacy records is unsafe without a full copy and SQLite validation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

NEW_NAME = 'CoinCatV70'
LEGACY_NAME = 'CoinCatV40'
MARKER = '.coincat_v60_state_ready.json'
LEDGER = 'CoinCat_Live_Orders.sqlite3'
SKIP_NAMES = {'coincat_v30_instance.lock', 'coincat_v40_instance.lock', 'coincat_v50_instance.lock', 'coincat_v60_instance.lock'}
SKIP_SUFFIXES = ('-wal', '-shm', '-journal')
SQLITE_SUFFIXES = ('.sqlite', '.sqlite3', '.db')

class StateError(RuntimeError):
    pass


def appdata() -> Path:
    return Path(os.environ.get('APPDATA') or Path.home())


def data_root() -> Path:
    return Path(os.environ.get('COINCAT_DATA_DIR') or appdata() / NEW_NAME)


def state_status(root=None):
    """Fail closed if V60 data was not verified; never silently create an empty ledger."""
    root = Path(root) if root is not None else data_root()
    marker = root / MARKER
    if not marker.is_file() or marker.is_symlink():
        raise StateError(f'CoinCat v70 verified state missing at {root}. Use the first-start migration screen to copy verified PRIVATE data or choose a complete backup. No ledger was created.')
    try:
        m = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise StateError('CoinCat v70 legacy-compatible state marker is invalid; stop and verify your separate PRIVATE backup.') from exc
    if m.get('format') != 'coincat-v60-state-v1' or m.get('source') not in ('legacy-copy', 'private-backup-copy', 'explicit-fresh', 'verified-existing'):
        raise StateError('Unknown CoinCat state migration marker; live startup blocked.')
    if not (root / LEDGER).is_file() or (root / LEDGER).is_symlink():
        raise StateError('CoinCat financial ledger is missing; blocked to protect original authorized holdings and lots.')
    # An empty/fresh marker must NEVER be inferred from a missing backup.
    try:
        with closing(sqlite3.connect((root / LEDGER).as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise StateError('CoinCat financial ledger failed SQLite quick_check; do not arm.')
            has_orders = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
            if not has_orders:
                raise StateError('CoinCat financial ledger has no orders schema; migration may be incomplete.')
    except sqlite3.Error as exc:
        raise StateError('Cannot validate CoinCat ledger; keep DISARMED and restore/review backup.') from exc
    return {'path': root, 'source': m['source']}


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_snapshot(src: Path, dst: Path):
    """SQLite online backup for coherent copies; source remains read-only."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(src.as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
        with closing(sqlite3.connect(dst, timeout=10)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise StateError(f'Copied SQLite database failed integrity_check: {src.name}')


@contextmanager
def _source_guard(root: Path):
    """Non-mutating cooperative lock probe if an old CoinCat lock exists.

    If the lock does not exist, the user MUST still close all programs; the
    migration itself does not create/modify files under its source directory.
    """
    lock = next((root / n for n in ('coincat_v50_instance.lock','coincat_v40_instance.lock','coincat_v30_instance.lock') if (root/n).exists()), root/'coincat_v60_instance.lock')
    if not lock.exists():
        yield
        return
    if lock.is_symlink() or not lock.is_file():
        raise StateError('Unexpected or symlinked CoinCat source lock; blocked.')
    try:
        handle = lock.open('r+b')
    except OSError as exc:
        raise StateError('Unable to check CoinCat source lock; close all CoinCat windows.') from exc
    with handle:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise StateError('Another CoinCat process may hold the source ledger lock; close all CoinCat windows.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate(source: Path, destination: Path | None = None):
    """Atomic verified directory copy from legacy APPDATA or an explicit private backup.

    Source and destination are not deleted or overwritten on any failure.
    """
    raw_src = Path(source).expanduser()
    if raw_src.is_symlink():
        raise StateError('Source directory is a symlink; refusing migration.')
    src = raw_src.resolve()
    dst = Path(destination) if destination is not None else data_root()
    dst = dst.expanduser().absolute()
    if not src.is_dir() or src.is_symlink():
        raise StateError('Source folder not found or is a symlink. Provide a COMPLETE private CoinCat data backup; no old program installation is required.')
    if src == dst or src in dst.parents or dst in src.parents:
        raise StateError('Source and destination must be separate folders (no nested copies).')
    if src.name.lower() == 'coincatv50':
        marker = src / '.coincat_v50_state_ready.json'
        if not marker.is_file() or marker.is_symlink():
            raise StateError('Old V50 source has no verified state marker. Select a complete verified backup.')
        try:
            old_state = json.loads(marker.read_text(encoding='utf-8'))
            if old_state.get('format') != 'coincat-v50-state-v1':
                raise ValueError('old marker format')
        except (ValueError, OSError) as exc:
            raise StateError('Old V50 state marker invalid; original not touched.') from exc
    if not (src / LEDGER).is_file() or (src / LEDGER).is_symlink():
        raise StateError(f'Financial ledger {LEDGER} not found in source. No partial/empty migration allowed.')
    if dst.exists():
        if dst.is_symlink() or any(dst.iterdir()):
            raise StateError('Destination CoinCatV70 already contains data. REFUSING overwrite or merge; inspect existing v40 state before proceeding.')
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='CoinCatV70_Migration_', dir=str(dst.parent)))
    published = False
    count = 0
    try:
        with _source_guard(src):
            for base, dirs, files in os.walk(src, followlinks=False):
                here = Path(base)
                for dirname in dirs:
                    if (here / dirname).is_symlink():
                        raise StateError('Symlink directory in source; migration blocked.')
                rel = here.relative_to(src)
                (staging / rel).mkdir(parents=True, exist_ok=True)
                for filename in files:
                    srcfile = here / filename
                    if srcfile.is_symlink():
                        raise StateError('Symlink file in source; migration blocked.')
                    if filename in SKIP_NAMES or filename.lower().endswith(SKIP_SUFFIXES) or filename in (MARKER, '.coincat_v40_state_ready.json', '.coincat_v50_state_ready.json'):
                        continue
                    target = staging / rel / filename
                    if srcfile.suffix.lower() in SQLITE_SUFFIXES:
                        _sqlite_snapshot(srcfile, target)
                    elif srcfile.is_file():
                        shutil.copy2(srcfile, target)
                        if _file_sha256(srcfile) != _file_sha256(target):
                            raise StateError('Verification mismatch after copying '+filename)
                    else:
                        raise StateError('Unexpected source entry, refusing partial copy.')
                    count += 1
        if not count or not (staging / LEDGER).is_file():
            raise StateError('No complete ledger/data copied; migration refused.')
        # Validate ledger schema and integrity before revealing as a live state root.
        with closing(sqlite3.connect((staging / LEDGER).as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise StateError('Financial ledger copy failed SQLite integrity_check.')
            if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'").fetchone():
                raise StateError('Ledger missing orders schema. Refusing incomplete state.')
        metadata = {
            'format': 'coincat-v60-state-v1',
            'source': ('legacy-copy' if src.name.lower() == LEGACY_NAME.lower() else 'private-backup-copy'),
            'verified_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'files_copied': count,
        }
        (staging / MARKER).write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
        if dst.is_dir():
            dst.rmdir()  # only possible when empty (explicitly checked above)
        staging.rename(dst)  # same APPDATA volume, atomic rename
        published = True
        state_status(dst)
        return {'path': dst, 'copied_files': count, 'source': src}
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)



def activate_existing(root: Path | None = None):
    """Register already-existing v40 financial state; never initialize a new ledger.

    The optional marker is the ONLY written file, and its creation is explicit.
    This does not imply Coinbase reconciliation or permission to ARM.
    """
    root = Path(root) if root is not None else data_root()
    if root.is_symlink() or not root.is_dir():
        raise StateError('CoinCat v60 private-data folder does not exist. Import your complete private backup first.')
    if (root / MARKER).exists():
        return state_status(root)
    ledger = root / LEDGER
    if ledger.is_symlink() or not ledger.is_file():
        raise StateError('No existing CoinCat financial ledger in the v60 data folder. Refusing to create an empty ledger.')
    try:
        with closing(sqlite3.connect(ledger.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise StateError('Existing v40 financial ledger failed integrity_check.')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {'orders', 'fills', 'enrollment', 'risk', 'inventory_lots', 'inventory_disposals'}
            if expected - tables:
                raise StateError('Existing v40 financial ledger is missing financial/inventory tables. No state was activated.')
            if db.execute('SELECT COUNT(*) FROM enrollment').fetchone()[0] == 0 and db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0:
                raise StateError('Existing ledger has no approvals AND no order history. Verify the backup; no empty ledger activated.')
    except sqlite3.Error as exc:
        raise StateError('Existing v40 ledger cannot be validated. No state was activated.') from exc
    record = {'format':'coincat-v60-state-v1', 'source':'verified-existing',
              'verified_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    # 'x' guarantees an existing marker cannot be clobbered by concurrent use.
    marker = root / MARKER
    try:
        with marker.open('x', encoding='utf-8') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
        return state_status(root)
    except FileExistsError as exc:
        raise StateError('Another process created a state marker. Re-run verification; no overwrite performed.') from exc

def cli(argv=None):
    parser = argparse.ArgumentParser(description='Offline, copy-only CoinCat v60 private data migration/verification')
    parser.add_argument('operation', choices=('verify', 'migrate', 'import', 'activate'))
    parser.add_argument('--source', help='Complete private backup of CoinCat state (no old program folder required)')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'activate':
            result = activate_existing()
            print('V60 EXISTING PRIVATE DATA VERIFIED AND ACTIVATED:', result['path'])
            print('Only a v40 verification marker was created; financial records were not edited.')
        elif args.operation == 'verify':
            result = state_status()
            print('V60 PRIVATE DATA VERIFIED:', result['path'])
            print('Source type:',result['source'])
        else:
            if not args.source:
                raise StateError('Specify --source with the COMPLETE private backup directory.')
            result = migrate(Path(args.source))
            print('V60 COPY-ONLY DATA MIGRATION VERIFIED:',result['path'])
            print('Private files copied:',result['copied_files'])
            print('Original source left in place; do not delete your private backup.')
        print('No Coinbase network access or order submissions performed.')
        return 0
    except (OSError, sqlite3.Error, StateError) as exc:
        print('V60 DATA BLOCKED:',exc)
        return 2

if __name__ == '__main__':
    raise SystemExit(cli())
