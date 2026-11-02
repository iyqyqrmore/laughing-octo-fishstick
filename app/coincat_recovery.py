"""Sanitized read-only failure attribution and bounded monotonic recovery."""
from collections import Counter
from email.utils import parsedate_to_datetime
import math
import sqlite3
import time
import requests

STAGES=frozenset({'PERMISSIONS','BALANCES','CATALOG','FEE_TIER','PUBLIC_QUOTE',
                  'LOCAL_PUBLIC_QUOTE_STORE','UNKNOWN'})
BACKOFF=(10,20,40,80,160)


def retry_after(raw,*,wall=None):
    try:value=float(raw)
    except (TypeError,ValueError):
        try:value=parsedate_to_datetime(raw).timestamp()-(time.time() if wall is None else wall)
        except (TypeError,ValueError,OverflowError):return 0.0
    return max(0,value) if math.isfinite(value) else 0.0


def failure(exc,stage='UNKNOWN',*,minimum_delay=0):
    if isinstance(exc,ReadFailure):return dict(exc.detail)
    stage=stage if stage in STAGES else 'UNKNOWN'
    response=getattr(exc,'response',None)
    status=getattr(response,'status_code',None)
    if not isinstance(status,int) or not 400<=status<=599:status=None
    headers=getattr(response,'headers',{}) or {}
    delay=max(float(minimum_delay),retry_after(headers.get('Retry-After')))
    transient=False;category='UNEXPECTED_ERROR';name='UnexpectedError'
    if isinstance(exc,requests.exceptions.Timeout):
        name=type(exc).__name__ if type(exc).__name__ in ('ReadTimeout','ConnectTimeout') else 'Timeout'
        category='READ_TIMEOUT';transient=True
    elif isinstance(exc,requests.exceptions.SSLError):
        name='SSLError';category='TLS_ERROR'
    elif isinstance(exc,requests.exceptions.ConnectionError):
        name='ConnectionError';category='CONNECTION_ERROR';transient=True
    elif isinstance(exc,requests.exceptions.HTTPError):
        name='HTTPError';category='HTTP_'+str(status) if status else 'HTTP_ERROR'
        transient=status==429 or (status is not None and 500<=status<=599)
    elif isinstance(exc,sqlite3.Error):name='SQLiteError';category='LOCAL_STATE_ERROR'
    elif isinstance(exc,(ValueError,ArithmeticError,TypeError,KeyError)):
        name='ValueError';category='INVALID_DATA_OR_SETTINGS'
    elif type(exc).__name__=='LiveBlocked':name='LiveBlocked';category='PERMISSION_OR_DATA_REJECTED'
    return dict(stage=stage,error_class=name,status=status,category=category,
                transient=transient,retry_after_s=delay)


class ReadFailure(RuntimeError):
    def __init__(self,detail):
        self.detail=dict(detail)
        super().__init__(detail['stage']+':'+detail['category'])


def read_call(stage,call,*args,**kwargs):
    try:return call(*args,**kwargs)
    except ReadFailure:raise
    except Exception as exc:raise ReadFailure(failure(exc,stage)) from None


def public_quote_failure(code,*,minimum_delay=0):
    code=str(code)
    status=None;category='PUBLIC_QUOTE_ERROR';transient=False;name='QuoteUnavailable'
    if code.startswith('HTTP_'):
        try:status=int(code.split('_')[1])
        except (ValueError,IndexError):pass
        if status is not None and 400<=status<=599:
            category='HTTP_'+str(status);transient=status==429 or status>=500;name='HTTPError'
        else:status=None
    elif code in ('ConnectionError','CONNECTION_ERROR'):
        category='CONNECTION_ERROR';name='ConnectionError';transient=True
    elif code in ('Timeout','ReadTimeout','ConnectTimeout','SCOUT_DEADLINE','SLOW_OR_LATE_QUOTE'):
        category='READ_TIMEOUT';name='Timeout';transient=True
    elif code in ('GET_RATE_BUDGET_DEFERRED','PREVIOUS_GETS_IN_FLIGHT','GET_DEFERRED'):
        category='GET_DEFERRED';name='QuoteDeferred';transient=True
    return dict(stage='PUBLIC_QUOTE',error_class=name,status=status,category=category,
                transient=transient,retry_after_s=max(0,float(minimum_delay)))


class Recovery:
    def __init__(self,clock=None):
        self.clock=time.monotonic if clock is None else clock
        self.state='STOPPED';self.attempt=0;self.due_at=None;self.last_failure=None
        self.interruptions=0;self.recovered_periods=0;self.retry_attempts=0
        self.connect_interruptions=0;self.connection_recoveries=0;self.outage_is_scan=True
        self.failures=Counter();self.outage=False;self.last_successful_scan_at=None

    def start(self):
        self.state='RUNNING';self.attempt=0;self.due_at=None

    def stop(self):
        self.state='STOPPED';self.due_at=None;self.attempt=0

    def failed(self,detail,*,now=None,operation='scan'):
        # Only allow controlled classifier fields into public state.
        self.last_failure={k:detail.get(k) for k in
            ('stage','error_class','status','category','transient','retry_after_s')}
        self.last_failure['at']=time.time() if now is None else now
        self.last_failure['operation']='connect' if operation=='connect' else 'scan'
        self.failures[str(detail['stage'])+':'+str(detail['category'])]+=1
        if not self.outage:
            self.outage=True;self.outage_is_scan=operation!='connect'
            if self.outage_is_scan:self.interruptions+=1
            else:self.connect_interruptions+=1
        if detail['transient'] and self.attempt<len(BACKOFF):
            self.state='RETRYING'
            delay=max(BACKOFF[self.attempt],detail.get('retry_after_s',0))
            self.due_at=self.clock()+delay
        else:self.state='PAUSED_NEEDS_ATTENTION';self.due_at=None
        return self.state

    def begin_retry(self):
        if self.state!='RETRYING' or self.due_at is None or self.clock()<self.due_at:return False
        self.attempt+=1;self.retry_attempts+=1;self.due_at=None
        return True

    def successful(self,at):
        if self.outage:
            if self.outage_is_scan:self.recovered_periods+=1
            else:self.connection_recoveries+=1
            self.outage=False
        self.state='RUNNING';self.attempt=0;self.due_at=None;self.last_successful_scan_at=at

    def authenticated(self):
        if self.outage and not self.outage_is_scan:self.connection_recoveries+=1;self.outage=False
        self.stop()

    def diagnostics(self):
        return dict(connection_state=self.state,retry_attempt=self.attempt,
            retry_limit=len(BACKOFF),retry_attempts_total=self.retry_attempts,
            retry_in_s=None if self.due_at is None else max(0,self.due_at-self.clock()),
            last_failure=self.last_failure,scan_interruptions=self.interruptions,
            recovered_periods=self.recovered_periods,failure_counts=dict(self.failures),
            connect_interruptions=self.connect_interruptions,connection_recoveries=self.connection_recoveries,
            last_successful_scan_at=self.last_successful_scan_at)
