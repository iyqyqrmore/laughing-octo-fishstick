"""Opt-in 168-hour native-price assumed trial, separate from earlier evidence."""
from copy import deepcopy
from pathlib import Path
import threading
import time
import sqlite3

from coincat_assumed_math import initial_state,observation_time,plan,fill_record,apply_record,marked_performance
from coincat_assumed_store import AssumedStore,sizing
from coincat_assumed_public import project
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_watchlist import WATCH_PAIRS
from coincat_shadow_source import frame_quality
from coincat_trial_clock import begin_run,advance,prime_quality,end_run,progress,NS
from coincat_assumed_math import fee_rate

class AssumedTrader:
    def __init__(self,path,*,clock=time.time,monotonic_ns=time.monotonic_ns):
        self.path=Path(path);self.clock=clock;self.monotonic_ns=monotonic_ns;self.lease=None;self.stop_flag=threading.Event();self.stop_flag.set()
        self.store=None;self.load_error=False;self.rows=[];self.orders=[];self.last_frame=None;self.reason='PRESS_START_FOR_ASSUMED_FILLS';self.buy_price='ASK'
        self.pending_sizing={p:0 for p in WATCH_PAIRS}
        if self.path.exists():
            try:
                self.store=AssumedStore(self.path);self.orders=self.store.recent();self.buy_price=self.store.state()['buy_price'];self.pending_sizing=self.store.state()['sizing']
                if self.store.clock['phase']!='COMPLETE':
                    begin_run(self.store.clock,wall=self.clock(),mono_ns=self.monotonic_ns());self.store.flush_clock()
                    if self.store.clock['wanted']:self.stop_flag.clear()
                self.reason='SAVED_TRIAL_WAITING_FOR_FRESH_INPUTS_NO_OFFLINE_FILLS' if self.running else 'SAVED_TRIAL_PAUSED_OR_COMPLETE'
            except (ValueError,OSError,TypeError,KeyError,ArithmeticError,sqlite3.Error):self.store=None;self.load_error=True;self.reason='SAVED_SIMULATION_REVIEW_REQUIRED_NO_RESET'
        self._view={};self.update_view()
    @property
    def running(self):return not self.stop_flag.is_set()
    def start(self,buy_price=None):
        if self.load_error:raise BetaBlocked('SAVED_SIMULATION_REVIEW_REQUIRED_NO_RESET')
        buy_price=self.buy_price if buy_price is None else buy_price
        if buy_price not in ('ASK','BID'):raise BetaBlocked('ASSUMED_BUY_PRICE_MUST_BE_ASK_OR_BID')
        if self.running and self.buy_price!=buy_price:raise BetaBlocked('PAUSE_BEFORE_CHANGING_UNSTARTED_BUY_PRICE')
        if self.store is not None and self.store.state()['buy_price']!=buy_price:raise BetaBlocked('SAVED_SIMULATION_BUY_PRICE_FROZEN')
        if self.store is not None:
            with self.store.lock:
                if self.store.clock['phase']=='COMPLETE':raise BetaBlocked('COMPLETED_ASSUMED_TRIAL_FROZEN')
                self.store.clock.update(wanted=True,phase='RECOVERING',previous_valid=False);self.store.flush_clock()
        self.buy_price=buy_price
        self.reason='WAIT_FOR_FRESH_NATIVE_BOOKS';self.stop_flag.clear();self.lease=None;self.update_view()
    def pause(self):
        self.stop_flag.set()
        if self.store is not None:
            self.heartbeat()
            with self.store.lock:
                if self.store.clock['phase']!='COMPLETE':self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False)
                self.store.flush_clock()
        self.lease=None
    def configure(self,values):
        values=sizing(values)
        if self.store is not None:self.store.configure(values)
        self.pending_sizing=values;self.update_view()
    def heartbeat(self,*,persist=False):
        if self.store is None or self.load_error:return
        with self.store.lock:
            c=self.store.clock;mono=self.monotonic_ns();coverage=0;valid=False
            if self.lease is not None and 0<=mono-self.lease['mono']<=25*NS and 0<=self.clock()-self.lease['wall']<=25 and self.clock()<=self.lease['valid_until']:
                coverage=self.lease['coverage'];valid=self.lease['valid']
            advance(c,wall=self.clock(),mono_ns=mono,valid=valid,coverage=coverage,run_id=c['run_id'])
            if c['phase']=='REVIEW_REQUIRED':
                self.stop_flag.set();self.reason='ASSUMED_CLOCK_REVIEW_REQUIRED';self.store.flush_clock();self.load_error=True;self.update_view();return
            if c['phase']=='COMPLETE':
                self.stop_flag.set();self.reason='168_VALID_HOURS_COMPLETE_ASSUMED_FILLS_UNPROVEN'
                if self.store.completion is None:
                    self.store.finish(dict(classification='ASSUMED_TRIAL_NOT_EXECUTION_OR_PROFIT_EVIDENCE',
                        simulation=self.state(),progress=self.progress(),performance=(self._view or {}).get('performance')))
                self.update_view()
            elif persist:self.store.flush_clock()
    def shutdown(self):
        self.stop_flag.set()
        if self.store is None:return
        self.heartbeat()
        with self.store.lock:end_run(self.store.clock,wall=self.clock());self.store.flush_clock()
        self.lease=None
    def progress(self):return None if self.store is None or self.load_error else progress(self.store.clock,self.clock())
    def observation_gap(self):
        if self.load_error:return
        self.heartbeat();self.lease=None
        if self.store is not None:
            with self.store.lock:prime_quality(self.store.clock,valid=False,coverage=0)
        self.last_frame=None;self.reason='NATIVE_FEED_UNAVAILABLE_WAITING_FOR_FRESH_GETS'
        self.rows=[dict(pair=p,state='WAITING',reason=self.reason) for p in WATCH_PAIRS];self.update_view()
    def state(self):return None if self.store is None else self.store.state()
    def update_view(self):
        state=self.state()
        self._view=dict(state=state,rows=deepcopy(self.rows),orders=deepcopy(self.orders),reason=self.reason,
            performance=(self.store.completion or {}).get('performance') if self.store is not None and self.store.clock['phase']=='COMPLETE' else
                None if state is None or self.last_frame is None else marked_performance(state,self.last_frame,self.clock()))
    def view(self):return deepcopy(self._view)
    def public(self):
        s=self._view.get('state');at=None if self.last_frame is None else self.last_frame.get('at')
        phase='REVIEW_REQUIRED' if self.load_error else 'PAUSED' if s is not None and not self.running else 'OFF' if not self.running else 'WAITING'
        if self.store is not None and self.store.clock['phase']=='COMPLETE':phase='COMPLETE'
        if self.running and s is not None and at is not None and 0<=self.clock()-at<=30:
            phase='RUNNING' if any(r.get('state')=='ASSUMED_FILLED' for r in self.rows) else 'WAITING'
        p=self.progress()
        return project(dict(state=phase,valid_seconds=0 if p is None else int(p['valid_seconds']),restart_count=0 if p is None else p['restart_count'],
            **({k:s[k] for k in ('waves','orders','buys','sells','maker_orders','taker_orders')} if s else {})))
    @native_math
    def review(self,frame):
        if not self.running:return
        try:
            observation_time(frame,self.clock())
            seed=initial_state(frame,self.clock(),self.buy_price) if self.store is None else None
            if seed is not None:seed['sizing']=sizing(self.pending_sizing)
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            self.reason=str(exc) if isinstance(exc,BetaBlocked) else 'SEED_VALUATION_OR_NATIVE_INPUT_UNAVAILABLE'
            self.rows=[dict(pair=p,state='WAITING',reason=self.reason) for p in WATCH_PAIRS];self.update_view();return
        if self.store is None:
            try:
                self.store=AssumedStore(self.path,initial=seed)
                begin_run(self.store.clock,wall=self.clock(),mono_ns=self.monotonic_ns());self.store.flush_clock()
            except BaseException:
                self.stop_flag.set();self.load_error=True;self.reason='SIMULATION_JOURNAL_REVIEW_REQUIRED';self.update_view();raise
        self.heartbeat()
        if not self.running:return
        state=self.state()
        if ((state['last_at'] is not None and frame['at']<=state['last_at']) or
                self.last_frame is not None and frame['at']<=self.last_frame['at']):
            self.reason='WAIT_FOR_NEW_OBSERVATION';self.update_view();return
        valid,coverage=frame_quality(frame)
        try:
            fee_rate(frame,'MAKER')
            if self.buy_price=='ASK':fee_rate(frame,'TAKER')
            if any(not 0<=self.clock()-b['at']<=30 for b in frame['books'].values()):valid=False
        except (ValueError,TypeError,KeyError,ArithmeticError):valid=False
        expires=min((b['at']+30 for b in frame.get('books',{}).values()),default=self.clock())
        self.lease=dict(mono=self.monotonic_ns(),wall=self.clock(),valid=valid,coverage=coverage,valid_until=expires)
        with self.store.lock:prime_quality(self.store.clock,valid=valid,coverage=coverage)
        self.last_frame=deepcopy(frame)
        records=[];rows=[];working=deepcopy(state)
        for pair in WATCH_PAIRS:
            previous=working['pairs'][pair];side=previous['next_side']
            row=dict(pair=pair,side=side,state='WAITING',reason='NATIVE_INPUT_UNAVAILABLE')
            try:
                ticket=plan(pair,side,frame,self.buy_price,wallet=working['wallet'],percent=state['sizing'][pair],settings_version=state['settings_version'])
                if not 0<=self.clock()-ticket['book_at']<=30:raise BetaBlocked('NATIVE_BOOK_OLDER_THAN_30_SECONDS')
                row.update(ticket)
                record=fill_record(ticket,state['waves']+1);apply_record(working,record)
                records.append(record);row.update(state='ASSUMED_FILLED',reason='ASSUMED_AT_BOOK_NOT_FILL_EVIDENCE')
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                row['reason']=str(exc) if isinstance(exc,BetaBlocked) else 'NATIVE_RULE_BOOK_OR_FEE_UNAVAILABLE'
            rows.append(row)
        if not self.running:return
        if records:
            try:self.store.append(records,at=frame['at'])
            except BaseException:
                self.stop_flag.set();self.load_error=True;self.reason='SIMULATION_JOURNAL_REVIEW_REQUIRED';self.update_view();raise
            self.orders=(self.orders+records)[-64:]
        self.rows=rows;self.reason='EXPLICIT_ASSUMED_FILLS_NOT_TRADING_EVIDENCE' if records else 'WAITING_FOR_NATIVE_INPUTS_OR_SIMULATED_FUNDS'
        self.update_view()
