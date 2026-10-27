"""CoinCat v60.8: bounded, actual REST-book, multi-horizon learning.

Research observations ONLY. These are not realized Coinbase trades, forecasts,
source/target HOLD comparisons, live permissions, or a second quote store.
All rows live in the existing ForwardStore market SQLite file. No private
wallet assets, amounts or orders are written to research data.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from collections import Counter
import time
from coincat_storage import research_sqlite_bytes, RESEARCH_LIMIT_MIB

HORIZONS=(300,900,3600)
KEEP_DAYS=15
BUCKET_SECONDS=3600
MAX_PER_SCAN=24
MAX_MATURED_PER_SCAN=450
MAX_MARK_DELAY=120
LIMIT_FRACTION=Decimal('.80')


def number(value):
    try:
        d=Decimal(str(value))
        return d if d.is_finite() else None
    except (ValueError,InvalidOperation,TypeError):return None


def _ready_state(observed,first,last,positive):
    """Maturity is only descriptive, never authorizes a buy or SHADOW fill."""
    span=last-first if first is not None and last is not None else 0
    if observed<35 or span<7*86400:
        return 'COLLECTING_INDEPENDENT_DATES'
    return 'HISTORY_MATURED_NOT_PORTFOLIO_VALIDATED'


class ForwardHorizonLab:
    def __init__(self,forward):
        self.forward=forward
        with forward._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS v608_strategy_horizons(
                strategy TEXT NOT NULL,pair TEXT NOT NULL,decision_bucket INTEGER NOT NULL,
                observed_at_utc INTEGER NOT NULL,entry_ask TEXT NOT NULL,fee_taker TEXT NOT NULL,
                horizon_s INTEGER NOT NULL,evaluate_after INTEGER NOT NULL,
                state TEXT NOT NULL, exit_bid TEXT,net_cash_pct TEXT,
                PRIMARY KEY(strategy,pair,decision_bucket,horizon_s));
                CREATE INDEX IF NOT EXISTS idx_v608_due ON
                    v608_strategy_horizons(state,evaluate_after);
                CREATE INDEX IF NOT EXISTS idx_v608_retention ON
                    v608_strategy_horizons(observed_at_utc);
                CREATE INDEX IF NOT EXISTS idx_v608_learning ON
                    v608_strategy_horizons(strategy,horizon_s,state,decision_bucket);''')

    def record_and_mature(self,candidates,*,now=None,fee_rate=None):
        """Use observed past-only signals; future quotes only after target time."""
        now=int(time.time() if now is None else now)
        fee=number(fee_rate)
        checked=0;inserted=0;matured=0;missing=0;storage_paused=False
        # Includes market, relative USD, fee evidence, WAL/SHM: no secondary quota.
        bytes_used=research_sqlite_bytes(self.forward.path.parent)
        max_bytes=RESEARCH_LIMIT_MIB*1048576
        storage_paused=bytes_used>=int(Decimal(max_bytes)*LIMIT_FRACTION)
        with self.forward._db() as db:
            # Prune research only; never mutate financial lots or original v607 trials.
            db.execute('DELETE FROM v608_strategy_horizons WHERE observed_at_utc<?',
                       (now-KEEP_DAYS*86400,))
            due=db.execute('''SELECT strategy,pair,decision_bucket,horizon_s,entry_ask,fee_taker,evaluate_after
                  FROM v608_strategy_horizons WHERE state='PENDING' AND evaluate_after<=?
                  ORDER BY evaluate_after LIMIT ?''',(now,MAX_MATURED_PER_SCAN)).fetchall()
            for strategy,pair,bucket,horizon,entry,fee_saved,target in due:
                # First authentic REST bid within 120 sec of target, no fabricated values.
                mark=db.execute('''SELECT bid FROM market_quotes WHERE pair=?
                    AND at_utc>=? AND at_utc<=? ORDER BY at_utc LIMIT 1''',
                    (pair,target,target+MAX_MARK_DELAY)).fetchone()
                if mark:
                    bid=number(mark[0]);ask=number(entry);cost=number(fee_saved)
                    if bid is not None and ask is not None and cost is not None and bid>0 and ask>0 and 0<=cost<Decimal('.05'):
                        drag=cost+Decimal('.0015')
                        net=((bid*(1-drag))/(ask*(1+drag))-1)*100
                        db.execute('''UPDATE v608_strategy_horizons SET state='OBSERVED',exit_bid=?,net_cash_pct=?
                            WHERE strategy=? AND pair=? AND decision_bucket=? AND horizon_s=? AND state='PENDING' ''',
                            (str(bid),str(net),strategy,pair,bucket,horizon))
                        matured+=1
                elif now>target+MAX_MARK_DELAY:
                    db.execute('''UPDATE v608_strategy_horizons SET state='MISSED_MARK'
                        WHERE strategy=? AND pair=? AND decision_bucket=? AND horizon_s=? AND state='PENDING' ''',
                        (strategy,pair,bucket,horizon))
                    missing+=1
            if fee is not None and Decimal(0)<=fee<Decimal('.05') and not storage_paused:
                for item in list(candidates or ())[:MAX_PER_SCAN]:
                    if item.get('action')!='EXPLORE_ONLY':continue
                    strategy=str(item.get('strategy',''))
                    pair=str(item.get('pair',''))
                    quote_ts=int(item.get('observation_at_utc',0))
                    if not strategy or '-' not in pair or not 0<=now-quote_ts<=120:continue
                    # Use the EXACT recorded ask at/before the observation.
                    entry=db.execute('''SELECT ask FROM market_quotes WHERE pair=? AND at_utc<=?
                        ORDER BY at_utc DESC LIMIT 1''',(pair,quote_ts)).fetchone()
                    ask=number(entry[0]) if entry else None
                    if ask is None or ask<=0:continue
                    checked+=1
                    bucket=now-now%BUCKET_SECONDS
                    for horizon in HORIZONS:
                        result=db.execute('''INSERT OR IGNORE INTO v608_strategy_horizons
                           (strategy,pair,decision_bucket,observed_at_utc,entry_ask,
                           fee_taker,horizon_s,evaluate_after,state)
                           VALUES(?,?,?,?,?,?,?,?, 'PENDING')''',
                           (strategy,pair,bucket,quote_ts,str(ask),str(fee),horizon,now+horizon))
                        inserted+=max(0,result.rowcount)
            # Cover only recent bounded dates, not the full horizon table.
            stats=db.execute('''SELECT strategy,horizon_s,state,COUNT(*),MIN(decision_bucket),
                       MAX(decision_bucket),SUM(CASE WHEN CAST(net_cash_pct AS REAL)>0 THEN 1 ELSE 0 END)
                  FROM v608_strategy_horizons WHERE observed_at_utc>=?
                  GROUP BY strategy,horizon_s,state''',(now-KEEP_DAYS*86400,)).fetchall()
            total=db.execute('SELECT COUNT(*) FROM v608_strategy_horizons').fetchone()[0]
        groups={}
        for strategy,horizon,state,n,first,last,positive in stats:
            key=f'{strategy}:{horizon//60}m'
            entry=groups.setdefault(key,{'OBSERVED':0,'PENDING':0,'MISSED_MARK':0,
                   'positive_cash_after_cost':0,'observed_first':None,'observed_last':None})
            if state in ('OBSERVED','PENDING','MISSED_MARK'):
                entry[state]+=int(n)
            if state=='OBSERVED':
                entry['positive_cash_after_cost']+=int(positive or 0)
                entry['observed_first']=first if entry['observed_first'] is None else min(entry['observed_first'],first)
                entry['observed_last']=last if entry['observed_last'] is None else max(entry['observed_last'],last)
        for entry in groups.values():
            entry['maturity']=_ready_state(entry['OBSERVED'],entry['observed_first'],entry['observed_last'],entry['positive_cash_after_cost'])
            entry.pop('observed_first');entry.pop('observed_last')
        # Bounded observations per hour; never infer database size from current disk bytes alone.
        max_rows_per_day=128*3*len(HORIZONS)*24
        max_rows_15_days=max_rows_per_day*KEEP_DAYS
        return {'state':'RESEARCH_ONLY_NO_PORTFOLIO_OOS','horizons_minutes':[5,15,60],
                'observations_sampled':checked,'new_rows':inserted,'matured':matured,
                'missing':missing,'study':groups,'rows':int(total),
                'storage_paused':storage_paused,'research_bytes_at_scan_start':bytes_used,
                'total_research_limit_bytes':max_bytes,'retention_days':KEEP_DAYS,
                'max_writes_per_scan':MAX_PER_SCAN*len(HORIZONS),
                'theoretical_worst_case_rows_at_full_128_pair_hourly_coverage':max_rows_15_days,
                'eligible_for_shadow':False,'eligible_for_live':False,
                'scope':'pair BUY-then-SELL versus CASH; NOT funding-asset HOLD or a validated strategy forecast'}


def status_text(strategy,route,horizons):
    s=strategy or {};r=route or {};h=horizons or {}
    return ('AI LAB → ONE PORTFOLIO PLANNER → SHADOW • patterns '+str(s.get('total_candidates',0))+
        ' • strategy funded-route reviews '+str(r.get('strategy_route_reviews',0))+
        ' • 5/15/60m learning '+str(h.get('matured',0))+' new outcomes'+
        (' • RESEARCH QUOTA HOLD' if h.get('storage_paused') else '')+
        ' • no verified portfolio-edge trade')


def diagnostics(strategy,route,horizons,storage=None):
    s=strategy or {};r=route or {};h=horizons or {};st=storage or {}
    lines=['V60.8 ONE-PLANNER DECISION + RESEARCH STORAGE EVIDENCE',
        status_text(s,r,h),
        'Portfolio feeds verified AVAILABLE+ENROLLED funding; SHADOW uses evolved modeled holdings.',
        'V60.11 STRATEGY-FORWARD HANDOFF: mature 5/15/60m observations annotate same planner; pair-vs-cash studies are DESCRIPTIVE and NEVER produce oos_validated=True.',
        'Observations for a strategy are not independent across its product pairs; conditional funded HOLD-vs-SWITCH remains REQUIRED.',
        'AI Lab strategies and ordinary BUY signals share ONE planner; no separate broker, live POST or fake fills.',
        'Strategy route target count: '+str(r.get('strategy_targets',0)),
        'Strategy funded route reviews: '+str(r.get('strategy_route_reviews',0)),
        'Strategy costed route proposals: '+str(r.get('strategy_routes_feasible',0)),
        'Strategy-only routes certified for SHADOW fills: 0 (requires conditional portfolio OOS).',
        'SELL-first screened holdings: '+str((r.get('sell_first') or {}).get('screened',0)),
        'Futures horizon minutes: 5, 15, 60; observations only from authentic later REST books.',
        'New horizon rows: '+str(h.get('new_rows',0))+'; matured: '+str(h.get('matured',0))+
            '; missing: '+str(h.get('missing',0))+'; total rows: '+str(h.get('rows','n/a')),
        'Research table retention days: '+str(h.get('retention_days',KEEP_DAYS))+
            '; theoretical maximum row bound: '+str(h.get('theoretical_worst_case_rows_at_full_128_pair_hourly_coverage','n/a')),
        'Research insert pause >=80% of shared 1GiB cap: '+str(bool(h.get('storage_paused',False))),
        'Active storage research MiB: '+str((st.get('research') or {}).get('used_mb','unavailable'))+
          '/'+str((st.get('research') or {}).get('limit_mb',RESEARCH_LIMIT_MIB)),
        'Actual SQLite growth depends on page sizes, journals and market rates; row bound is NOT a byte guarantee.',
        'Future portfolio P&L measured versus HOLD only after independently validated complete route decisions.',
        'Do not interpret no SHADOW FIFO fills as broken FIFO; proposal and independent edge qualification are separate.',
        'NO SDK/POST • NO REAL FINANCIAL WRITES • LIVE ALL-SPOT SUBMISSION BLOCKED.']
    return '\n'.join(lines)
