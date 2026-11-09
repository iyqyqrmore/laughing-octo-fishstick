"""Fair, bounded reference backfill with explicit progress and isolated retries."""
from contextlib import closing
from copy import deepcopy
import sqlite3,time
from coincat_beta_store import BetaBlocked
from coincat_candle_cache import REFERENCES,closed_candles
from coincat_forecast_history import candle_rows

SPECS={'ONE_MINUTE':(60,4320),'FIVE_MINUTE':(300,2880),'ONE_HOUR':(3600,2400)}
REASONS={'IDLE','COLLECTING','UP_TO_DATE','EMPTY_RESPONSE','SPARSE_HISTORY','READ_UNAVAILABLE','INVALID_CANDLES','CLOSED_PRICE_CORRECTION','STORAGE_REVIEW'}

def gap(intervals,end,required,seconds):
    first=end-required*seconds;merged=[]
    for a,b in intervals:
        if merged and a<=merged[-1][1]:merged[-1][1]=max(b,merged[-1][1])
        else:merged.append([a,b])
    hi=end
    for a,b in reversed(merged):
        if b<hi:return max(first,b-seconds,hi-349*seconds),hi
        if a<hi:hi=a
        if hi<=first:break
    return None if hi<=first else (max(first,hi-349*seconds),hi)

def reason(exc):
    if not isinstance(exc,BetaBlocked):return 'STORAGE_REVIEW' if isinstance(exc,(OSError,sqlite3.Error)) else 'READ_UNAVAILABLE'
    code=str(exc)
    if 'CORRECTION' in code:return 'CLOSED_PRICE_CORRECTION'
    if any(s in code for s in ('CACHE','DIGEST','DATABASE','STORAGE','INTEGRITY','PATH')):return 'STORAGE_REVIEW'
    if 'CANDLE' in code or 'RESPONSE' in code:return 'INVALID_CANDLES'
    return 'READ_UNAVAILABLE'

class HistoryBackfill:
    def __init__(self,reader,hourly,minute,*,monotonic=time.monotonic):
        self.reader=reader;self.hourly=hourly;self.minute=minute;self.monotonic=monotonic;self.global_review=False
        self.cursor=0;self.anchor={};self.turns={};self.retry={};self.review=set();self.last_dispatch=monotonic();self.last_success=None
        self.last_reason='IDLE';self.last_product=None;self.last_granularity=None;self.attempts=0;self.failures=0;self.last_state='IDLE';self.include_short=False
        self.public_cache=None;self.public_due=0
    def overdue(self):return self.monotonic()-self.last_dispatch>=30
    def intervals(self,g,p):return self.hourly.intervals(p) if g=='ONE_HOUR' else self.minute.intervals(g,p)
    def next_request(self,now,include_short=False):
        groups=tuple((g,p) for g in (SPECS if include_short else ('ONE_HOUR',)) for p in REFERENCES)
        for offset in range(len(groups)):
            idx=(self.cursor+offset)%len(groups);g,p=groups[idx];key=(g,p)
            if key in self.review or now<self.retry.get(key,0):continue
            seconds,required=SPECS[g];end=int(now)//seconds*seconds;anchor=self.anchor.setdefault(key,end)
            try:intervals=self.intervals(g,p)
            except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError):self.review.add(key);continue
            bulk=gap(intervals,anchor,required,seconds)
            # Keep current reference prices available without repeatedly doing
            # only the sliding latest page and starving the older history.
            latest=gap(intervals,end,1,seconds)
            request=bulk if self.turns.get(key,0)%2==0 and bulk else latest or bulk
            if request:
                self.cursor=(idx+1)%len(groups);self.turns[key]=self.turns.get(key,0)+1
                return g,p,*request
        return None
    def collect(self,config=None,*,include_short=False):
        self.include_short=include_short;self.last_dispatch=self.monotonic();r=self.reader;now=r.clock();key=None;self.attempts+=1
        try:
            request=self.next_request(now,include_short)
            if request is None:
                self.last_state='REVIEW_REQUIRED' if self.review else 'BACKOFF' if any(t>now for t in self.retry.values()) else 'IDLE'
                if self.last_state=='IDLE':
                    self.public_cache=None;progress=self.progress(now)
                    self.last_reason='SPARSE_HISTORY' if any(row['aligned']<row['required'] for g,row in progress['granularities'].items() if include_short or g=='ONE_HOUR') else 'UP_TO_DATE'
                return dict(state=self.last_state,reason=self.last_reason)
            g,p,start,end=request;key=(g,p);self.last_granularity=g;self.last_product=p;self.last_state='DOWNLOADING'
            r.begin();r.deadline=min(r.deadline,r.started+6);r.scope()
            raw=r.call('get_candles',product_id=p,start=str(start),end=str(end),granularity=g,limit=350);received=r.clock()
            if g=='ONE_HOUR':
                rows=candle_rows(raw,p,received,start,end);self.hourly.append(p,start,end,received,rows)
            else:
                rows=closed_candles(raw,p,g,received,start,end);self.minute.append(g,p,start,end,received,rows)
            self.last_success=received;self.last_state='COLLECTING';self.last_reason='COLLECTING' if rows else 'EMPTY_RESPONSE'
            self.retry.pop(key,None);return dict(state='COLLECTING',count=len(rows),reason=self.last_reason)
        except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError) as exc:
            self.failures+=1;self.last_reason=reason(exc);self.last_state='REVIEW_REQUIRED' if self.last_reason in ('CLOSED_PRICE_CORRECTION','STORAGE_REVIEW') else 'BACKOFF'
            if key is not None:
                if self.last_state=='REVIEW_REQUIRED':self.review.add(key)
                else:self.retry[key]=now+60
            elif self.last_state=='REVIEW_REQUIRED':self.global_review=True
            return dict(state=self.last_state,reason=self.last_reason)
        finally:self.public_cache=None
    def hour_counts(self,now):
        result={p:dict(bars=0,pages=0) for p in REFERENCES};end=int(now)//3600*3600;first=end-2399*3600
        if not self.hourly.path.exists():return result,0
        with self.hourly.lock,self.hourly.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT pair,COUNT(*) FROM hourly WHERE at>=? AND at<=? GROUP BY pair',(first,end))
            for p,n in cur:
                if p in result:result[p]['bars']=n
            cur.execute('SELECT pair,COUNT(*) FROM batches GROUP BY pair')
            for p,n in cur:
                if p in result:result[p]['pages']=n
            cur.execute('SELECT COUNT(*) FROM (SELECT at FROM hourly WHERE at>=? AND at<=? GROUP BY at HAVING COUNT(DISTINCT pair)=5)',(first,end));aligned=cur.fetchone()[0]
        return result,aligned
    def progress(self,now):
        if self.public_cache is not None and self.monotonic()<self.public_due:return deepcopy(self.public_cache)
        result=dict(state=self.last_state,reason=self.last_reason,attempts=self.attempts,failures=self.failures,
            last_success_age_s=None if self.last_success is None else max(0,now-self.last_success),granularities={})
        for g,(seconds,required) in SPECS.items():
            try:
                if g=='ONE_HOUR':products,aligned=self.hour_counts(now)
                else:products=self.minute.counts(g,now,required);aligned=self.minute.aligned_count(g,now,required)
                state='REVIEW_REQUIRED' if any(key[0]==g for key in self.review) else 'BACKOFF' if any(key[0]==g and until>now for key,until in self.retry.items()) else 'SUFFICIENT_BARS' if aligned>=required else 'PARTIAL' if any(r['bars'] for r in products.values()) else 'EMPTY'
            except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError):
                products={p:dict(bars=0,pages=0) for p in REFERENCES};aligned=0;state='REVIEW_REQUIRED'
            result['granularities'][g]=dict(state=state,interval_s=seconds,required=required,aligned=aligned,products=products)
        self.public_cache=deepcopy(result);self.public_due=self.monotonic()+2;return result
    def reviewed(self,g):return self.global_review or any(key[0]==g for key in self.review)
