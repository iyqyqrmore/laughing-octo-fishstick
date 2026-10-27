"""Console-free CoinCat Windows GUI entrypoint; live order POST remains blocked."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))

def _notice(status):
    # Avoid writing secrets, key paths, raw Coinbase responses or tracebacks.
    try:
        root=Path(os.environ.get('APPDATA') or Path.home())/'CoinCatV70'
        if root.is_dir():
            logs=root/'logs';logs.mkdir(exist_ok=True)
            with (logs/'startup_status.log').open('a',encoding='utf-8') as out:
                out.write(datetime.now(timezone.utc).isoformat(timespec='seconds')+' '+status+'\n')
    except OSError:pass

def main():
    try:
        from coincat_v60_launcher import main as gui_main
        code=gui_main()
        if code not in (None,0):
            _notice('GUI_START_REFUSED; status='+str(code))
        return int(code or 0)
    except SystemExit as exc:
        _notice('GUI_START_BLOCKED; exit='+str(exc.code)[:8])
        return 2
    except BaseException as exc:
        _notice('GUI_START_ERROR; class='+type(exc).__name__)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk();root.withdraw()
            messagebox.showerror('CoinCat could not start',
                'Startup failed. Open the Debug Launcher for troubleshooting. '
                'Your Coinbase funds and original financial data were not changed.')
            root.destroy()
        except Exception:pass
        return 3

if __name__=='__main__':sys.exit(main())
