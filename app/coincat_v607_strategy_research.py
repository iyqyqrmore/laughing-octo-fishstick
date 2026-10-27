"""Original CoinCat strategy comparison, public REST bids/asks only.

READ-ONLY research. No broker, portfolio ledger, account client or order APIs.
All candidates must still pass existing independent HOLD/OOS/SHADOW gates.
Market marks come from the ONE existing ForwardStore.market_quotes database.
Methods inspired by widely described strategy patterns, not copied from other bots.
"""
from __future__ import annotations
from collections import Counter
from decimal import Decimal, InvalidOperation
import time

STRATEGIES = ('MOMENTUM_BASELINE', 'RANGE_REVERSION', 'BREAKOUT')
HORIZON_S = 3600
LATER_GRACE_S = 1200
MAX_PAIRS = 128


def _dec(x):
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def analyze_pair(pair, observations, *, now):
    """Compare independent, past-only regimes at decision time.

    Returns candidate observations, never BUY/trade authority. Price movement
    is descriptive and NOT an expected after-fee advantage or GPU validation.
    """
    out={'pair':str(pair),'regime':'UNKNOWN','candidates':[], 'blocker':'',
         'observations':len(observations or ()), 'last_quote_age_s':None}
    rows=[]
    for item in observations or ():
        if not isinstance(item,(tuple,list)) or len(item)<3:continue
        try:ts=int(item[0])
        except (ValueError,TypeError):continue
        b,a=_dec(item[1]),_dec(item[2])
        if b is None or a is None or not 0<b<=a or ts>int(now):continue
        rows.append((ts,b,a))
    rows=sorted(rows,key=lambda x:x[0]); rows=rows[-80:]
    if not rows:
        out['blocker']='NO_REAL_BID_ASK';return out
    out['last_quote_age_s']=int(now)-rows[-1][0]
    if len(rows)<8 or rows[-1][0]-rows[0][0]<720 or not 0<=out['last_quote_age_s']<=180:
        out['blocker']='INSUFFICIENT_MATURE_FRESH_QUOTES';return out
    spread=(rows[-1][2]-rows[-1][1])/rows[-1][2]*Decimal(10000)
    if spread>25:
        out['blocker']='SPREAD_GT_25_BPS';return out
    mids=[(b+a)/2 for _,b,a in rows]
    start=mids[0]; last=mids[-1]
    if start<=0:
        out['blocker']='BAD_MID';return out
    momentum=(last/start-1)*100
    before=mids[:-1]
    prior_low=min(before);prior_high=max(before)
    prior_range=(prior_high-prior_low)/prior_low*100 if prior_low>0 else Decimal(0)
    # Regime recognition is descriptive; none of these rules predicts profit.
    if abs(momentum)>=Decimal('.35'):
        out['regime']='TRENDING'
    elif prior_range<=Decimal('.8'):
        out['regime']='RANGING'
    else:
        out['regime']='MIXED'
    candidates=[]
    if momentum>=Decimal('.35') and last>mids[-4]:
        candidates.append(('MOMENTUM_BASELINE', momentum, 'OBSERVED_TREND'))
    # Mean reversion only if latest price has moved close to past lower bound
    # AND earlier observations show meaningful sideways range; no lookahead.
    if prior_range>=Decimal('.15') and prior_range<=Decimal('2') and last<=prior_low*Decimal('1.0015'):
        candidates.append(('RANGE_REVERSION', -momentum, 'TESTING_RANGE_LOWER_BOUND'))
    # A fresh breakout must exceed all earlier mids, not just an arbitrary
    # latest-minus-first positive move. Its future after-cost edge is UNKNOWN.
    if prior_high>0 and last>=prior_high*Decimal('1.002') and last>mids[-4]:
        candidates.append(('BREAKOUT',(last/prior_high-1)*100,'PRIOR_HIGH_BREAK'))
    out['candidates']=[{'pair':str(pair),'strategy':s,'regime':out['regime'],
        'observation_at_utc':rows[-1][0],'observed_pct':score,
        'momentum_pct':momentum,'spread_bps':spread,'action':'EXPLORE_ONLY',
        'reason':reason,'sends_orders':False,'oos_validated':False}
        for s,score,reason in candidates]
    if not candidates:out['blocker']='NO_STRATEGY_PATTERN'
    return out


class StrategyResearch:
    """Same existing market SQLite file; NO second quote source/ledger."""
    def __init__(self,forward):
        self.forward=forward
        with self.forward._db() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS v607_strategy_trials(
              strategy TEXT NOT NULL, pair TEXT NOT NULL, observed_at_utc INTEGER NOT NULL,
              decision_bucket INTEGER NOT NULL, entry_ask TEXT NOT NULL,
              fee_taker TEXT NOT NULL, evaluate_after INTEGER NOT NULL,
              outcome_state TEXT NOT NULL, exit_bid TEXT, after_cost_pct TEXT,
              PRIMARY KEY(strategy,pair,decision_bucket))''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_v607_strategy_outcome ON v607_strategy_trials(outcome_state,evaluate_after)')

    def evaluate_matured(self,now):
        """Mature only on actual later quotes near target, never offline imputation."""
        observed=missed=0
        with self.forward._db() as c:
            pending=c.execute('''SELECT strategy,pair,decision_bucket,entry_ask,fee_taker,evaluate_after
                 FROM v607_strategy_trials WHERE outcome_state='PENDING' AND evaluate_after<=?
                 ORDER BY evaluate_after LIMIT 300''',(int(now),)).fetchall()
            for strategy,pair,bucket,entry,fee,target in pending:
                mark=c.execute('''SELECT bid FROM market_quotes WHERE pair=? AND at_utc>=?
                          AND at_utc<=? ORDER BY at_utc LIMIT 1''',(pair,target,target+LATER_GRACE_S)).fetchone()
                if mark is not None:
                    bid=_dec(mark[0]);entry_d=_dec(entry);fee_d=_dec(fee)
                    if bid is None or entry_d is None or fee_d is None or bid<=0 or entry_d<=0 or fee_d<0:
                        continue
                    # After account-tier taker fees and fixed 15bps per-leg
                    # slippage stress; NOT pair-preview or realized trade costs.
                    drag=fee_d+Decimal('.0015')
                    net=((bid*(1-drag))/(entry_d*(1+drag))-1)*100
                    c.execute('''UPDATE v607_strategy_trials SET outcome_state='OBSERVED',
                       exit_bid=?,after_cost_pct=? WHERE strategy=? AND pair=? AND decision_bucket=?
                       AND outcome_state='PENDING' ''',(str(bid),str(net),strategy,pair,bucket))
                    observed+=1
                elif now>target+LATER_GRACE_S:
                    c.execute('''UPDATE v607_strategy_trials SET outcome_state='MISSED_FUTURE_MARK'
                       WHERE strategy=? AND pair=? AND decision_bucket=? AND outcome_state='PENDING' ''',
                       (strategy,pair,bucket))
                    missed+=1
            # Bounded retention inside the original research store; do not touch
            # unrelated financial, forward BUY or OHLCV rows.
            c.execute('DELETE FROM v607_strategy_trials WHERE observed_at_utc<?', (int(now)-180*86400,))
        return {'observed':observed,'missing':missed}

    def scan(self,pairs,*,now=None,fee_rate=None):
        now=int(time.time() if now is None else now)
        outcomes=self.evaluate_matured(now)
        unique=list(dict.fromkeys(str(x).upper() for x in (pairs or ()) if isinstance(x,str)))[:MAX_PAIRS]
        aggregate=Counter();candidates=[];reasons=Counter();regimes=Counter()
        fee=_dec(fee_rate)
        fee_verified=fee is not None and Decimal(0)<=fee<Decimal('.05')
        with self.forward._db() as c:
            for pair in unique:
                rows=c.execute('''SELECT at_utc,bid,ask FROM market_quotes WHERE pair=? AND at_utc>=?
                   AND at_utc<=? ORDER BY at_utc DESC LIMIT 80''', (pair,now-3600,now)).fetchall()[::-1]
                info=analyze_pair(pair,rows,now=now)
                regimes[info['regime']]+=1
                if info['blocker']:reasons[info['blocker']]+=1
                for item in info['candidates']:
                    aggregate[item['strategy']]+=1
                    # The same source yields RESEARCH ONLY in BOTH AI Lab and
                    # Auto Trader. No model/GPU-only BUY and no fabricated cash.
                    candidates.append(item)
                    if not fee_verified:continue
                    latest=rows[-1] if rows else None
                    if latest is None:continue
                    ask=_dec(latest[2])
                    if ask is None or ask<=0:continue
                    bucket=now-now%900
                    c.execute('''INSERT OR IGNORE INTO v607_strategy_trials
                      (strategy,pair,observed_at_utc,decision_bucket,entry_ask,fee_taker,
                      evaluate_after,outcome_state) VALUES(?,?,?,?,?,?,?,'PENDING')''',
                      (item['strategy'],pair,int(item['observation_at_utc']),bucket,str(ask),str(fee),
                       int(now)+HORIZON_S))
            states=c.execute('''SELECT strategy,outcome_state,COUNT(*),
                     SUM(CASE WHEN CAST(after_cost_pct AS REAL)>0 THEN 1 ELSE 0 END)
                     FROM v607_strategy_trials GROUP BY strategy,outcome_state''').fetchall()
        hist={s:{'PENDING':0,'OBSERVED':0,'MISSED_FUTURE_MARK':0,'positive_after_assumed_cost':0} for s in STRATEGIES}
        for strategy,state,count,positive in states:
            if strategy in hist and state in hist[strategy]:hist[strategy][state]=int(count)
            if strategy in hist:hist[strategy]['positive_after_assumed_cost']+=int(positive or 0)
        candidates.sort(key=lambda x:(-float(x['observed_pct']),x['pair'],x['strategy']))
        return {'version':'v60.7','state':'RESEARCH_ONLY_NOT_OOS_VALIDATED',
            'studied_pairs':len(unique),'patterns':dict(aggregate),'regimes':dict(regimes),
            'rejections':dict(reasons),'candidates':candidates[:24],
            'total_candidates':len(candidates),'sampled_limit':MAX_PAIRS,
            'fee_verified':fee_verified,'future_outcomes':hist,
            'newly_matured':outcomes,'portfolio_alpha_validated':False,
            'auto_trade_eligible':0,'may_authorize_orders':False,
            'note':'Observation-only; no independent matched portfolio HOLD-vs-SWITCH OOS evidence or maker/depth fills'}


def public_summary(result):
    """Redacted status shared verbatim in all four tabs and diagnostics."""
    r=result or {}
    pats=r.get('patterns') or {}
    return ('STRATEGY RESEARCH / NO ORDERS • scanned '+str(int(r.get('studied_pairs',0)))+
            ' pairs • momentum '+str(int(pats.get('MOMENTUM_BASELINE',0)))+
            ' / range '+str(int(pats.get('RANGE_REVERSION',0)))+
            ' / breakout '+str(int(pats.get('BREAKOUT',0)))+
            ' • independent portfolio OOS NOT VERIFIED; HOLD default')


def report(result):
    """Combined diagnostics safe aggregate: no account holdings or quantities."""
    r=result or {}
    out=['V60.7 THREE-STRATEGY RESEARCH + FOUR-TAB HANDOFF',
         'Original CoinCat research algorithms; NO external bot source code copied.',
         public_summary(r), 'One canonical Coinbase REST bid/ask market DB; no second market feed.',
         'AI Lab → same shared rotation planner → SHADOW/Auto Trader → P&L diagnostics.',
         'Market conditions: '+str({k:int(v) for k,v in (r.get('regimes') or {}).items() if k in ('TRENDING','RANGING','MIXED','UNKNOWN')}),
         'Pattern count (NOT orders): '+str({k:int(v) for k,v in (r.get('patterns') or {}).items() if k in STRATEGIES}),
         'Rejected pattern conditions: '+str({k:int(v) for k,v in (r.get('rejections') or {}).items() if k in ('NO_REAL_BID_ASK','INSUFFICIENT_MATURE_FRESH_QUOTES','SPREAD_GT_25_BPS','BAD_MID','NO_STRATEGY_PATTERN')}),
         'Future observed/missing (correlated across pairs and strategies; not P&L):']
    for s in STRATEGIES:
        h=(r.get('future_outcomes') or {}).get(s) or {}
        out.append('  '+s+': observed='+str(int(h.get('OBSERVED',0)))+
                   ' pending='+str(int(h.get('PENDING',0)))+
                   ' missed='+str(int(h.get('MISSED_FUTURE_MARK',0)))+
                   ' positive_after_assumed_cost='+str(int(h.get('positive_after_assumed_cost',0))))
    out.extend(['Cost marks use recorded account tier + assumed 15bps slippage/leg, NOT verified fills.',
                'No lookahead, no invented future marks; no live orders, no strategy authorization.',
                'Automatic unattended LIVE operation: NOT ENABLED; separate future certification and typed ARM required.'])
    return '\n'.join(out)
