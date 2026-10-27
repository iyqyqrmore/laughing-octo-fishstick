"""CoinCat v40 forward-only market data store; NO simulated trading tables.

Uses persisted live market_quotes when present and creates separate live hourly/daily
summaries. Never deletes real order/fill ledgers. SQLite maintenance prunes
market quotes; schema evolves additively with compatible prior forward records.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from datetime import datetime,timezone
import sqlite3,time
from coincat_storage import RESEARCH_LIMIT_MIB, research_sqlite_bytes

@dataclass(frozen=True)
class Retention:
    max_mb:int=RESEARCH_LIMIT_MIB
    raw_days:int=3
    hourly_days:int=120
    daily_days:int=365

class ForwardStore:
    def __init__(self,path,retention=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.retention=retention or Retention()
        with self._db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS market_quotes(
               pair TEXT NOT NULL,at_utc INTEGER NOT NULL,bid TEXT NOT NULL,
               ask TEXT NOT NULL,source TEXT NOT NULL DEFAULT 'coinbase',
               PRIMARY KEY(pair,at_utc));
            CREATE INDEX IF NOT EXISTS idx_quotes_age ON market_quotes(at_utc);
            CREATE TABLE IF NOT EXISTS live_quote_summaries(
               pair TEXT NOT NULL,interval_seconds INTEGER NOT NULL,bucket_utc INTEGER NOT NULL,
               samples INTEGER NOT NULL,open_mid REAL NOT NULL,close_mid REAL NOT NULL,
               high_mid REAL NOT NULL,low_mid REAL NOT NULL,mean_spread_bps REAL NOT NULL,
               PRIMARY KEY(pair,interval_seconds,bucket_utc));
            CREATE INDEX IF NOT EXISTS idx_live_summaries_age ON live_quote_summaries(interval_seconds,bucket_utc);
            CREATE TABLE IF NOT EXISTS research_history_hourly(
               pair TEXT NOT NULL,at_utc INTEGER NOT NULL,open TEXT NOT NULL,
               high TEXT NOT NULL,low TEXT NOT NULL,close TEXT NOT NULL,volume TEXT NOT NULL,
               source TEXT NOT NULL DEFAULT 'coinbase-10day',PRIMARY KEY(pair,at_utc));
            CREATE TABLE IF NOT EXISTS research_history_sync(
               pair TEXT PRIMARY KEY,synced_at INTEGER NOT NULL,candles INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_history_age ON research_history_hourly(at_utc);
            CREATE TABLE IF NOT EXISTS catalog_discovery_latest(
                pair TEXT PRIMARY KEY,at_utc INTEGER NOT NULL,bid TEXT NOT NULL,
                ask TEXT NOT NULL,prior_at_utc INTEGER,prior_mid TEXT,samples INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS idx_catalog_discovery_age ON catalog_discovery_latest(at_utc);
            CREATE TABLE IF NOT EXISTS live_store_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
    @contextmanager
    def _db(self):
        c=sqlite3.connect(str(self.path),timeout=30)
        try:
            c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=30000')
            with c:yield c
        finally:c.close()
    def record_quote(self,pair,timestamp_utc,bid,ask,source='coinbase-live-v40'):
        from coincat_live import dec
        b=dec(bid);a=dec(ask)
        if not pair or not 0<b<=a:raise ValueError('Bad market bid/ask')
        t=int(timestamp_utc)
        with self._db() as c:
            cur=c.execute('INSERT OR IGNORE INTO market_quotes(pair,at_utc,bid,ask,source) VALUES(?,?,?,?,?)',
                          (pair,t,str(b),str(a),source))
            if not cur.rowcount:return False
            mid=float((a+b)/2);spread=float((a-b)/a*10000)
            for size in (3600,86400):
                bucket=t-t%size
                c.execute('''INSERT INTO live_quote_summaries VALUES(?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(pair,interval_seconds,bucket_utc) DO UPDATE SET
                   samples=samples+1,close_mid=excluded.close_mid,
                   high_mid=MAX(high_mid,excluded.high_mid),low_mid=MIN(low_mid,excluded.low_mid),
                   mean_spread_bps=(mean_spread_bps*samples+excluded.mean_spread_bps)/(samples+1)''',
                  (pair,size,bucket,1,mid,mid,mid,mid,spread))
        return True
    def recent_bid_ask(self,*,now=None,max_age=120,limit=3500):
        """Recent Coinbase public REST bid/ask observations for read-only FX.

        Combines deep market_quotes and *separate* scouting observations, but
        NEVER treats ticker_batch last-trade updates as bid/ask. Latest wins.
        Returned data cannot authorize broker order previews or fills.
        """
        if not 0 < int(max_age) <= 300 or not 0 < int(limit) <= 3500:
            raise ValueError('Unsafe research quote query bounds')
        cutoff=int(time.time() if now is None else now)-int(max_age)
        with self._db() as c:
            deep=c.execute("""SELECT q.pair,q.bid,q.ask,q.at_utc FROM market_quotes q
                JOIN (SELECT pair,MAX(at_utc) stamp FROM market_quotes
                      WHERE at_utc>=? GROUP BY pair) latest
                  ON q.pair=latest.pair AND q.at_utc=latest.stamp
                ORDER BY q.at_utc DESC LIMIT ?""",(cutoff,int(limit))).fetchall()
            survey=c.execute("""SELECT pair,bid,ask,at_utc FROM catalog_discovery_latest
                WHERE at_utc>=? ORDER BY at_utc DESC LIMIT ?""",(cutoff,int(limit))).fetchall()
        rows={}
        for pair,bid,ask,ts in list(deep)+list(survey):
            if pair not in rows or ts>rows[pair][2]:
                rows[pair]=(bid,ask,ts)
        return rows

    def get_state_int(self,key,default=0):
        with self._db() as c:
            row=c.execute('SELECT value FROM live_store_state WHERE key=?',(key,)).fetchone()
        try:return int(row[0]) if row else int(default)
        except (ValueError,TypeError):return int(default)

    def set_state_int(self,key,value):
        with self._db() as c:
            c.execute('INSERT OR REPLACE INTO live_store_state(key,value) VALUES(?,?)',(key,str(int(value))))

    def record_discovery(self,pair,timestamp_utc,bid,ask):
        """Last-only catalog sampling, isolated from signal/forward-label tables."""
        from coincat_live import dec
        b=dec(bid);a=dec(ask)
        if not pair or not 0<b<=a:raise ValueError('Bad discovery bid/ask')
        ts=int(timestamp_utc)
        with self._db() as c:
            row=c.execute('SELECT at_utc,bid,ask,samples FROM catalog_discovery_latest WHERE pair=?',(pair,)).fetchone()
            if row and ts<=int(row[0]):return False
            ptime=int(row[0]) if row else None
            pmid=str((dec(row[1])+dec(row[2]))/2) if row else None
            count=int(row[3])+1 if row else 1
            c.execute('INSERT OR REPLACE INTO catalog_discovery_latest VALUES(?,?,?,?,?,?,?)',
                      (pair,ts,str(b),str(a),ptime,pmid,count))
        return True

    def universe_coverage(self,catalog,now=None,lookback=86400):
        """Distinct sampled eligible pairs; not model performance or trade readiness."""
        pairs=set(catalog)
        if not pairs:return 0
        cutoff=int(now if now is not None else time.time())-lookback
        with self._db() as c:
            names=c.execute("SELECT pair FROM catalog_discovery_latest WHERE at_utc>=? UNION SELECT DISTINCT pair FROM market_quotes WHERE at_utc>=?",(cutoff,cutoff)).fetchall()
        return len(pairs.intersection(r[0] for r in names))

    def history_refresh_window(self,pair,now=None):
        """Only fetch uncached recent time, bounded to last 10 days after a long shutdown.

        Historical OHLCV cannot reconstruct missing true forward bid/ask ticks.
        """
        now=int(now if now is not None else time.time())
        oldest=now-10*86400
        with self._db() as c:
            row=c.execute('SELECT MAX(at_utc),COUNT(*) FROM research_history_hourly WHERE pair=? AND at_utc>=?',
                          (pair,oldest)).fetchone()
        latest=row[0] if row else None
        # Also repair thin/corrupt historical caches by pulling the full window.
        start=max(oldest,int(latest)-2*3600) if latest is not None and row[1]>=12 else oldest
        return start,now

    def history_health(self,now=None):
        now=int(now if now is not None else time.time())
        with self._db() as c:
            pairs=c.execute('SELECT COUNT(DISTINCT pair) FROM research_history_hourly WHERE at_utc>=?',
                           (now-10*86400,)).fetchone()[0]
            candles=c.execute('SELECT COUNT(*) FROM research_history_hourly WHERE at_utc>=?',
                             (now-10*86400,)).fetchone()[0]
            latest_quote=c.execute('SELECT MAX(at_utc) FROM market_quotes').fetchone()[0]
            last_maintenance=c.execute("SELECT value FROM live_store_state WHERE key='last_maintenance'").fetchone()
        mb=research_sqlite_bytes(self.path.parent)/(1024*1024)
        return {'pairs':pairs,'candles':candles,'latest_live_quote':latest_quote,'size_mb':round(mb,2),
                'limit_mb':self.retention.max_mb,'last_maintenance':int(last_maintenance[0]) if last_maintenance else None}

    def history_current(self,pair,now=None):
        now=int(now if now is not None else time.time())
        with self._db() as c:
            row=c.execute('SELECT synced_at,candles FROM research_history_sync WHERE pair=?',(pair,)).fetchone()
        return bool(row and row[1]>=12 and 0<=now-int(row[0])<20*3600)

    def save_history(self,pair,candles,now=None):
        now=int(now or time.time())
        if not candles:return 0
        with self._db() as c:
            c.executemany('INSERT OR REPLACE INTO research_history_hourly (pair,at_utc,open,high,low,close,volume,source) VALUES(?,?,?,?,?,?,?,?)',
                          [(pair,*row,'coinbase-10day') for row in candles])
            active=c.execute('SELECT COUNT(*) FROM research_history_hourly WHERE pair=? AND at_utc>=?',
                             (pair,now-10*86400)).fetchone()[0]
            c.execute('INSERT OR REPLACE INTO research_history_sync(pair,synced_at,candles) VALUES(?,?,?)',
                      (pair,now,active))
        return len(candles)

    def history_status(self,pair,now=None):
        now=int(now or time.time())
        with self._db() as c:
            rows=c.execute('SELECT at_utc,close FROM research_history_hourly WHERE pair=? AND at_utc>=? ORDER BY at_utc',(pair,now-11*86400)).fetchall()
        if len(rows)<12:return {'candles':len(rows),'change_24h':None,'change_10d':None}
        from decimal import Decimal
        end=Decimal(rows[-1][1]);prev=next((Decimal(c) for ts,c in reversed(rows) if ts<=rows[-1][0]-86400),None)
        start=Decimal(rows[0][1]); pct=lambda x:float((end/x-1)*100) if x and x>0 else None
        return {'candles':len(rows),'change_24h':pct(prev),'change_10d':pct(start)}

    def maintenance(self,now=None):
        now=int(now or time.time())
        db_size=lambda:research_sqlite_bytes(self.path.parent)/(1024*1024)
        with self._db() as c:
            row=c.execute("SELECT value FROM live_store_state WHERE key='last_maintenance'").fetchone()
            if row is None or now-int(row[0])>=86400 or db_size()>self.retention.max_mb:
                c.execute('DELETE FROM market_quotes WHERE at_utc<?',(now-self.retention.raw_days*86400,))
                c.execute('DELETE FROM catalog_discovery_latest WHERE at_utc<?',(now-7*86400,))
                c.execute('DELETE FROM research_history_hourly WHERE at_utc<?',(now-11*86400,))
                c.execute('DELETE FROM research_history_sync WHERE synced_at<?',(now-14*86400,))
                c.execute('DELETE FROM live_quote_summaries WHERE (interval_seconds=3600 AND bucket_utc<?) OR (interval_seconds=86400 AND bucket_utc<?)',
                          (now-self.retention.hourly_days*86400,now-self.retention.daily_days*86400))
                c.execute("INSERT OR REPLACE INTO live_store_state(key,value) VALUES('last_maintenance',?)",(str(now),))
        mb=db_size()
        # Weekly SQLite compaction, outside any active write transaction.
        with self._db() as c:
            previous=c.execute("SELECT value FROM live_store_state WHERE key='last_compact'").fetchone()
        if previous is None or now-int(previous[0])>=7*86400:
            try:
                with self._db() as c:
                    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                    c.execute('VACUUM')
                    c.execute("INSERT OR REPLACE INTO live_store_state(key,value) VALUES('last_compact',?)",(str(now),))
            except sqlite3.OperationalError:
                pass  # Storage budget gate below remains fail closed.
            mb=db_size()
        if mb>self.retention.max_mb:
            # Safe pressure relief: shorten ONLY raw quote retention; live orders/fills are in a different DB.
            with self._db() as c:
                c.execute('DELETE FROM market_quotes WHERE at_utc<?',(now-86400,))
                # Checkpoint only AFTER this write transaction commits.
            # Explicit checkpoint may shrink WAL; periodic maintenance does not touch order data.
            with self._db() as c:
                c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            mb=db_size()
        return {'size_mb':mb,'limit_mb':self.retention.max_mb,'over_limit':mb>self.retention.max_mb}
