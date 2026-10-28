"""Offline private-data cut-over with an independent verified backup.

Never deletes a source, merges datasets, changes financial schemas, decrypts a
vault, or contacts Coinbase. Receipts contain fingerprints, never record values.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid

from coincat_state_v50 import (
    data_root, state_status, migrate, StateError, MARKER, LEDGER,
    SKIP_NAMES, _source_guard, _reject_link, _walk_error, _is_sqlite_sidecar, _is_sqlite_database)

RECEIPT='.coincat_import_receipt.json'
FORMAT='coincat-portable-import-v1'
METADATA={MARKER,RECEIPT,'.coincat_v40_state_ready.json','.coincat_v50_state_ready.json'}


def installation_root():
    return Path(__file__).resolve().parents[1]


def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _db_fingerprint(path):
    h=hashlib.sha256()
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise StateError('Private SQLite integrity check failed; original was not changed.')
        for pragma in ('user_version','application_id'):
            h.update(str(db.execute('PRAGMA '+pragma).fetchone()[0]).encode()+b'\n')
        for line in db.iterdump():h.update(line.encode('utf8')+b'\n')
    return h.hexdigest()


def inventory(root):
    """Complete logical DB/file fingerprints; includes research, tax files, vault."""
    root=Path(root).absolute();_reject_link(root)
    if not root.is_dir():raise StateError('Private-data folder is missing.')
    result={}
    for base,dirs,files in os.walk(root,followlinks=False,onerror=_walk_error):
        for name in dirs:_reject_link(Path(base)/name)
        for name in sorted(files):
            path=Path(base)/name;_reject_link(path)
            if name in SKIP_NAMES or name in METADATA or _is_sqlite_sidecar(path):continue
            if not path.is_file():raise StateError('Unexpected private-data entry.')
            is_db=_is_sqlite_database(path)
            result[path.relative_to(root).as_posix()]={
                'kind':'sqlite-logical' if is_db else 'file-sha256',
                'sha256':_db_fingerprint(path) if is_db else _sha(path)}
    return result


def _receipt(root):
    path=Path(root)/RECEIPT;_reject_link(path)
    try:r=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError) as exc:raise StateError('Verified portable import receipt missing or invalid.') from exc
    if (not isinstance(r,dict) or r.get('format')!=FORMAT or not isinstance(r.get('files'),dict) or LEDGER not in r['files']
        or not all(isinstance(r.get(k),str) and r[k] for k in ('import_id','source_path','backup_relative'))):
        raise StateError('Unsupported/incomplete import receipt.')
    for name,record in r['files'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or not isinstance(record,dict):
            raise StateError('Unsafe import receipt path.')
    return r


def verify_active(root=None):
    """Normal startup reads ONLY the current data; old source/backup may be offline."""
    root=Path(root) if root is not None else data_root()
    _reject_link(root)
    state_status(root)
    r=_receipt(root)
    # A portable folder may itself be moved/renamed. All database consumers use
    # this current root; recorded old locations are audit history, not selectors.
    for name in r['files']:
        path=root/name;_reject_link(path)
        if not path.is_file():raise StateError('An imported private file is missing; restore/review the backup.')
    return {'path':root,'import_id':r['import_id'],'files':len(r['files'])}


def import_private_data(source, destination=None, backup_root=None):
    src=Path(source).expanduser().absolute();_reject_link(src)
    src=src.resolve()
    dst=Path(destination) if destination is not None else data_root()
    dst=dst.expanduser().absolute();_reject_link(dst)
    dst=dst.resolve()
    backups=Path(backup_root) if backup_root is not None else dst.parent/'private_backups'
    backups=backups.absolute();_reject_link(backups)
    backups=backups.resolve()
    if not backups.is_relative_to(dst.parent):
        raise StateError('Keep private_backups inside the new main CoinCat folder.')
    for a,b in ((src,dst),(src,backups),(dst,backups)):
        if a==b or a in b.parents or b in a.parents:
            raise StateError('Source, active data and backup must be separate non-nested folders.')
    if dst.exists() and (not dst.is_dir() or any(dst.iterdir())):
        raise StateError('Active data already exists. No overwrite or merge is allowed.')
    if not (src/LEDGER).is_file():raise StateError('Choose the PRIVATE data folder containing the complete ledger.')
    # Allow room for both the active snapshot and its independent backup, with
    # WAL bytes included conservatively. Do not begin a known partial copy.
    dst.parent.mkdir(parents=True,exist_ok=True)
    size=0
    for base,dirs,files in os.walk(src,followlinks=False,onerror=_walk_error):
        for name in dirs:_reject_link(Path(base)/name)
        for name in files:
            path=Path(base)/name;_reject_link(path)
            size+=path.stat().st_size
    if shutil.disk_usage(dst.parent).free < size*2+16*1024*1024:
        raise StateError('Insufficient free disk for verified active data plus independent backup.')
    staging_parent=Path(tempfile.mkdtemp(prefix='.coincat-import-',dir=dst.parent))
    stage=staging_parent/'private_data'
    token=uuid.uuid4().hex
    backup=backups/('import-'+token)
    try:
        # Existing importer handles coherent SQLite backup, markers and lock probes.
        migrate(src,stage)
        with _source_guard(src):
            expected=inventory(src)
            if not expected or inventory(stage)!=expected:
                raise StateError('Source changed or copied data differs. No active data was published.')
            migrate(stage,backup)
            if inventory(backup)!=expected:
                raise StateError('Independent backup verification failed. No active data was published.')
            if inventory(src)!=expected:
                raise StateError('Source changed during verification. No active data was published.')
            record={'format':FORMAT,'import_id':token,'source_path':str(src),
                'data_path_at_import':str(dst),
                'backup_relative':os.path.relpath(backup,dst.parent),
                'verified_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'files':expected}
            for root in (stage,backup):
                (root/RECEIPT).write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
            verify_active(stage)
            # Never replace a nonempty destination, including one created mid-copy.
            if dst.exists():dst.rmdir()
            stage.rename(dst)
        verify_active(dst)
        return {'path':dst,'backup':backup,'source':src,'files':len(expected)}
    finally:
        # Only this invocation's private staging directory is removed. Keep the
        # verified backup even if publication fails. The source is never removed.
        shutil.rmtree(staging_parent,ignore_errors=True)


def _backup_path(root,r):
    rel=Path(r['backup_relative'])
    if rel.is_absolute() or '..' in rel.parts:raise StateError('Unsafe backup receipt path.')
    result=Path(root).parent/rel;_reject_link(result)
    return result


def check_cleanup(candidate, root=None):
    """Read-only retirement check. No command in this module deletes old folders."""
    root=Path(root) if root is not None else data_root()
    root=root.absolute();verify_active(root)
    r=_receipt(root);backup=_backup_path(root,r)
    state_status(backup)
    if inventory(backup)!=r['files']:
        raise StateError('Independent backup is missing/changed; cleanup is blocked.')
    candidate=Path(candidate).expanduser().absolute();_reject_link(candidate)
    candidate=candidate.resolve();root=root.resolve()
    if not candidate.is_dir():raise StateError('Candidate folder not found.')
    for protected in (root,backup.parent,installation_root()):
        if candidate==protected or candidate in protected.parents or protected in candidate.parents:
            raise StateError('Current installation, active data or backups cannot be retired.')
    imported_source=Path(r['source_path'])
    if candidate==imported_source:
        with _source_guard(candidate):
            if inventory(candidate)!=r['files']:
                raise StateError('Old data changed since import. Do not delete; reconcile the divergent datasets.')
        return {'state':'ELIGIBLE_IMPORTED_SOURCE','candidate':candidate,'active':root,'backup':backup}
    # Old source ZIPs: all original source files must still match their own
    # manifest. Unknown files are not assumed disposable. Caches are regenerable.
    manifest=next((candidate/n for n in ('SHA256_MANIFEST.json','SHA256_MANIFEST_V60.json')
                   if (candidate/n).is_file()),None)
    if manifest is None:raise StateError('Not the imported source or a recognized source release. Preserve it for manual review.')
    _reject_link(manifest)
    try:known=json.loads(manifest.read_text(encoding='utf8'))['files']
    except (OSError,ValueError,KeyError) as exc:raise StateError('Old release manifest is unreadable.') from exc
    if not isinstance(known,dict):raise StateError('Invalid old release manifest.')
    with _source_guard(candidate):
        for base,dirs,files in os.walk(candidate,followlinks=False,onerror=_walk_error):
            here=Path(base)
            for name in dirs:_reject_link(here/name)
            if '.git' in dirs:raise StateError('Old checkout has Git history; preserve it before manual cleanup.')
            dirs[:]=[name for name in dirs if name not in ('.venv','__pycache__','.pytest_cache')]
            for name in files:
                p=here/name;_reject_link(p)
                rel=p.relative_to(candidate).as_posix()
                if p==manifest:continue
                # These shortcuts were generated by prior CoinCat releases and
                # only start their old source tree. The new setup regenerates a
                # versionless START shortcut; arbitrary shortcuts remain unknown.
                generated={f'CoinCat {version} - {label}.lnk' for version in ('v60','v70')
                    for label in ('START','DEBUG START','SETUP','VERIFY','GPU TEST',
                                  'PRIVATE DATA CHECK','FINAL SAFETY GATES','COINBASE READ ONLY')}
                if here==candidate and name in generated:continue
                if rel not in known or _sha(p)!=known[rel]:
                    raise StateError('Old folder has unverified, modified or private files. Back them up/review before cleanup.')
    return {'state':'ELIGIBLE_OLD_SOURCE_ONLY','candidate':candidate,'active':root,'backup':backup}


def import_wizard():
    import tkinter as tk
    from tkinter import messagebox,filedialog
    ui=tk.Tk();ui.withdraw()
    try:
        dst=data_root()
        if dst.exists() and any(dst.iterdir()):
            messagebox.showerror('Private data import','The new private_data folder already contains files. No overwrite or merge.',parent=ui)
            return False
        old=Path(os.environ.get('APPDATA') or Path.home())/'CoinCatV70'
        source=None
        if old.is_dir() and messagebox.askyesno('Import current CoinCat data',
            'Use your existing CoinCatV70 private data as the source?\n\n'+str(old),parent=ui):source=old
        if source is None:
            choice=filedialog.askdirectory(parent=ui,title='Choose COMPLETE private data or backup folder containing CoinCat_Live_Orders.sqlite3')
            if not choice:return False
            source=Path(choice)
            if not (source/LEDGER).is_file() and (source/'private_data'/LEDGER).is_file():source=source/'private_data'
        if not messagebox.askokcancel('Verified copy — close every CoinCat version',
            'Copy all private databases, encrypted credentials, settings, tax files and research?\n\n'
            'From: '+str(source)+'\nTo: '+str(dst)+'\nBackup: '+str(dst.parent/'private_backups')+
            '\n\nClose ALL older CoinCat processes first. Sources will not be deleted or merged. '
            'The encrypted vault remains tied to the same Windows user. LIVE stays blocked.',parent=ui):return False
        # Keep the standalone import window responsive while copying large
        # research stores. There is no running app or trade worker in this UI.
        import threading
        from tkinter import ttk
        ui.deiconify();ui.title('CoinCat — verifying private data copy')
        ui.protocol('WM_DELETE_WINDOW',lambda:None)
        ttk.Label(ui,text='Copying and verifying databases and backup. Please keep this window open.',
                  padding=20).pack()
        bar=ttk.Progressbar(ui,mode='indeterminate');bar.pack(fill='x',padx=20,pady=15);bar.start(20)
        result_box={};finished=threading.Event()
        def copy():
            try:result_box['result']=import_private_data(source)
            except Exception as exc:result_box['error']=exc
            finally:finished.set()
        threading.Thread(target=copy,daemon=True).start()
        while not finished.wait(.05):ui.update()
        bar.stop();ui.withdraw()
        if 'error' in result_box:raise result_box['error']
        result=result_box['result']
        messagebox.showinfo('Private data copied and verified',
            f"Verified {result['files']} private files.\nActive: {result['path']}\nBackup: {result['backup']}\n\n"
            'Run 05_CHECK_CLEANUP.bat on an old folder before deleting it manually. No old folder was deleted.',parent=ui)
        return True
    except (StateError,OSError,sqlite3.Error,ValueError) as exc:
        detail=str(exc) if isinstance(exc,StateError) else type(exc).__name__+' during copy/verification. Preserve originals and backups.'
        messagebox.showerror('Private data import BLOCKED',detail,parent=ui)
        return False
    finally:ui.destroy()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('import','verify','check'))
    p.add_argument('--source');p.add_argument('--candidate');p.add_argument('--pick-folder',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.operation=='import':
            if args.source:result=import_private_data(Path(args.source))
            else:return 0 if import_wizard() else 2
        elif args.operation=='verify':result=verify_active()
        else:
            candidate=args.candidate
            if args.pick_folder:
                import tkinter as tk
                from tkinter import filedialog
                ui=tk.Tk();ui.withdraw()
                try:candidate=filedialog.askdirectory(parent=ui,title='Choose OLD folder to check — nothing will be deleted')
                finally:ui.destroy()
            if not candidate:raise StateError('Choose an old folder to inspect; no deletion was performed.')
            result=check_cleanup(candidate)
        print('PASS: Active private data:',result.get('path',result.get('active')))
        if 'files' in result:print('Imported private files verified:',result['files'])
        if 'backup' in result:print('Verified independent backup:',result['backup'])
        if 'candidate' in result:
            print('Old folder checked:',result['candidate'])
            print('Eligible for MANUAL cleanup. First confirm the current CoinCat starts from this main folder.')
        print('No old files were deleted. Keep private_data and private_backups; LIVE remains blocked.')
        return 0
    except (StateError,OSError,sqlite3.Error,ValueError) as exc:
        detail=str(exc) if isinstance(exc,StateError) else type(exc).__name__+' during copy/verification; originals retained.'
        print('BLOCKED:',detail);return 2


if __name__=='__main__':raise SystemExit(main())
