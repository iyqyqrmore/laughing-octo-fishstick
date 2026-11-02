"""One canonical public bid/ask journal. No strategies, training or wallets.

Existing research tables are left untouched. Only the existing market_quotes
schema is used; private financial databases are never opened here.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3

from coincat_cross_quote import split_spot
from coincat_storage import RESEARCH_LIMIT_MIB, research_sqlite_bytes


@dataclass(frozen=True)
class Retention:
    max_mb:int=RESEARCH_LIMIT_MIB


class ForwardStore:
    def __init__(self,path,retention=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.retention=retention or Retention()
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS market_quotes(pair TEXT NOT NULL,at_utc INTEGER NOT NULL,bid TEXT NOT NULL,ask TEXT NOT NULL,source TEXT NOT NULL DEFAULT \'coinbase\',PRIMARY KEY(pair,at_utc))')
            db.execute('CREATE INDEX IF NOT EXISTS idx_quotes_age ON market_quotes(at_utc)')

    @contextmanager
    def _db(self):
        db=sqlite3.connect(str(self.path),timeout=10)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:yield db
        finally:db.close()

    def record_quotes(self,rows,*,cancel=None):
        if cancel is not None and cancel.is_set():return 0
        if research_sqlite_bytes(self.path.parent)>self.retention.max_mb*1024*1024:
            return 0  # Pause recording at quota; do not delete an older dataset.
        clean=[]
        for pair,stamp,bid,ask,source in rows:
            try:
                split_spot(pair);bid=Decimal(str(bid));ask=Decimal(str(ask))
                if not bid.is_finite() or not ask.is_finite() or not 0<bid<=ask:continue
                if not isinstance(stamp,(int,float)) or stamp<=0:continue
                clean.append((pair,int(stamp),str(bid),str(ask),str(source)))
            except (ValueError,InvalidOperation,TypeError,OverflowError):continue
        with self._db() as db:
            if cancel is not None and cancel.is_set():return 0
            before=db.total_changes
            db.executemany('INSERT OR REPLACE INTO market_quotes VALUES(?,?,?,?,?)',clean)
            if cancel is not None and cancel.is_set():db.rollback();return 0
            return db.total_changes-before
