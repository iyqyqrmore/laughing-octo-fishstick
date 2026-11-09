"""Explicit read-only historical trial viewer; no controller initialization."""
from contextlib import closing
from pathlib import Path
import hashlib
import sqlite3
import tkinter as tk
from tkinter import ttk
from coincat_beta_store import unpack,pack,BetaBlocked
from coincat_version import DISPLAY

NAMES={'resumable_trial':'Original portfolio research','assumed_fill_sandbox':'Native assumed-fill arithmetic','opportunity_shadow':'v1.04 opportunity policy'}

def read_archive(data,name):
    if name not in NAMES:raise BetaBlocked('ARCHIVE_SCOPE_INVALID')
    path=Path(data)/'research_data'/name/'active.sqlite3'
    if not path.exists():return None
    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size>1024**3:raise BetaBlocked('ARCHIVE_PATH_REVIEW_REQUIRED')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db,closing(db.cursor()) as cur:
        result={}
        for table in ('trial_state','trial_clock'):
            cur.execute('SELECT payload,digest FROM '+table+' WHERE id=1');row=cur.fetchone()
            if row is None or hashlib.sha256(row[0].encode()).hexdigest()!=row[1]:raise BetaBlocked('ARCHIVE_INTEGRITY_REVIEW_REQUIRED')
            result[table]=unpack(row[0])
    return result

class ArchiveWindow:
    def __init__(self,app):
        self.root=tk.Toplevel(app.root);self.root.title(DISPLAY+' · Historical v1.04 records · Read only');self.root.geometry('1000x700')
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=DISPLAY+' · Historical trial archive',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='Read only. Opening this viewer never resumes a v1.04 controller, changes its clock, migrates data or resets its benchmark. Details stay private.',wraplength=940).pack(anchor='w',pady=8)
        self.body=tk.Text(shell,wrap='word',background='#10151b',foreground='#e3e8ee');self.body.pack(fill='both',expand=True)
        for name,label in NAMES.items():
            self.body.insert('end',label+'\n')
            try:
                value=read_archive(app.data,name)
                self.body.insert('end','No saved record.\n\n' if value is None else pack(value)+'\n\n')
            except (OSError,ValueError,sqlite3.Error):self.body.insert('end','Record needs review. Original preserved; no reset attempted.\n\n')
        self.body.configure(state='disabled')
