"""Isolated append-only assumed-order ledger, with explicit SQLite ownership."""
from contextlib import closing,contextmanager
from copy import deepcopy
import hashlib
import re
from pathlib import Path
import sqlite3
import threading

from coincat_beta_store import BetaBlocked,pack,unpack,digest
from coincat_assumed_math import CLASSIFICATION,FEE_MODEL,apply_record
from coincat_execution_limits import native_math
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from coincat_trial_clock import new_clock,validate_clock,COUNTERS as CLOCK_COUNTERS

APP_ID=0x43434146
FROZEN=('schema','classification','fee_model','sandbox_id','started_at','seed_at','seed_usd_per_coin','seed_marks','original','buy_price')
COUNTS=('waves','orders','buys','sells','maker_orders','taker_orders')

def query(db,sql,args=(),*,one=False):
    with closing(db.cursor()) as cursor:
        cursor.execute(sql,args)
        return cursor.fetchone() if one else cursor.fetchall() if cursor.description else None

@native_math
def validate(state):
    if state.get('schema')!=1 or state.get('classification')!=CLASSIFICATION or state.get('fee_model')!=FEE_MODEL:
        raise BetaBlocked('ASSUMED_CHECKPOINT_CLASSIFICATION_INVALID')
    if exact(state.get('seed_usd_per_coin'))!=100 or state.get('buy_price') not in ('ASK','BID') or set(state['pairs'])!=set(WATCH_PAIRS):raise BetaBlocked('ASSUMED_SEED_OR_MARKETS_CHANGED')
    if not isinstance(state.get('sandbox_id'),str) or not re.fullmatch('[0-9a-f]{32}',state['sandbox_id']):raise BetaBlocked('ASSUMED_IDENTITY_INVALID')
    for key in ('wallet','original','seed_marks','fees_native'):
        if set(state[key])!=set(WATCH_ASSETS) or any(exact(v)<0 for v in state[key].values()):raise BetaBlocked('ASSUMED_INVENTORY_INVALID')
    if any(type(state[k]) is not int or state[k]<0 for k in COUNTS):raise BetaBlocked('ASSUMED_COUNTER_INVALID')
    if state['orders']!=state['buys']+state['sells'] or state['orders']!=state['maker_orders']+state['taker_orders']:
        raise BetaBlocked('ASSUMED_COUNTER_CONFLICT')
    for asset in WATCH_ASSETS:
        mark=state['seed_marks'][asset]
        if mark<=0 or state['original'][asset]!=(exact(100)/mark).quantize(exact('1e-18'),rounding='ROUND_FLOOR'):
            raise BetaBlocked('ASSUMED_ORIGINAL_HUNDRED_USD_SEED_CHANGED')
    for value in state['pairs'].values():
        if value['next_side'] not in ('BUY','SELL'):raise BetaBlocked('ASSUMED_NEXT_DIRECTION_INVALID')
    sizing(state['sizing'])
    if type(state['settings_version']) is not int or state['settings_version']<1:raise BetaBlocked('ASSUMED_SIZING_VERSION_INVALID')

def sizing(values):
    if not isinstance(values,dict) or set(values)!=set(WATCH_PAIRS):raise BetaBlocked('ASSUMED_SIZE_SLIDERS_REQUIRE_SEVEN_MARKETS')
    result={p:exact(v) for p,v in values.items()}
    if any(not 0<=v<=100 for v in result.values()):raise BetaBlocked('NATIVE_SIZE_SLIDER_REQUIRES_ZERO_TO_100')
    return result

class AssumedStore:
    """No spending/turnover/attempt cap; cumulative observation clock is separate."""
    def __init__(self,path,*,initial=None):
        self.path=Path(path);self.lock=threading.RLock()
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):raise BetaBlocked('ASSUMED_JOURNAL_SYMLINK_REJECTED')
        if not self.path.exists():
            if initial is None:raise BetaBlocked('ASSUMED_CHECKPOINT_MISSING')
            validate(initial);self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.database(create=True) as db,db:
                query(db,'PRAGMA application_id='+str(APP_ID));query(db,'PRAGMA user_version=1')
                query(db,'CREATE TABLE assumed_state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                query(db,'CREATE TABLE assumed_seed(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,digest TEXT NOT NULL)')
                query(db,'CREATE TABLE assumed_orders(seq INTEGER PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,wave INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                query(db,'CREATE TABLE assumed_settings(version INTEGER PRIMARY KEY,after_order INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                query(db,'CREATE TABLE assumed_clock(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
                query(db,'CREATE TABLE assumed_final(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,digest TEXT NOT NULL)')
                raw=pack(initial);sha=hashlib.sha256(raw.encode()).hexdigest()
                query(db,'INSERT INTO assumed_state VALUES(1,0,?,?)',(raw,sha))
                query(db,'INSERT INTO assumed_seed VALUES(1,?,?)',(raw,sha))
                raw=pack(initial['sizing']);query(db,'INSERT INTO assumed_settings VALUES(1,0,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
                raw=pack(new_clock(initial['sandbox_id'],initial['started_at']))
                query(db,'INSERT INTO assumed_clock VALUES(1,0,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
        with self.database() as db:
            if query(db,'PRAGMA quick_check(1)',one=True)[0]!='ok':raise BetaBlocked('ASSUMED_INTEGRITY_REVIEW_REQUIRED')
            revision,raw,sha=self.checkpoint(db)
            seed=query(db,'SELECT payload,digest FROM assumed_seed WHERE id=1',one=True)
            if seed is None or hashlib.sha256(seed[0].encode()).hexdigest()!=seed[1]:raise BetaBlocked('ASSUMED_SEED_DIGEST_INVALID')
            state=unpack(raw);validate(state);original=unpack(seed[0]);validate(original)
            if revision!=state['waves']+state['settings_version']-1:raise BetaBlocked('ASSUMED_CHECKPOINT_REVISION_CONFLICT')
            if original['orders'] or any(state[k]!=original[k] for k in FROZEN):raise BetaBlocked('ASSUMED_FROZEN_SEED_CHANGED')
            self.audit(db,original,state)
            row=query(db,'SELECT revision,payload,digest FROM assumed_clock WHERE id=1',one=True)
            if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('ASSUMED_CLOCK_DIGEST_INVALID')
            self.clock=unpack(row[1]);self.clock_revision=row[0];validate_clock(self.clock)
            if self.clock['trial_id']!=state['sandbox_id'] or self.clock['started_at']!=state['started_at']:raise BetaBlocked('ASSUMED_CLOCK_IDENTITY_CONFLICT')
            final=query(db,'SELECT payload,digest FROM assumed_final WHERE id=1',one=True);self.completion=None
            if final is not None:
                if hashlib.sha256(final[0].encode()).hexdigest()!=final[1] or self.clock['phase']!='COMPLETE':raise BetaBlocked('ASSUMED_COMPLETION_DIGEST_INVALID')
                self.completion=unpack(final[0])
                if digest(self.completion['simulation'])!=digest(state):raise BetaBlocked('ASSUMED_COMPLETION_STATE_CONFLICT')
        self._state=state;self.revision=revision

    @contextmanager
    def database(self,*,create=False):
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):raise BetaBlocked('ASSUMED_JOURNAL_SYMLINK_REJECTED')
        target=self.path if create else self.path.resolve().as_uri()+'?mode=rw'
        with closing(sqlite3.connect(target,uri=not create,timeout=1)) as db:
            if not create and (query(db,'PRAGMA application_id',one=True)[0]!=APP_ID or query(db,'PRAGMA user_version',one=True)[0]!=1):
                raise BetaBlocked('WRONG_ASSUMED_DATABASE_OR_VERSION')
            yield db

    def checkpoint(self,db):
        row=query(db,'SELECT revision,payload,digest FROM assumed_state WHERE id=1',one=True)
        if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('ASSUMED_CHECKPOINT_DIGEST_INVALID')
        return row

    @native_math
    def audit(self,db,seed,state):
        """Replay all synthetic native flows before accepting a saved checkpoint."""
        replay=deepcopy(seed);wave=0
        settings=iter(query(db,'SELECT version,after_order,payload,digest FROM assumed_settings ORDER BY version'))
        pending=next(settings,None);version=0
        def advance_settings():
            nonlocal pending,version
            while pending is not None and pending[1]<=replay['orders']:
                v,after,raw,sha=pending
                if v!=version+1 or after!=replay['orders'] or hashlib.sha256(raw.encode()).hexdigest()!=sha:raise BetaBlocked('ASSUMED_SIZING_HISTORY_INVALID')
                values=sizing(unpack(raw))
                if v==1 and values!=seed['sizing']:raise BetaBlocked('ASSUMED_INITIAL_SIZING_CHANGED')
                replay.update(sizing=values,settings_version=v);version=v;pending=next(settings,None)
        with closing(db.cursor()) as cursor:
            cursor.execute('SELECT seq,order_id,wave,payload,digest FROM assumed_orders ORDER BY seq')
            for seq,oid,n,raw,sha in cursor:
                advance_settings()
                if seq!=replay['orders']+1 or hashlib.sha256(raw.encode()).hexdigest()!=sha:
                    raise BetaBlocked('ASSUMED_ORDER_HISTORY_INVALID')
                record=unpack(raw)
                if record['order_id']!=oid or record['wave']!=n or n not in (wave,wave+1) or n<=0:
                    raise BetaBlocked('ASSUMED_ORDER_HISTORY_SEQUENCE_CONFLICT')
                if n!=wave:
                    if replay['last_at'] is not None and record['at']<=replay['last_at']:raise BetaBlocked('ASSUMED_OBSERVATION_TIME_CONFLICT')
                    wave=n;replay['waves']+=1;replay['last_at']=record['at']
                elif record['at']!=replay['last_at']:raise BetaBlocked('ASSUMED_WAVE_TIME_CONFLICT')
                apply_record(replay,record)
        advance_settings()
        if pending is not None or version!=state['settings_version']:raise BetaBlocked('ASSUMED_SIZING_HISTORY_CONFLICT')
        if digest(replay)!=digest(state):raise BetaBlocked('ASSUMED_CHECKPOINT_LEDGER_CONFLICT')

    def state(self):
        with self.lock:return deepcopy(self._state)

    @native_math
    def append(self,records,*,at):
        if not records:return self.state()
        with self.lock:
            before=self._state
            if self.clock['phase']=='COMPLETE':raise BetaBlocked('COMPLETED_ASSUMED_TRIAL_FROZEN')
            if before['last_at'] is not None and at<=before['last_at']:raise BetaBlocked('ASSUMED_OBSERVATION_ALREADY_CONSUMED')
            state=deepcopy(before);state['waves']+=1;state['last_at']=at
            for record in records:
                if record['wave']!=state['waves'] or record['at']!=at:raise BetaBlocked('ASSUMED_WAVE_CONFLICT')
                apply_record(state,record)
            validate(state)
            if any(state[k]!=before[k] for k in FROZEN):raise BetaBlocked('ASSUMED_FROZEN_SEED_CHANGED')
            with self.database() as db,db:
                query(db,'BEGIN IMMEDIATE');revision,raw,sha=self.checkpoint(db)
                if revision!=self.revision or digest(unpack(raw))!=digest(before):raise BetaBlocked('STALE_ASSUMED_WRITER')
                for i,record in enumerate(records,1):
                    raw=pack(record)
                    query(db,'INSERT INTO assumed_orders VALUES(?,?,?,?,?)',
                        (before['orders']+i,record['order_id'],state['waves'],raw,hashlib.sha256(raw.encode()).hexdigest()))
                raw=pack(state)
                query(db,'UPDATE assumed_state SET revision=?,payload=?,digest=? WHERE id=1',
                    (revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
                self._clock_write(db)
            self._state=state;self.revision+=1;self.clock_revision+=1;return deepcopy(state)

    def configure(self,values):
        values=sizing(values)
        with self.lock:
            if self.clock['phase']=='COMPLETE':raise BetaBlocked('COMPLETED_ASSUMED_TRIAL_FROZEN')
            before=self._state
            if before['sizing']==values:return
            state=deepcopy(before);state.update(sizing=values,settings_version=before['settings_version']+1);validate(state)
            with self.database() as db,db:
                query(db,'BEGIN IMMEDIATE');revision,raw,sha=self.checkpoint(db)
                if revision!=self.revision or digest(unpack(raw))!=digest(before):raise BetaBlocked('STALE_ASSUMED_WRITER')
                raw=pack(values)
                query(db,'INSERT INTO assumed_settings VALUES(?,?,?,?)',(state['settings_version'],before['orders'],raw,hashlib.sha256(raw.encode()).hexdigest()))
                raw=pack(state);query(db,'UPDATE assumed_state SET revision=?,payload=?,digest=? WHERE id=1',(revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
                self._clock_write(db)
            self._state=state;self.revision+=1;self.clock_revision+=1

    def _clock_write(self,db):
        validate_clock(self.clock)
        row=query(db,'SELECT revision,payload,digest FROM assumed_clock WHERE id=1',one=True)
        if row is None or row[0]!=self.clock_revision or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:raise BetaBlocked('ASSUMED_CLOCK_CHECKPOINT_CHANGED')
        prior=unpack(row[1])
        if (any(self.clock[k]!=prior[k] for k in ('trial_id','started_at','target_ns')) or
                any(self.clock[k]<prior[k] for k in CLOCK_COUNTERS) or
                prior['phase']=='COMPLETE' and self.clock['phase']!='COMPLETE'):
            raise BetaBlocked('ASSUMED_CLOCK_ORIGINAL_COUNTERS_CHANGED')
        raw=pack(self.clock);query(db,'UPDATE assumed_clock SET revision=?,payload=?,digest=? WHERE id=1',(self.clock_revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))

    def flush_clock(self):
        with self.lock:
            with self.database() as db,db:
                query(db,'BEGIN IMMEDIATE');revision,raw,sha=self.checkpoint(db)
                if revision!=self.revision or digest(unpack(raw))!=digest(self._state):raise BetaBlocked('ASSUMED_MODEL_CHECKPOINT_CHANGED')
                self._clock_write(db)
            self.clock_revision+=1

    def finish(self,report):
        with self.lock:
            if self.completion is not None:return
            if self.clock['phase']!='COMPLETE':raise BetaBlocked('ASSUMED_TRIAL_NOT_COMPLETE')
            with self.database() as db,db:
                query(db,'BEGIN IMMEDIATE');revision,raw,sha=self.checkpoint(db)
                if revision!=self.revision or digest(unpack(raw))!=digest(self._state):raise BetaBlocked('ASSUMED_MODEL_CHECKPOINT_CHANGED')
                if query(db,'SELECT 1 FROM assumed_final WHERE id=1',one=True) is not None:raise BetaBlocked('ASSUMED_FINAL_ALREADY_WRITTEN')
                raw=pack(report);query(db,'INSERT INTO assumed_final VALUES(1,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
                self._clock_write(db)
            self.clock_revision+=1;self.completion=deepcopy(report)

    def recent(self,limit=64):
        if type(limit) is not int or not 1<=limit<=256:raise BetaBlocked('ASSUMED_HISTORY_VIEW_BOUND')
        with self.database() as db:
            rows=query(db,'SELECT payload,digest FROM assumed_orders ORDER BY seq DESC LIMIT ?',(limit,))
        result=[]
        for raw,sha in reversed(rows):
            if hashlib.sha256(raw.encode()).hexdigest()!=sha:raise BetaBlocked('ASSUMED_ORDER_HISTORY_INVALID')
            result.append(unpack(raw))
        return result
