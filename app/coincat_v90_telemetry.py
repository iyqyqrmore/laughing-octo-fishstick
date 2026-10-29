"""Bounded, quantity-free RAM measurements of existing research work.

No pricing, path selection, market requests, financial storage or order APIs.
Coverage is scoped to current eligible urgent directions, independently of ARM.
"""
from collections import Counter, deque
from datetime import datetime, timezone
import math
from threading import RLock
from uuid import uuid4


def utc(stamp):
    return datetime.fromtimestamp(float(stamp), timezone.utc).isoformat(timespec='milliseconds')


class ResearchCycles:
    def __init__(self):
        self.run_id=uuid4().hex[:12]
        self.sequence=0

    def begin(self, now):
        self.sequence+=1
        return {'id':f'{self.run_id}:urgent:{self.sequence}', 'started_at':float(now),
                'scope':'URGENT_DISCOVERY'}


def direction(idea):
    steps=idea.get('shadow_fifo_steps') or ()
    return (steps[0]['pair'],steps[0]['side']) if len(steps)==1 else None


class DirectionCoverage:
    """One row per currently eligible product/side; at most two per product.

    Removal discards its row. Re-entry starts a new eligibility interval; no
    old completion is presented as evidence for newly approved funding.
    Window events are bounded and any truncation is explicitly reported.
    """
    def __init__(self, *, window_s=60, max_events=8192):
        self.window_s=window_s
        self.max_events=max_events
        self.rows={}
        self.events=deque()
        self.dropped_events=0
        self.last_dropped_at=None
        self.scope_at=None
        self.last_cycle=None
        self._lock=RLock()

    def select(self, eligible, selected, *, now, cycle_id):
        with self._lock:
            keys={(p,s) for p,s,*_ in eligible}
            self.rows={k:v for k,v in self.rows.items() if k in keys}
            for key in keys:
                self.rows.setdefault(key,{'eligible_since':now, 'last_selected_at':None,
                    'last_evaluated_at':None,'last_complete_at':None,'latest_reason':'NEVER_SELECTED'})
            # Removed/re-entered directions must not inherit window events.
            self.events=deque(e for e in self.events if e[1] in keys)
            for p,s,*_ in selected:
                row=self.rows[(p,s)]
                row['last_selected_at']=now
                row['latest_reason']='AWAITING_EVALUATION'
            self.scope_at=now
            self.last_cycle=cycle_id

    def record(self, evaluations, selected, *, now, reason):
        with self._lock:
            reached=set()
            for item in evaluations:
                key=tuple(item['direction'])
                if key not in self.rows:continue
                reached.add(key)
                row=self.rows[key]
                row['last_evaluated_at']=item['evaluated_at']
                row['latest_reason']=','.join(item['blockers']) or item['state']
                complete=item['priced_sizes']>0
                if complete:row['last_complete_at']=item['evaluated_at']
                self.events.append((item['evaluated_at'],key,complete))
            for p,s,*_ in selected:
                key=(p,s)
                if key in self.rows and key not in reached:
                    self.rows[key]['latest_reason']='NO_PRICING_EVALUATION:'+reason
            self._prune(now)

    def _prune(self, now):
        # Event timestamps can differ slightly across sizes; filter all rows.
        self.events=deque(e for e in self.events if now-self.window_s<=e[0]<=now)
        while len(self.events)>self.max_events:
            self.last_dropped_at=self.events.popleft()[0]
            self.dropped_events+=1

    def summary(self, *, now):
        with self._lock:
            self._prune(now)
            rows=list(self.rows.values())
            complete={key for at,key,ok in self.events if ok}
            evaluated={key for at,key,ok in self.events}
            ages=[now-r['last_complete_at'] for r in rows if r['last_complete_at'] is not None]
            recent=sum(0<=age<=self.window_s for age in ages)
            never=sum(r['last_complete_at'] is None for r in rows)
            quotes={}
            for (pair,side),row in sorted(self.rows.items()):
                quote=pair.split('-')[1]
                group=quotes.setdefault(quote,{'eligible':0,'never_complete':0,'recent_complete':0})
                group['eligible']+=1
                stamp=row['last_complete_at']
                if stamp is None:group['never_complete']+=1
                elif 0<=now-stamp<=self.window_s:group['recent_complete']+=1
            return {'scope':'URGENT_ELIGIBILITY_AT_SCOPE_TIMESTAMP_RAM_ONLY',
                'age_basis':'LOCAL_MODEL_EVALUATION',
                'as_of':now,'eligibility_as_of':self.scope_at,
                'eligibility_age_s':None if self.scope_at is None else round(now-self.scope_at,3),
                'cycle_id':self.last_cycle,
                'window_s':self.window_s,'eligible_directions':len(rows),
                'never_selected':sum(r['last_selected_at'] is None for r in rows),
                'never_evaluated':sum(r['last_evaluated_at'] is None for r in rows),
                'never_complete':never,'recent_complete':recent,
                'overdue_complete':len(rows)-never-recent,
                'oldest_complete_age_s':round(max(ages),3) if ages else None,
                'distinct_evaluated_in_window':len(evaluated),
                'distinct_complete_in_window':len(complete),
                'evaluation_events_in_window':len(self.events),
                'complete_events_in_window':sum(ok for at,key,ok in self.events),
                'window_truncated':self.last_dropped_at is not None and now-self.last_dropped_at<=self.window_s,
                'dropped_window_events_total':self.dropped_events,
                'latest_reason_direction_counts':dict(Counter(r['latest_reason'] for r in rows)),
                'by_market_quote':quotes}

    def ages(self, *, now):
        """Local per-direction inspection; shared reports use aggregate summary."""
        with self._lock:
            return {key:{**row, 'last_complete_age_s':
                None if row['last_complete_at'] is None else now-row['last_complete_at']}
                for key,row in self.rows.items()}


def age_detail(clock, stamp, limit):
    try:
        value=float(stamp)
        if not value or not math.isfinite(value):raise ValueError()
        age=float(clock)-value
        return {'age_s':round(age,3),'limit_s':limit,
                'state':'CLOCK_CONFLICT' if age<0 else 'FRESH' if age<=limit else 'STALE'}
    except (TypeError, ValueError, OverflowError):
        return {'age_s':None,'limit_s':limit,'state':'UNOBSERVED'}


def coverage_details(tracker, *, now):
    if tracker is None:return 'Direction coverage has not been observed yet.'
    rows=tracker.ages(now=now)
    lines=['DIRECTION COVERAGE — local view; snapshot UTC '+utc(now),
        'Last evaluated means the strict pricing evaluator ran. Complete means modeled W/L pricing, regardless of sign.',
        'A complete model does not verify exchange time, depth, fees or execution.',
        'Product / direction | selected age | evaluated age | complete-frame age | latest outcome']
    def age(stamp):
        if stamp is None:return 'never'
        elapsed=now-stamp
        return 'clock conflict' if elapsed<0 else f'{elapsed:.1f}s'
    for (pair,side),row in sorted(rows.items()):
        lines.append(f"{pair} / {side} | {age(row['last_selected_at'])} | "
            f"{age(row['last_evaluated_at'])} | {age(row['last_complete_at'])} | {row['latest_reason']}")
    if not rows:lines.append('No eligible directions in the last observed scope.')
    return '\n'.join(lines)
