"""New minute/five-minute reference cache; no financial or old-trial migration."""
from contextlib import closing,contextmanager
from pathlib import Path
import hashlib,sqlite3,threading
from coincat_beta_store import BetaBlocked,pack,unpack
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS

REFERENCES=tuple(a+'-USD' for a in WATCH_ASSETS)
RESOLUTIONS={'ONE_MINUTE':60,'FIVE_MINUTE':300}
APP_ID=0x43434D35

def closed_candles(raw,pair,granularity,received,start,end):
    seconds=RESOLUTIONS[granularity];items=raw.get('candles') if isinstance(raw,dict) else None
    if pair not in REFERENCES or not isinstance(items,list) or len(items)>350:raise BetaBlocked('HISTORY_RESPONSE_INVALID')
    rows=[];seen=set()
    for item in items:
        try:
            t=int(item['start'])
            if t==end and t+seconds>received:continue
            if str(t)!=str(item['start']) or t%seconds or not start<=t<end or t+seconds>received or t in seen:raise ValueError()
            o,h,l,c,v=(exact(item[k]) for k in ('open','high','low','close','volume'))
            if not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError()
        except (KeyError,ValueError,TypeError,ArithmeticError):raise BetaBlocked('HISTORY_CANDLE_NOT_CLOSED_OR_INVALID') from None
        seen.add(t);rows.append(dict(pair=pair,at=t+seconds,open=o,high=h,low=l,close=c,volume=v))
    return sorted(rows,key=lambda r:r['at'])

class CandleCache:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.revision=0;self.revisions=dict.fromkeys(RESOLUTIONS,0);self.broken=False
        if self.path.exists():
            try:
                with self.db() as db,closing(db.cursor()) as cur:
                    cur.execute('PRAGMA quick_check(1)')
                    if cur.fetchone()[0]!='ok':raise BetaBlocked('HISTORY_CACHE_INTEGRITY')
                    cur.execute('SELECT COUNT(*) FROM candles');cur.fetchone()
            except (OSError,sqlite3.Error,ValueError):self.broken=True
    @contextmanager
    def db(self,*,create=False):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('HISTORY_CACHE_PATH_REVIEW')
        if self.path.exists() and self.path.stat().st_size>128*1024*1024:raise BetaBlocked('HISTORY_CACHE_STORAGE_LIMIT')
        if create:self.path.parent.mkdir(parents=True,exist_ok=True)
        target=self.path if create else self.path.resolve().as_uri()+'?mode=rw'
        with closing(sqlite3.connect(target,uri=not create,timeout=1)) as db:
            if not create:
                with closing(db.cursor()) as cur:
                    cur.execute('PRAGMA application_id');app=cur.fetchone()[0];cur.execute('PRAGMA user_version')
                    if app!=APP_ID or cur.fetchone()[0]!=1:raise BetaBlocked('HISTORY_CACHE_IDENTITY')
            yield db
    def initialize(self):
        if self.broken:raise BetaBlocked('HISTORY_CACHE_REVIEW_REQUIRED')
        if self.path.exists():return
        with self.db(create=True) as db,db,closing(db.cursor()) as cur:
            cur.execute('PRAGMA application_id='+str(APP_ID));cur.execute('PRAGMA user_version=1')
            cur.execute('CREATE TABLE candles(granularity TEXT,pair TEXT,at INTEGER,payload TEXT,digest TEXT,PRIMARY KEY(granularity,pair,at))')
            cur.execute('CREATE TABLE batches(id INTEGER PRIMARY KEY,granularity TEXT,pair TEXT,start INTEGER,end INTEGER,received REAL,count INTEGER)')
    def append(self,granularity,pair,start,end,received,rows):
        if granularity not in RESOLUTIONS or pair not in REFERENCES or any(r.get('pair')!=pair for r in rows):raise BetaBlocked('HISTORY_REFERENCE_SCOPE')
        with self.lock:
            self.initialize()
            with self.db() as db,db,closing(db.cursor()) as cur:
                cur.execute('BEGIN IMMEDIATE')
                for row in rows:
                    raw=pack(row);sha=hashlib.sha256(raw.encode()).hexdigest()
                    cur.execute('SELECT payload,digest FROM candles WHERE granularity=? AND pair=? AND at=?',(granularity,pair,row['at']));old=cur.fetchone()
                    if old:
                        if hashlib.sha256(old[0].encode()).hexdigest()!=old[1]:raise BetaBlocked('HISTORY_CACHE_DIGEST_CONFLICT')
                        prior=unpack(old[0])
                        if any(prior[k]!=row[k] for k in ('open','high','low','close')):raise BetaBlocked('HISTORY_CLOSED_PRICE_CORRECTION_REVIEW')
                    else:cur.execute('INSERT INTO candles VALUES(?,?,?,?,?)',(granularity,pair,row['at'],raw,sha))
                cur.execute('INSERT INTO batches(granularity,pair,start,end,received,count) VALUES(?,?,?,?,?,?)',(granularity,pair,start,end,received,len(rows)))
            self.revision+=1
            self.revisions[granularity]+=1
    def intervals(self,granularity,pair):
        if not self.path.exists():return []
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT start,end FROM batches WHERE granularity=? AND pair=? ORDER BY start',(granularity,pair));return cur.fetchall()
    def panel(self,granularity,now,limit):
        if self.broken:raise BetaBlocked('HISTORY_CACHE_REVIEW_REQUIRED')
        if not self.path.exists():return []
        seconds=RESOLUTIONS[granularity];end=int(now)//seconds*seconds;first=end-(limit-1)*seconds;columns={p:{} for p in REFERENCES}
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT pair,at,payload,digest FROM candles WHERE granularity=? AND at>=? AND at<=? ORDER BY at',(granularity,first,end))
            for pair,at,raw,sha in cur:
                if pair not in columns or hashlib.sha256(raw.encode()).hexdigest()!=sha:raise BetaBlocked('HISTORY_CACHE_DIGEST_CONFLICT')
                row=unpack(raw)
                if row.get('pair')!=pair or row.get('at')!=at or exact(row['close'])<=0:raise BetaBlocked('HISTORY_CACHE_IDENTITY_CONFLICT')
                columns[pair][at]=row['close']
        times=set.intersection(*(set(v) for v in columns.values()))
        return [dict(at=t,marks={a:columns[a+'-USD'][t] for a in WATCH_ASSETS}) for t in sorted(times)]
    def counts(self,granularity,now,limit):
        result={p:dict(bars=0,pages=0) for p in REFERENCES}
        if not self.path.exists():return result
        seconds=RESOLUTIONS[granularity];end=int(now)//seconds*seconds;first=end-(limit-1)*seconds
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT pair,COUNT(*) FROM candles WHERE granularity=? AND at>=? AND at<=? GROUP BY pair',(granularity,first,end))
            for pair,n in cur:
                if pair in result:result[pair]['bars']=n
            cur.execute('SELECT pair,COUNT(*) FROM batches WHERE granularity=? GROUP BY pair',(granularity,))
            for pair,n in cur:
                if pair in result:result[pair]['pages']=n
        return result
    def aligned_count(self,granularity,now,limit):
        if not self.path.exists():return 0
        seconds=RESOLUTIONS[granularity];end=int(now)//seconds*seconds;first=end-(limit-1)*seconds
        with self.lock,self.db() as db,closing(db.cursor()) as cur:
            cur.execute('SELECT COUNT(*) FROM (SELECT at FROM candles WHERE granularity=? AND at>=? AND at<=? GROUP BY at HAVING COUNT(DISTINCT pair)=5)',(granularity,first,end))
            return cur.fetchone()[0]
