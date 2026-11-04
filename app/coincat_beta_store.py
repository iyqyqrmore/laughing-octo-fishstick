"""Bounded isolated beta journals. No financial, paper, key or network adapter."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from decimal import localcontext

from coincat_research_journal import _encode, _decode

MAX_BYTES=32*1024*1024
MAX_PAYLOAD=1048576
MAX_EVENTS=8192


class BetaBlocked(ValueError):
    pass


def _ordered(value):
    if isinstance(value,dict):
        if any(type(k) is not str for k in value):raise BetaBlocked('INVALID_BETA_MAPPING')
        return {k:_ordered(value[k]) for k in sorted(value)}
    if isinstance(value,list):return [_ordered(v) for v in value]
    if isinstance(value,tuple):return tuple(_ordered(v) for v in value)
    return value


def pack(value):
    raw=json.dumps(_encode(_ordered(value)),separators=(',',':'),allow_nan=False)
    if len(raw.encode())>MAX_PAYLOAD:raise BetaBlocked('BETA_PAYLOAD_LIMIT')
    return raw


def unpack(raw):
    if len(raw.encode())>MAX_PAYLOAD:raise BetaBlocked('BETA_PAYLOAD_LIMIT')
    def reject(value):raise BetaBlocked('INVALID_BETA_NUMBER')
    try:return _decode(json.loads(raw,parse_constant=reject))
    except (ValueError,TypeError,KeyError,ArithmeticError,RecursionError):
        raise BetaBlocked('INVALID_BETA_RECORD') from None


def digest(value):return hashlib.sha256(pack(value).encode()).hexdigest()


class BetaStore:
    """Append-only events plus a transactionally versioned private cache."""
    def __init__(self,path,application_id,*,initial=None,validate=lambda s:None):
        self.path=Path(path);self.application_id=application_id;self.validate=validate
        self.lock=threading.RLock()
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('BETA_SYMLINK_REJECTED')
        if self.path.exists() and self.path.stat().st_size>MAX_BYTES:raise BetaBlocked('BETA_STORAGE_LIMIT')
        if not self.path.exists():
            if initial is None:raise BetaBlocked('BETA_STORE_MISSING')
            validate(initial);self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path,timeout=1)) as db,db:
                db.execute('PRAGMA application_id='+str(application_id))
                db.execute('CREATE TABLE beta_state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                db.execute('CREATE TABLE beta_events(id TEXT PRIMARY KEY,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL)')
                raw=pack(initial)
                db.execute('INSERT INTO beta_state VALUES(1,0,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
        with closing(self._db()) as db:
            if db.execute('PRAGMA quick_check(1)').fetchone()[0]!='ok':raise BetaBlocked('BETA_INTEGRITY_FAILED')
            row=db.execute('SELECT revision,payload,digest FROM beta_state WHERE id=1').fetchone()
        if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('BETA_DIGEST_FAILED')
        self._state=unpack(row[1]);self.revision=row[0];validate(self._state)

    def _db(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('BETA_SYMLINK_REJECTED')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=1)
        try:
            if db.execute('PRAGMA application_id').fetchone()[0]!=self.application_id:
                raise BetaBlocked('WRONG_BETA_DATABASE')
        except BaseException:
            db.close();raise
        return db

    def state(self):
        with self.lock:return deepcopy(self._state)

    def change(self,kind,event_id,payload,action):
        if not isinstance(event_id,str) or not 1<=len(event_id)<=128:raise BetaBlocked('INVALID_BETA_EVENT_ID')
        fingerprint=digest(dict(kind=kind,payload=payload))
        with self.lock:
            with closing(self._db()) as db,db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT revision FROM beta_state WHERE id=1').fetchone()[0]!=self.revision:
                    raise BetaBlocked('STALE_BETA_INSTANCE_RELOAD_REQUIRED')
                prior=db.execute('SELECT fingerprint FROM beta_events WHERE id=?',(event_id,)).fetchone()
                if prior:
                    if prior[0]!=fingerprint:raise BetaBlocked('CONFLICTING_BETA_EVENT')
                    return {'state':'DUPLICATE_IGNORED'}
                if (self.path.stat().st_size>=MAX_BYTES or
                        db.execute('SELECT COUNT(*) FROM beta_events').fetchone()[0]>=MAX_EVENTS):
                    raise BetaBlocked('BETA_HISTORY_OR_STORAGE_LIMIT')
                state=deepcopy(self._state)
                with localcontext() as context:
                    context.prec=80
                    result=action(state);self.validate(state);raw=pack(state)
                db.execute('UPDATE beta_state SET revision=?,payload=?,digest=? WHERE id=1',
                    (self.revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
                db.execute('INSERT INTO beta_events VALUES(?,?,?,?)',(event_id,kind,fingerprint,pack(payload)))
            self._state=state;self.revision+=1
        return result

    def events(self,*,limit=64):
        if type(limit) is not int or not 1<=limit<=256:raise BetaBlocked('INVALID_BETA_HISTORY_LIMIT')
        with closing(self._db()) as db:
            rows=db.execute('SELECT kind,payload FROM beta_events ORDER BY rowid DESC LIMIT ?',(limit,)).fetchall()
        return [dict(kind=k,payload=unpack(v)) for k,v in reversed(rows)]
