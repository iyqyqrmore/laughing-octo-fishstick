"""CoinCat v40 forward BUY / SELL-vs-HOLD research.

Research-only counterfactuals, NOT executable orders, short positions, or a
trained profitability model. Every label requires an actually observed future
bid/ask quote within a bounded evaluation window. Never fill offline gaps with
historical candles. All percentages include estimated two-leg costs.
"""
from decimal import Decimal
import time,sqlite3
from coincat_live import D

class DirectionalLab:
    def __init__(self,store,fee_learning=None):
        self.store=store;self.fee_learning=fee_learning
        with self.store._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS directional_trials (
              id INTEGER PRIMARY KEY, pair TEXT NOT NULL, observed_at INTEGER NOT NULL,
              horizon_at INTEGER NOT NULL, entry_bid TEXT NOT NULL,entry_ask TEXT NOT NULL,
              exit_bid TEXT,exit_ask TEXT, buy_net_pct TEXT,sell_rebuy_net_pct TEXT,
              hold_price_pct TEXT, state TEXT NOT NULL DEFAULT 'PENDING',
              UNIQUE(pair,observed_at));
            CREATE INDEX IF NOT EXISTS idx_directional_due ON directional_trials(state,horizon_at);
            ''')
            cols={r[1] for r in db.execute('PRAGMA table_info(directional_trials)')}
            for column in ('fee_taker_at_entry','fee_source_at_entry'):
                if column not in cols:db.execute(f'ALTER TABLE directional_trials ADD COLUMN {column} TEXT')

    def record(self,pair,bid,ask,now=None):
        now=int(time.time() if now is None else now)
        bid,ask=D(bid),D(ask)
        if not (0<bid<=ask):return False
        block=now-now%1800
        fee=None
        source='UNVERIFIED_ASSUMPTION'
        if self.fee_learning is not None:
            tier=self.fee_learning.latest_tier(now=now)
            if tier['fresh']:
                fee=str(tier['taker']);source='AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY'
        with self.store._db() as db:
            r=db.execute('INSERT OR IGNORE INTO directional_trials(pair,observed_at,horizon_at,entry_bid,entry_ask,fee_taker_at_entry,fee_source_at_entry) VALUES(?,?,?,?,?,?,?)',
                         (pair,block,now+1800,str(bid),str(ask),fee,source))
        return bool(r.rowcount)

    def evaluate(self,now=None):
        now=int(time.time() if now is None else now)
        with self.store._db() as db:
            db.row_factory=sqlite3.Row
            due=db.execute("SELECT * FROM directional_trials WHERE state='PENDING' AND horizon_at<=? ORDER BY horizon_at LIMIT 250",(now,)).fetchall()
        evaluated=missed=0
        for item in due:
            with self.store._db() as db:
                db.row_factory=sqlite3.Row
                quote=db.execute('SELECT at_utc,bid,ask FROM market_quotes WHERE pair=? AND at_utc>=? AND at_utc<=? ORDER BY at_utc LIMIT 1',
                    (item['pair'],item['horizon_at'],item['horizon_at']+1200)).fetchone()
                if quote:
                    bid,ask=D(quote['bid']),D(quote['ask']);entry_bid=D(item['entry_bid']);entry_ask=D(item['entry_ask'])
                    if bid<=0 or ask<bid:continue
                    # Legacy trials without entry-time fee evidence can still
                    # retain quote-only history, but not invented net P&L.
                    if item['fee_source_at_entry']!='AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY' or item['fee_taker_at_entry'] is None:
                        db.execute("UPDATE directional_trials SET state='FEE_UNVERIFIED',exit_bid=?,exit_ask=? WHERE id=? AND state='PENDING'",
                                   (str(bid),str(ask),item['id']))
                        continue
                    entry_fee=D(item['fee_taker_at_entry'])
                    in_fee=out_fee=entry_fee
                    # BUY: buy at observed ask, sell 30m later at bid.
                    buy_pct=(bid*(1-out_fee)/(entry_ask*(1+in_fee))-1)*100
                    # SELL/rebuy: an owned-inventory counterfactual, not a short.
                    sell_pct=(entry_bid*(1-out_fee)/(ask*(1+in_fee))-1)*100
                    hold_pct=(bid/entry_bid-1)*100
                    db.execute("UPDATE directional_trials SET state='OBSERVED',exit_bid=?,exit_ask=?,buy_net_pct=?,sell_rebuy_net_pct=?,hold_price_pct=? WHERE id=? AND state='PENDING'",
                               (str(bid),str(ask),str(buy_pct),str(sell_pct),str(hold_pct),item['id']))
                    evaluated+=1
                elif now>item['horizon_at']+1200:
                    db.execute("UPDATE directional_trials SET state='MISSED_OFFLINE' WHERE id=? AND state='PENDING'",(item['id'],))
                    missed+=1
        return dict(evaluated=evaluated,missed_offline=missed)

    def stats(self,pair=None):
        query="SELECT pair,buy_net_pct,sell_rebuy_net_pct,hold_price_pct FROM directional_trials WHERE state='OBSERVED' AND fee_source_at_entry='AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY'"
        with self.store._db() as db:
            db.row_factory=sqlite3.Row
            rows=db.execute(query+(' AND pair=?' if pair else '')+' ORDER BY observed_at DESC LIMIT 1000',((pair,) if pair else ())).fetchall()
        if not rows:return dict(n=0,buy_net_avg=None,sell_rebuy_avg=None,hold_avg=None)
        avg=lambda k:sum((D(row[k]) for row in rows),Decimal(0))/len(rows)
        return dict(n=len(rows),buy_net_avg=avg('buy_net_pct'),sell_rebuy_avg=avg('sell_rebuy_net_pct'),hold_avg=avg('hold_price_pct'))

    def overview(self):
        with self.store._db() as db:
            r=db.execute("SELECT COUNT(*),SUM(CASE WHEN state='OBSERVED' AND fee_source_at_entry='AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY' THEN 1 ELSE 0 END),SUM(CASE WHEN state='MISSED_OFFLINE' THEN 1 ELSE 0 END) FROM directional_trials").fetchone()
        return dict(total=int(r[0] or 0),verified=int(r[1] or 0),missed=int(r[2] or 0))

    def prune(self,now=None,days=180):
        now=int(time.time() if now is None else now)
        with self.store._db() as db:
            db.execute('DELETE FROM directional_trials WHERE observed_at<?',(now-days*86400,))


def readiness(history_pairs,watched,fully_observed,verified_outcomes,gpu_evaluated=False):
    """0-100 research COVERAGE, not a probability of profit or trade permission."""
    pairs=max(int(watched),1)
    parts={
        'Recent candle context':min(1,max(0,history_pairs)/pairs),
        'Fresh quote coverage':min(1,max(0,fully_observed)/pairs),
        'Forward two-way outcomes':min(1,max(0,verified_outcomes)/240),
        'Diverse evaluation periods':min(1,max(0,verified_outcomes)/800),
        'GPU validation (observe-only)':1 if gpu_evaluated else 0,
    }
    weights=[.25,.30,.25,.15,.05]
    return dict(percent=round(100*sum(a*w for a,w in zip(parts.values(),weights))),components=parts)


def rotation_reviews(held_assets,buy_candidates,stats_for_pair,*,min_labels=24,min_edge_pct=Decimal('1.5')):
    """Research-only proposals. No order instructions, no capital reallocation.

    Compare historically observed after-cost BUY-outcomes with holding the
    enrolled asset. This is NOT a forecast; approval to trade is never implied.
    """
    findings=[]
    for source in held_assets:
        source_pair=source['pair'];old=stats_for_pair(source_pair)
        if old['n']<min_labels:continue
        for idea in buy_candidates:
            target=idea['pair']
            if source_pair==target or target.split('-')[0]==source_pair.split('-')[0]:continue
            if source_pair.split('-')[1]!=target.split('-')[1]:continue
            new=stats_for_pair(target)
            if new['n']<min_labels:continue
            # New's round-trip advantage vs price-only HOLD; add cushion for
            # extra implementation risk, variability, and delayed fills.
            edge=new['buy_net_avg']-old['hold_avg']
            if edge>min_edge_pct:
                findings.append({'source':source_pair,'target':target,'edge_pct':edge,
                    'reason':f'Research comparison +{edge:.2f}% historical 30m after-cost edge vs HOLD; NOT a prediction or executable rotation'})
    return sorted(findings,key=lambda r:r['edge_pct'],reverse=True)[:6]
