"""Explicit fresh v1.05 initialization; never reset or import an old dataset.

Existing protected financial schemas and verified-copy routines are reused.
Only a new empty destination is accepted. No credentials or Coinbase requests.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json

from coincat_state_v50 import data_root,StateError,MARKER,LEDGER,_reject_link
from coincat_data_transfer import import_private_data,verify_active


CONFIRMATION='CREATE NEW COINCAT V100'


def initialize_fresh(destination=None,*,confirmation):
    if confirmation!=CONFIRMATION:raise StateError('Explicit new-installation confirmation required.')
    dst=Path(destination) if destination is not None else data_root()
    dst=dst.expanduser().absolute();_reject_link(dst)
    if dst.exists() and (not dst.is_dir() or any(dst.iterdir())):
        raise StateError('Existing data must be preserved. Fresh setup never resets, overwrites or merges it.')
    dst.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.coincat-v1.05-new-',dir=dst.parent) as folder:
        src=Path(folder)/'new_dataset';src.mkdir()
        from coincat_live import LiveLedger
        LiveLedger(src/LEDGER)  # New schema only; never an existing user ledger.
        (src/MARKER).write_text(json.dumps({'format':'coincat-v60-state-v1',
            'source':'explicit-fresh','created_for':'CoinCat v1.05'}),encoding='utf8')
        # Creates verified independent snapshots without editing the importer.
        result=import_private_data(src,dst)
    verify_active(dst)
    return result


def first_run_wizard():
    import tkinter as tk
    from tkinter import messagebox
    ui=tk.Tk();ui.withdraw()
    try:
        if not messagebox.askokcancel('CoinCat v1.05 • first-time setup',
            'Create NEW local CoinCat v1.05 data in this installation?\n\n'
            'Your new Coinbase API key will be selected inside the app. '
            'No older credentials, databases or settings will be imported.\n\n'
            'Historical trades and tax cost bases cannot be recovered from a new API key alone. '
            'Keep a private backup of your old records before deleting old folders. '
            'LIVE trading remains blocked.',parent=ui):return False
        initialize_fresh(confirmation=CONFIRMATION)
        return True
    except (StateError,OSError,ValueError) as exc:
        messagebox.showerror('New setup blocked',str(exc),parent=ui)
        return False
    finally:ui.destroy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--new',action='store_true')
    p.parse_args()
    return 0 if first_run_wizard() else 2


if __name__=='__main__':raise SystemExit(main())
