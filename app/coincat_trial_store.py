"""Versioned trial/model/clock transactions in one isolated SQLite database.

Clock checkpoints update one bounded row, not an unbounded per-second event log.
Market/replay decisions retain their append-only evidence. No financial tables.
"""
from contextlib import closing
from copy import deepcopy
from decimal import localcontext
import hashlib
from pathlib import Path
import sqlite3
import threading

from coincat_beta_store import BetaBlocked,pack,unpack,digest
from coincat_trial_clock import new_clock,validate_clock,COUNTERS

APP_ID=0x43435434
MAX_BYTES=1024*1024*1024

class TrialStore:
    def __init__(self,path,*,initial=None,validate):
        self.path=Path(path);self.validate=validate;self.lock=threading.RLock()
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('TRIAL_SYMLINK_REJECTED')
        if self.path.exists() and self.path.stat().st_size>MAX_BYTES:raise BetaBlocked('TRIAL_STORAGE_REVIEW_REQUIRED')
        if not self.path.exists():
            if initial is None:raise BetaBlocked('TRIAL_STORE_MISSING')
            validate(initial);clock=new_clock(initial['trial_id'],initial['started_at']);self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path,timeout=1)) as db,db:
                db.execute('PRAGMA application_id='+str(APP_ID));db.execute('PRAGMA user_version=104')
                db.execute('CREATE TABLE trial_state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                db.execute('CREATE TABLE trial_clock(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                db.execute('CREATE TABLE trial_events(id TEXT PRIMARY KEY,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL)')
                for table,value in (('trial_state',initial),('trial_clock',clock)):
                    raw=pack(value);db.execute('INSERT INTO '+table+' VALUES(1,0,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
        with closing(self._db()) as db:
            if db.execute('PRAGMA quick_check(1)').fetchone()[0]!='ok':raise BetaBlocked('TRIAL_INTEGRITY_REVIEW_REQUIRED')
            model=db.execute('SELECT revision,payload,digest FROM trial_state WHERE id=1').fetchone()
            clock=db.execute('SELECT revision,payload,digest FROM trial_clock WHERE id=1').fetchone()
        def checked(row):
            if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('TRIAL_CHECKPOINT_DIGEST_INVALID')
            return unpack(row[1])
        self._state=checked(model);self.clock=checked(clock);validate(self._state);validate_clock(self.clock)
        if self.clock['trial_id']!=self._state['trial_id'] or self.clock['started_at']!=self._state['started_at']:
            raise BetaBlocked('TRIAL_MODEL_CLOCK_IDENTITY_CONFLICT')
        self.revision=model[0];self.clock_revision=clock[0]
    def _db(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('TRIAL_SYMLINK_REJECTED')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=1)
        try:
            if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or db.execute('PRAGMA user_version').fetchone()[0]!=104:
                raise BetaBlocked('WRONG_TRIAL_DATABASE_OR_VERSION')
        except BaseException:db.close();raise
        return db
    def state(self):
        with self.lock:return deepcopy(self._state)
    def _clock_write(self,db):
        validate_clock(self.clock)
        model=db.execute('SELECT revision,payload,digest FROM trial_state WHERE id=1').fetchone()
        if model is None or hashlib.sha256(model[1].encode()).hexdigest()!=model[2]:raise BetaBlocked('TRIAL_MODEL_CHECKPOINT_CHANGED')
        row=db.execute('SELECT revision,payload,digest FROM trial_clock WHERE id=1').fetchone()
        if row is None or row[0]!=self.clock_revision:raise BetaBlocked('CONCURRENT_TRIAL_CLOCK_WRITER')
        if hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('TRIAL_CLOCK_CHECKPOINT_CHANGED')
        prior=unpack(row[1])
        if (any(self.clock[k]!=prior[k] for k in ('trial_id','started_at','target_ns')) or
                any(self.clock[k]<prior[k] for k in COUNTERS)):raise BetaBlocked('TRIAL_COUNTERS_OR_IDENTITY_CANNOT_RESET')
        raw=pack(self.clock);db.execute('UPDATE trial_clock SET revision=?,payload=?,digest=? WHERE id=1',
            (self.clock_revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
    def flush_clock(self):
        with self.lock:
            with closing(self._db()) as db,db:
                db.execute('BEGIN IMMEDIATE');self._clock_write(db)
            self.clock_revision+=1
    def change(self,kind,event_id,payload,action):
        if not isinstance(event_id,str) or not 1<=len(event_id)<=128:raise BetaBlocked('TRIAL_EVENT_ID_INVALID')
        fingerprint=digest(dict(kind=kind,payload=payload))
        with self.lock:
            with closing(self._db()) as db,db:
                db.execute('BEGIN IMMEDIATE')
                checkpoint=db.execute('SELECT revision,payload,digest FROM trial_state WHERE id=1').fetchone()
                if checkpoint is None or checkpoint[0]!=self.revision:raise BetaBlocked('STALE_TRIAL_INSTANCE')
                if hashlib.sha256(checkpoint[1].encode()).hexdigest()!=checkpoint[2]:raise BetaBlocked('TRIAL_MODEL_CHECKPOINT_CHANGED')
                prior=db.execute('SELECT fingerprint FROM trial_events WHERE id=?',(event_id,)).fetchone()
                if prior:
                    if prior[0]!=fingerprint:raise BetaBlocked('CONFLICTING_TRIAL_EVENT')
                    return {'state':'DUPLICATE_IGNORED'}
                if self.path.stat().st_size>MAX_BYTES or db.execute('SELECT COUNT(*) FROM trial_events').fetchone()[0]>=1000000:
                    raise BetaBlocked('TRIAL_STORAGE_REVIEW_REQUIRED')
                state=deepcopy(self._state)
                with localcontext() as context:
                    context.prec=80;result=action(state);self.validate(state);raw=pack(state)
                if any(state[k]!=self._state[k] for k in ('trial_id','started_at','strategy','config','config_digest','expires_at','original','portfolio')):
                    raise BetaBlocked('ORIGINAL_TRIAL_BASELINE_OR_LIMITS_CHANGED')
                db.execute('UPDATE trial_state SET revision=?,payload=?,digest=? WHERE id=1',
                    (self.revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
                db.execute('INSERT INTO trial_events VALUES(?,?,?,?)',(event_id,kind,fingerprint,pack(payload)))
                self._clock_write(db)
            self._state=state;self.revision+=1;self.clock_revision+=1
        return result
    def events(self,limit=64):
        if type(limit) is not int or not 1<=limit<=256:raise BetaBlocked('TRIAL_EVENT_VIEW_BOUND')
        with closing(self._db()) as db:
            rows=db.execute('SELECT kind,payload FROM trial_events ORDER BY rowid DESC LIMIT ?',(limit,)).fetchall()
        return [dict(kind=k,payload=unpack(p)) for k,p in reversed(rows)]
