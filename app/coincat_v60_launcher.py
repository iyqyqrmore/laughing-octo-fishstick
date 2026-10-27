"""CoinCat v60 source-run Windows entrypoint, copy-only private onboarding."""
from __future__ import annotations
import os, sys
from pathlib import Path

# Isolated V70 private copy, separate from source and V60; preserve explicit
# test COINCAT_DATA_DIR for offline tests, otherwise use the V70 location.
os.environ.setdefault('COINCAT_DATA_DIR', str(Path(os.environ.get('APPDATA') or Path.home())/'CoinCatV70'))

def ensure_private_data():
    from coincat_state_v50 import state_status, migrate, StateError, data_root
    try:
        state_status(data_root())
        return True
    except StateError:
        pass
    import tkinter as tk
    from tkinter import messagebox, filedialog
    ui=tk.Tk();ui.withdraw()
    try:
        title='CoinCat v70 — Verified Private Data Copy'
        old=Path(os.environ.get('APPDATA') or Path.home())/'CoinCatV60'
        msg=('CoinCat v70 uses a NEW separate private COPY at %APPDATA%\\CoinCatV70.\n\n'
             'The first launch COPY must be approved; originals are never overwritten. '
             'Close all older CoinCat processes before copying.\n\n'
             'NO REAL ORDERS can be submitted by this release.')
        if not messagebox.askokcancel(title,msg,parent=ui):return False
        source=None
        if old.is_dir():
            if messagebox.askyesno(title,'COPY your existing VERIFIED CoinCatV60 private data into NEW CoinCatV70?\nOriginal is preserved.',parent=ui):
                source=old
        if source is None:
            chosen=filedialog.askdirectory(parent=ui,title='Select COMPLETE verified CoinCatV60/private data backup')
            if not chosen:return False
            source=Path(chosen)
        try:
            migrate(source,data_root())
            state_status(data_root())
            messagebox.showinfo(title,'Verified, copy-only import completed. CoinCat v70 starts DISARMED. No live orders.',parent=ui)
            return True
        except (StateError,OSError,ValueError) as exc:
            messagebox.showerror(title,'PRIVATE DATA COPY BLOCKED: '+type(exc).__name__+
                                 '. Existing financial records were not changed.',parent=ui)
            return False
    finally:ui.destroy()

def main():
    if len(sys.argv)==2 and sys.argv[1]=='--verify-cuda-runtime':
        try:
            import torch
            if not torch.cuda.is_available():return 14
            return 0 if float(torch.ones(1,device='cuda').cpu()[0])==1.0 else 15
        except Exception:return 16
    if not ensure_private_data():return 2
    from coincat_app import main as run
    try:
        run();return 0
    except Exception:
        import tkinter as tk
        from tkinter import messagebox
        ui=tk.Tk();ui.withdraw()
        messagebox.showerror('CoinCat v70','Startup was blocked. Check redacted diagnostic logs; financial records remain protected.',parent=ui)
        ui.destroy();return 3

if __name__=='__main__':sys.exit(main())
