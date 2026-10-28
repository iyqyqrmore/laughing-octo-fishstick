"""Bounded public GET transport; no credentials, broker, or order API.

One process-wide ticker budget, thread-local connection pools, no sleep/retry on
429. Retry-After postpones later GETs. A late result is never written by the
collector. At most one unfinished scout batch survives a collection deadline.
"""
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from threading import Lock, local
import math
import time

import requests


class QuoteDeferred(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class GetBudget:
    def __init__(self, interval=.2, clock=time.monotonic):
        self.interval, self.clock = interval, clock
        self.lock = Lock()
        self.next_at = self.blocked_until = 0.0

    def acquire(self, deadline, sleep=time.sleep):
        with self.lock:
            now = self.clock()
            at = max(now, self.next_at, self.blocked_until)
            if at >= deadline:
                raise QuoteDeferred('GET_RATE_BUDGET_DEFERRED')
            self.next_at = at+self.interval
        if at > now:
            sleep(at-now)
        if self.clock() >= deadline:
            raise QuoteDeferred('SCOUT_DEADLINE')

    def postpone(self, retry_after, wall=time.time):
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(retry_after)
                delay = date.timestamp()-wall()
            except (TypeError, ValueError, OverflowError):
                delay = 2.0
        if not math.isfinite(delay): delay = 2.0
        # Never shorten a server-requested wait. Very long waits require review.
        with self.lock:
            self.blocked_until = max(self.blocked_until, self.clock()+max(1.0, delay))


BUDGET = GetBudget()
_LOCAL = local()


def pooled_get(*args, **kwargs):
    if not hasattr(_LOCAL, 'session'):
        _LOCAL.session = requests.Session()  # normal proxy + TLS verification
    return _LOCAL.session.get(*args, **kwargs)


@dataclass(frozen=True)
class QuoteSnapshot:
    pair: str
    bid: object
    ask: object
    observed_at: float
    received_at: float
    request_ms: float
    source: str = 'COINBASE_PUBLIC_REST_BEST_BID_ASK'
    exchange_timestamp: object = None

    def book(self):
        return self.bid, self.ask, self.observed_at


def fetch_snapshot(pair, *, deadline=None, get=None, budget=None):
    from coincat_live_quotes import TICKER, parse_ticker
    from coincat_cross_quote import split_spot
    split_spot(pair)
    budget = BUDGET if budget is None else budget
    deadline = time.monotonic()+4 if deadline is None else deadline
    budget.acquire(deadline)
    started, wall = time.monotonic(), time.time()
    remaining = deadline-started
    if remaining <= 0: raise QuoteDeferred('SCOUT_DEADLINE')
    response = (pooled_get if get is None else get)(
        TICKER.format(pair=pair), params={'limit': 1},
        timeout=(min(1.5, remaining), min(2.0, remaining)),
        headers={'Accept': 'application/json'})
    if response.status_code == 429:
        budget.postpone(response.headers.get('Retry-After'))
        raise QuoteDeferred('HTTP_429_RETRY_AFTER')
    response.raise_for_status()
    bid, ask = parse_ticker(response.json())
    elapsed, received = time.monotonic()-started, time.time()
    if time.monotonic() > deadline or elapsed > 3.0:
        raise QuoteDeferred('SLOW_OR_LATE_QUOTE')
    if abs((received-wall)-elapsed) > 1:
        raise QuoteDeferred('CLOCK_CHANGED_DURING_GET')
    # Ticker does not establish exchange quote-event time. Use request start,
    # not receipt, and explicitly retain that limitation in diagnostics.
    return QuoteSnapshot(pair, bid, ask, wall, received, elapsed*1000)


class ScoutCollector:
    def __init__(self):
        self.lock = Lock()
        self.inflight = set()

    def collect(self, pairs, *, fetch=fetch_snapshot, seconds=6, clock=time.monotonic):
        start = clock()
        with self.lock:
            self.inflight = {f for f in self.inflight if not f.done()}
            if self.inflight:
                return {}, {'PREVIOUS_GETS_IN_FLIGHT': len(self.inflight)}, 0
            pool = ThreadPoolExecutor(max_workers=4)
            jobs = {pool.submit(fetch, p, deadline=start+seconds): p for p in pairs}
            self.inflight = set(jobs)
        try:
            done, pending = wait(jobs, timeout=max(0, start+seconds-clock()))
            snapshots, errors = {}, {}
            for future in done:
                pair = jobs[future]
                try:
                    snapshot = future.result()
                    snapshots[pair] = snapshot
                except Exception as exc:
                    reason = getattr(exc, 'reason', type(exc).__name__)
                    errors[reason] = errors.get(reason, 0)+1
            if pending: errors['SCOUT_DEADLINE'] = len(pending)
            for future in pending: future.cancel()
            return snapshots, errors, round((clock()-start)*1000, 2)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


SCOUT = ScoutCollector()


def percentiles(values):
    values = sorted(values)
    if not values: return {}
    return {f'p{q}': round(values[max(0, math.ceil(q/100*len(values))-1)], 2)
            for q in (50, 95, 99)}
