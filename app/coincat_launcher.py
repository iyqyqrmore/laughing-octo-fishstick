"""Self-contained CoinCat entrypoint. Only explicit import looks at old folders."""
from __future__ import annotations
import sys


def ensure_private_data():
    from coincat_data_transfer import verify_active, import_wizard
    from coincat_state_v50 import StateError, data_root
    try:
        verify_active()
        return True
    except (StateError,OSError,ValueError):
        # A damaged/partial destination is never overwritten or re-imported.
        root=data_root()
        if root.exists() and any(root.iterdir()):
            import tkinter as tk
            from tkinter import messagebox
            ui=tk.Tk();ui.withdraw()
            try:messagebox.showerror('Private data not verified',
                'Current private_data is incomplete or unverified. Preserve it and its backup. '
                'The importer will not merge or overwrite it.',parent=ui)
            finally:ui.destroy()
            return False
    return import_wizard()


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
        messagebox.showerror('CoinCat','Startup was blocked. Check redacted diagnostic logs; financial records remain protected.',parent=ui)
        ui.destroy();return 3

if __name__=='__main__':sys.exit(main())
