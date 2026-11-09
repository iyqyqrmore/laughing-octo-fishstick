"""Bounded GET-only hourly reference cache. It never supplies an order product.

The five USD products are valuation/forecast references only; executable markets
remain the seven approved native pairs. No account, fill or tax data is stored.
"""
from contextlib import closing,contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib
import math
import sqlite3
import threading

from coincat_beta_store import BetaBlocked,pack,unpack,digest
from coincat_forecast_24h import ForecastConfig,HOUR,forecast
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS

REFERENCES=tuple(a+'-USD' for a in WATCH_ASSETS)
APP_ID=0x43434635
MAX_BYTES=128*1024*1024

def candle_rows(raw,pair,received_at,start,end):
    if pair not in REFERENCES or not isinstance(raw,dict) or not isinstance(raw.get('candles'),list) or len(raw['candles'])>350:
        raise BetaBlocked('FORECAST_CANDLE_RESPONSE_INVALID')
    rows=[];seen=set()
    for item in raw['candles']:
        if not isinstance(item,dict):raise BetaBlocked('FORECAST_CANDLE_INVALID')
        try:
            t=int(item['start'])
            if t==end and t+HOUR>received_at:continue # venue may include the still-open endpoint candle.
            if str(t)!=str(item['start']) or t%HOUR or not start<=t<end or t+HOUR>received_at:raise ValueError()
            o,h,l,c,v=(exact(item[k]) for k in ('open','high','low','close','volume'))
            if not 0<l<=min(o,c)<=max(o,c)<=h or v<0 or t in seen:raise ValueError()
        except (ValueError,TypeError,KeyError,ArithmeticError):raise BetaBlocked('FORECAST_CANDLE_INVALID_OR_NOT_CLOSED') from None
        seen.add(t);rows.append(dict(pair=pair,at=t+HOUR,open=o,high=h,low=l,close=c,volume=v))
    return sorted(rows,key=lambda r:r['at'])

class ForecastHistory:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.revision=0;self.broken=False
        self.cache=None;self.cache_key=None;self.reason='FORECAST_HISTORY_INSUFFICIENT';self.last_status={}
        if self.path.exists():
            try:
                with self.db() as db,closing(db.cursor()) as cur:
                    cur.execute('PRAGMA quick_check(1)')
                    if cur.fetchone()[0]!='ok':raise BetaBlocked('FORECAST_HISTORY_INTEGRITY')
                    cur.execute('SELECT COUNT(*) FROM hourly');cur.fetchone()
            except (OSError,sqlite3.Error,ValueError):self.broken=True;self.reason='FORECAST_HISTORY_STORAGE_REVIEW_REQUIRED'
    @contextmanager
    def db(self,*,create=False):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('FORECAST_HISTORY_PATH_REJECTED')
        if self.path.exists() and self.path.stat().st_size>MAX_BYTES:raise BetaBlocked('FORECAST_HISTORY_STORAGE_LIMIT')
        if create:self.path.parent.mkdir(parents=True,exist_ok=True)
        target=self.path if create else self.path.resolve().as_uri()+'?mode=rw'
        with closing(sqlite3.connect(target,uri=not create,timeout=1)) as db:
            if not create:
                with closing(db.cursor()) as cur:
                    cur.execute('PRAGMA application_id')
                    if cur.fetchone()[0]!=APP_ID:raise BetaBlocked('FORECAST_HISTORY_DATABASE_MISMATCH')
                    cur.execute('PRAGMA user_version')
                    if cur.fetchone()[0]!=1:raise BetaBlocked('FORECAST_HISTORY_DATABASE_MISMATCH')
            yield db
    def initialize(self):
        if self.broken:raise BetaBlocked(self.reason)
        if self.path.exists():return
        with self.db(create=True) as db,db,closing(db.cursor()) as cur:
            cur.execute('PRAGMA application_id='+str(APP_ID));cur.execute('PRAGMA user_version=1')
            cur.execute('CREATE TABLE hourly(pair TEXT NOT NULL,at INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(pair,at))')
            cur.execute('CREATE TABLE batches(id INTEGER PRIMARY KEY,pair TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,received REAL NOT NULL,count INTEGER NOT NULL)')
    def append(self,pair,start,end,received_at,rows):
        if pair not in REFERENCES or not all(row.get('pair')==pair for row in rows):raise BetaBlocked('FORECAST_REFERENCE_SCOPE_INVALID')
        with self.lock:
            self.initialize()
            with self.db() as db,db,closing(db.cursor()) as cur:
                cur.execute('BEGIN IMMEDIATE')
                for row in rows:
                    raw=pack(row);fingerprint=hashlib.sha256(raw.encode()).hexdigest()
                    cur.execute('SELECT payload,digest FROM hourly WHERE pair=? AND at=?',(pair,row['at']));old=cur.fetchone()
                    if old is not None:
                        if hashlib.sha256(old[0].encode()).hexdigest()!=old[1]:raise BetaBlocked('FORECAST_HISTORY_DIGEST_CONFLICT')
                        prior=unpack(old[0])
                        if any(prior[k]!=row[k] for k in ('open','high','low','close')):raise BetaBlocked('FORECAST_FINAL_CANDLE_CORRECTION_REVIEW_REQUIRED')
                        continue # volume-only revisions do not alter the price model.
                    cur.execute('INSERT INTO hourly VALUES(?,?,?,?)',(pair,row['at'],raw,fingerprint))
                cur.execute('INSERT INTO batches(pair,start,end,received,count) VALUES(?,?,?,?,?)',(pair,start,end,received_at,len(rows)))
            self.revision+=1;self.cache_key=None
    def intervals(self,pair):
        if not self.path.exists():return []
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT start,end FROM batches WHERE pair=? ORDER BY start',(pair,));return cur.fetchall()
    def panel(self,now,config=None):
        config=(config or ForecastConfig()).checked();end=int(now)//HOUR*HOUR;start=end-(config.history_hours-1)*HOUR
        if self.broken:raise BetaBlocked(self.reason)
        if not self.path.exists():return []
        columns={p:{} for p in REFERENCES}
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT pair,at,payload,digest FROM hourly WHERE at>=? AND at<=? ORDER BY at',(start,end))
            for pair,at,raw,sha in cur:
                if pair not in columns or hashlib.sha256(raw.encode()).hexdigest()!=sha:raise BetaBlocked('FORECAST_HISTORY_DIGEST_CONFLICT')
                row=unpack(raw)
                if row.get('pair')!=pair or row.get('at')!=at or exact(row['close'])<=0:raise BetaBlocked('FORECAST_HISTORY_IDENTITY_CONFLICT')
                columns[pair][at]=row['close']
        times=set.intersection(*(set(v) for v in columns.values()))
        self.last_status=dict(reference_count=sum(bool(v) for v in columns.values()),aligned_observations=len(times),required=config.history_hours,
            latest_at=max(times) if times else None)
        return [dict(at=t,marks={a:columns[a+'-USD'][t] for a in WATCH_ASSETS}) for t in sorted(times)]
    def estimate(self,now,config=None):
        config=config or ForecastConfig();key=(self.revision,int(now)//HOUR,pack(config.__dict__))
        try:
            if self.cache_key!=key:
                rows=self.panel(now,config);self.cache=forecast(rows,now,config);self.cache_key=key
            result=deepcopy(self.cache);result.update(decision_at=now,forecast_end_at=now+24*HOUR)
            self.reason='FORECAST_READY_UNVALIDATED';return result
        except (ValueError,KeyError,TypeError,ArithmeticError,sqlite3.Error,OSError) as exc:
            self.reason=str(exc) if isinstance(exc,BetaBlocked) else 'FORECAST_HISTORY_UNAVAILABLE'
            return dict(state='HOLD',reason=self.reason,horizon_s=24*HOUR,decision_at=now,
                forecast_validation='UNVALIDATED_RESEARCH_ESTIMATE',history=deepcopy(self.last_status))

class ForecastHistorySource:
    def __init__(self,reader,store):self.reader=reader;self.store=store;self.retry_at=0;self.last_reason='FORECAST_HISTORY_INSUFFICIENT'
    def next_request(self,now,config=None):
        config=config or ForecastConfig();end=int(now)//HOUR*HOUR;first=end-config.history_hours*HOUR
        for pair in REFERENCES:
            merged=[]
            for a,b in self.store.intervals(pair):
                if merged and a<=merged[-1][1]:merged[-1][1]=max(b,merged[-1][1])
                else:merged.append([a,b])
            hi=end
            for a,b in reversed(merged):
                if b<hi:return pair,max(first,b-HOUR,hi-349*HOUR),hi
                if a<hi:hi=a
                if hi<=first:break
            if hi>first:return pair,max(first,hi-349*HOUR),hi
        return None
    def collect(self,config=None):
        r=self.reader;now=r.clock()
        if now<self.retry_at:return dict(state='BACKOFF',reason=self.last_reason)
        try:
            request=self.next_request(now,config)
            if request is None:return dict(state='READY')
            pair,start,end=request;r.begin();r.deadline=min(r.deadline,r.started+6)
            r.scope()
            raw=r.call('get_candles',product_id=pair,start=str(start),end=str(end),granularity='ONE_HOUR',limit=350)
            received=r.clock();rows=candle_rows(raw,pair,received,start,end)
            self.store.append(pair,start,end,received,rows);self.last_reason='FORECAST_HISTORY_COLLECTING'
            return dict(state='COLLECTING',pair=pair,count=len(rows))
        except (ValueError,TypeError,KeyError,ArithmeticError,OSError,sqlite3.Error) as exc:
            self.last_reason=str(exc) if isinstance(exc,BetaBlocked) else 'FORECAST_HISTORY_READ_UNAVAILABLE'
            self.retry_at=now+60;return dict(state='HOLD',reason=self.last_reason)
