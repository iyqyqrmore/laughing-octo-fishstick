"""CoinCat v50: evidence-gated *proposals* for larger LIVE trading budgets.

No autonomous capacity increase: a user must explicitly approve the exact next
stage while DISARMED; arming live trading is a separate typed confirmation.
Only reconciled Coinbase SELL order exits of verified bot-bought inventory are
counted. Paper trades, historic candles, open/unrealized P&L, enrollment-price
snapshots, and AI/GPU predictions never qualify this capacity gate.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime,timezone
import time
from coincat_live import LiveBlocked, D, sql, PENDING

@dataclass(frozen=True)
class CapacityTier:
    order: Decimal
    daily: Decimal
    exposure: Decimal
    orders_day: int

TIERS=(
    CapacityTier(D('10'),D('40'),D('50'),12),
    CapacityTier(D('12'),D('48'),D('60'),14),
    CapacityTier(D('15'),D('60'),D('75'),16),
    CapacityTier(D('20'),D('80'),D('100'),20),
)
# Sample count, elapsed calendar days, distinct UTC trading days, net gain,
# observed directional label count; increase requirements with higher stages.
GATES={
    1:(30,14,7,D('5'),60),
    2:(65,28,14,D('12'),160),
    3:(110,45,24,D('25'),350),
}

def current_stage(ledger):
    try: value=int(ledger.setting('capacity_stage','0'))
    except (TypeError,ValueError):raise LiveBlocked('Invalid saved capacity authorization')
    if value not in range(len(TIERS)):raise LiveBlocked('Capacity authorization stage invalid')
    return value

def limits_for(ledger):return TIERS[current_stage(ledger)]

def validate_limits(ledger,order,daily,exposure,attempts,*,portfolio_cap=None):
    # Explicit per-session portfolio authorization is an alternative to the
    # legacy fixed pilot tiers. Never a silent/automatic stage increase.
    if portfolio_cap is not None:
        from coincat_portfolio_budget import validate_manual_budget
        validate_manual_budget(order,daily,exposure,attempts,portfolio_cap)
        return portfolio_cap
    t=limits_for(ledger)
    if D(order)<=0 or D(daily)<=0 or D(exposure)<=0 or int(attempts)<=0:
        raise LiveBlocked('Trading budgets must be positive')
    if D(order)>t.order or D(daily)>t.daily or D(exposure)>t.exposure or int(attempts)>t.orders_day:
        raise LiveBlocked(f'CAPACITY STAGE {current_stage(ledger)} approved maxima: '
                          f'${t.order}/order, ${t.daily} buys/day, ${t.exposure} added exposure, '
                          f'{t.orders_day} order attempts/day. Separate approval required to raise.')
    return t

def _closed_bot_sell_orders(ledger):
    """Group actual filled SELL executions into independent order-level outcomes.

    One Coinbase market order may fill in multiple trades. Partial/unmatched
    entries and user holdings marked at enrollment are ineligible evidence.
    """
    with sql(ledger.path) as c:
        rows=c.execute('''
          SELECT o.cid,o.order_id,MIN(f.at_utc) when_utc,
                 SUM(CAST(f.performance_realized_quote AS REAL)) pnl,
                 COUNT(*) n,
                 SUM(CASE WHEN f.performance_realized_quote IS NOT NULL
                          AND f.basis_provenance='BOT_FILL' THEN 1 ELSE 0 END) verified
            FROM orders o JOIN fills f ON f.cid=o.cid AND f.order_id=o.order_id
           WHERE o.side='SELL' AND o.state='FILLED' AND f.side='SELL' AND o.purpose='AUTOTRADE'
           GROUP BY o.cid,o.order_id
        ''').fetchall()
    return sorted([(int(r['when_utc']),D(str(r['pnl']))) for r in rows
                   if int(r['n'])>0 and int(r['n'])==int(r['verified'])],key=lambda x:x[0])

def evaluate(ledger,verified_forward_labels=0,now=None):
    """Determine if a single next-stage *proposal* is supported; no mutation."""
    now=int(time.time() if now is None else now)
    stage=current_stage(ledger)
    next_stage=stage+1
    output=dict(ready=False,stage=stage,next_stage=next_stage if next_stage<len(TIERS) else None,
                reason='',cycles=0,win_pct=0.0,net=0.0,profit_factor=0.0,
                drawdown=0.0,age_days=0,distinct_days=0,forward_labels=int(verified_forward_labels))
    if next_stage>=len(TIERS):
        output['reason']='Maximum optional pilot capacity stage already approved.';return output
    if ledger.pending():
        output['reason']='Unresolved Coinbase order. Capacity review paused until reconciled.';return output
    if ledger.setting('halted','0')=='1':
        output['reason']='Emergency stop latched. Capacity review suspended.';return output
    # Old successes cannot justify a new increase after a long offline gap.
    rows=[(t,p) for t,p in _closed_bot_sell_orders(ledger) if now-90*86400<=t<=now]
    n=len(rows);output['cycles']=n
    if rows:
        output['age_days']=(rows[-1][0]-rows[0][0])//86400
        output['distinct_days']=len({datetime.fromtimestamp(t,timezone.utc).date() for t,p in rows})
        wins=sum(p>0 for t,p in rows)
        output['win_pct']=float(D(wins)*100/D(n))
        gp=sum((p for t,p in rows if p>0),D('0'))
        gl=-sum((p for t,p in rows if p<0),D('0'))
        total=gp-gl;output['net']=float(total)
        output['profit_factor']=float(gp/gl) if gl else (float('inf') if gp>0 else 0.0)
        peak=D('0');cumulative=D('0');max_dd=D('0')
        for t,p in rows:
            cumulative+=p;peak=max(peak,cumulative)
            max_dd=max(max_dd,peak-cumulative)
        output['drawdown']=float(max_dd)
    req_n,req_days,req_sessions,req_net,req_labels=GATES[next_stage]
    conditions=[
        (n>=req_n,f'Need {req_n} verified bot-owned completed SELL orders; {n} recorded'),
        (output['age_days']>=req_days,f'Need {req_days} days of completed-trade span; {output["age_days"]} recorded'),
        (output['distinct_days']>=req_sessions,f'Need trades on {req_sessions} distinct UTC days; {output["distinct_days"]} recorded'),
        (int(verified_forward_labels)>=req_labels,f'Need {req_labels} genuinely observed forward labels; {verified_forward_labels} recorded'),
        (output['net']>=float(req_net),f'Net verified trading profit ${output["net"]:.2f} below ${req_net} minimum'),
        (output['profit_factor']>=1.5,f'Profit factor {output["profit_factor"]:.2f} below 1.50'),
        # Limit aggregate losing streaks even when a few large wins inflated P&L.
        (output['drawdown']<=max(2.,output['net']*.35),
         f'Realized peak-to-trough drawdown ${output["drawdown"]:.2f} too large for this stage'),
        (sum((p for t,p in rows[-10:]),D('0'))>0,
         'Most recent 10 verified completed sells are not net profitable'),
        (bool(rows) and now-rows[-1][0]<=7*86400,
         'No verified bot-owned SELL completed in the past 7 days'),
    ]
    failing=[explanation for passed,explanation in conditions if not passed]
    output['ready']=not failing
    output['reason']=('Evidence threshold passed; USER APPROVAL required. No increase has occurred.'
                       if not failing else ' • '.join(failing[:3]))
    return output

def approve_next_stage(ledger,stage,authorization,*,forward_labels=0,now=None):
    """Atomic, audited authorization; caller must disarm before invocation.

    Approval never changes the order broker instance's armed flag or places orders.
    Requires recalculating evidence immediately before authorization.
    """
    now=int(time.time() if now is None else now)
    stage=int(stage)
    if authorization!=f'APPROVE CAPACITY {stage}':
        raise LiveBlocked(f'Type exactly APPROVE CAPACITY {stage}')
    if stage!=current_stage(ledger)+1:
        raise LiveBlocked('Only the immediately next capacity stage can be approved')
    report=evaluate(ledger,forward_labels,now)
    if not report['ready'] or report['next_stage']!=stage:
        raise LiveBlocked('Trading capacity not ready: '+report['reason'])
    with sql(ledger.path) as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM orders WHERE state IN (%s) LIMIT 1' % ','.join('?'*len(PENDING)),tuple(PENDING)).fetchone():
            raise LiveBlocked('Outstanding order prevents capacity approval')
        halt=c.execute("SELECT value FROM risk WHERE key='halted'").fetchone()
        if halt and halt['value']=='1':
            raise LiveBlocked('Emergency stop must be reviewed before capacity approval')
        row=c.execute("SELECT value FROM risk WHERE key='capacity_stage'").fetchone()
        stored=int(row['value']) if row else 0
        if stored!=stage-1:
            raise LiveBlocked('Capacity stage changed; review proposal again')
        c.execute("INSERT INTO risk(key,value) VALUES('capacity_stage',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(stage),))
        c.execute('INSERT INTO events(at_utc,event,detail) VALUES(?,?,?)',
            (now,'USER_CAPACITY_STAGE_APPROVED',f'Stage {stage}; {report["cycles"]} verified cycles; net ${report["net"]:.2f}; forward labels {forward_labels}; explicit typed approval'))
    return TIERS[stage]
