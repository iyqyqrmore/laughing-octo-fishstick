"""Retain real SQLite objects; assertions run before fixture-directory removal."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch


class TrialSQLiteProbe:
    def __init__(self):
        self.connections=[];self.cursors=[];self.native_checks=0
        self.fault=None;self.fetch_fault=None;self.commit_fault=None
    def before_sql(self,sql):
        if self.fault is not None:self.fault(sql)
    def assert_closed(self,case):
        case.assertTrue(self.connections,'No SQLite connection was exercised')
        case.assertTrue(all(db.closed for db in self.connections),'SQLite connections must close explicitly before temporary cleanup')
        case.assertTrue(all(cur.closed for cur in self.cursors),'SQLite cursors must close explicitly before temporary cleanup')
        for db in self.connections:
            with case.assertRaises(sqlite3.ProgrammingError):sqlite3.Connection.execute(db,'SELECT 1')
    def assert_released(self,case,path):
        self.assert_closed(case);path=Path(path)
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            create=kernel.CreateFileW;create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];create.restype=wintypes.HANDLE
            close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
            # OPEN_EXISTING, read/write, zero sharing: a remaining SQLite handle
            # fails here before any directory deletion. No retry or GC fallback.
            handle=create(str(path.resolve()),0xC0000000,0,None,3,0,None)
            if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            try:self.native_checks+=1
            finally:
                if not close(handle):raise ctypes.WinError(ctypes.get_last_error())
        moved=path.with_name(path.name+'.release-probe')
        path.rename(moved);moved.rename(path)


@contextmanager
def trial_sqlite_probe():
    original=sqlite3.connect;probe=TrialSQLiteProbe()
    class Cursor(sqlite3.Cursor):
        closed=False
        def execute(self,sql,*args,**kwargs):
            self.sql=sql;probe.before_sql(sql);return super().execute(sql,*args,**kwargs)
        def fetchone(self):
            if probe.fetch_fault is not None:probe.fetch_fault(self.sql)
            return super().fetchone()
        def fetchall(self):
            if probe.fetch_fault is not None:probe.fetch_fault(self.sql)
            return super().fetchall()
        def close(self):super().close();self.closed=True
    class Connection(sqlite3.Connection):
        closed=False
        def cursor(self,*args,**kwargs):
            value=super().cursor(factory=Cursor);probe.cursors.append(value);return value
        def execute(self,sql,*args,**kwargs):return self.cursor().execute(sql,*args,**kwargs)
        def __exit__(self,*exc):
            if probe.commit_fault is not None and self.in_transaction and exc[0] is None:probe.commit_fault()
            return super().__exit__(*exc)
        def close(self):super().close();self.closed=True
    def connect(*args,**kwargs):
        if 'factory' in kwargs or len(args)>5:raise AssertionError('Ordinary SQLite connection factory required by closure probe')
        value=original(*args,**kwargs,factory=Connection);probe.connections.append(value);return value
    with patch('sqlite3.connect',side_effect=connect):yield probe
    # Deliberately no cleanup that closes leaked handles. Tests must prove that
    # their own code released them while these strong references still exist.
