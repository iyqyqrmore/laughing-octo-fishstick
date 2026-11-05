"""Durable read-only/shadow lifecycle. This module has no SDK/write adapter.

Local undispatched proposals can be retired with known zero fills. Once an
explicit replay models dispatch, cancellation/remaining quantity/holds require
explicit reconciled evidence; quote touches never advance inventory.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import threading
import time
import uuid

from coincat_beta_store import BetaBlocked,digest
from coincat_trial_store import TrialStore
from coincat_trial_clock import begin_run,advance,prime_quality,end_run,progress,NS
from coincat_shadow_source import frame_quality
from coincat_execution_limits import native_math
from coincat_fill_units import normalize_fill
from coincat_manual_trade import identity,fill_identity
from coincat_order_services import PortfolioInventory,native_fill_changes,ShadowAuthorization
from coincat_order_services import ticket_values
from coincat_portfolio_policy import PortfolioConfig,select_candidates,usd_marks,performance,POLICY,assess_ticket
from coincat_trial_evidence import new_metrics,validate_metrics,observe,summary as evidence_summary
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

TERMINAL={'FILLED','CANCELED','REJECTED'}
MODES={'PAUSED','ACTIVE','RECOVERING','RECONCILIATION_REQUIRED','EXPIRED','LIMIT_REACHED','COMPLETE'}
ORDER_STATES=TERMINAL|{'RESERVED','SIMULATED_OPEN','SIMULATED_PARTIAL','CANCEL_PENDING','UNKNOWN'}

def validate(state):
    if state.get('schema')!=2 or state.get('strategy')!=POLICY or state.get('config_digest')!=digest(state['config']) or state.get('provider')!='READ_ONLY_SHADOW_WITH_EXPLICIT_REPLAY' or state['mode'] not in MODES:
        raise BetaBlocked('SHADOW_STATE_INVALID')
    config=PortfolioConfig(**state['config']).checked();identity(state['portfolio'])
    if 'research_metrics' in state:validate_metrics(state['research_metrics'])
    if state['expires_at']!=state['started_at']+config.duration_s:raise BetaBlocked('SHADOW_ORIGINAL_EXPIRY_CHANGED')
    for field in ('wallet','original','venue_holds'):
        if set(state[field])!=set(WATCH_ASSETS) or any(exact(q)<0 for q in state[field].values()):raise BetaBlocked('SHADOW_INVENTORY_INVALID')
    if len(state['orders'])>config.max_orders or len(state['fills'])>512 or len(state['observations'])>256:raise BetaBlocked('SHADOW_HISTORY_LIMIT')
    active=0
    for ref,o in state['orders'].items():
        if o['reference']!=ref or o['pair'] not in WATCH_PAIRS or o['side'] not in ('BUY','SELL') or o['state'] not in ORDER_STATES:
            raise BetaBlocked('SHADOW_ORDER_INVALID')
        if o['post_only'] is not True or o['dispatch_count'] not in (0,1):raise BetaBlocked('SHADOW_MAKER_OR_DISPATCH_INVALID')
        if not 0<=o['filled']<=o['size'] or o.get('prior_spent',D(0))+o['spent']<0:raise BetaBlocked('SHADOW_REMAINING_BUDGET_INVALID')
        if o.get('prior_spent',D(0))+o['spent']>o['root_budget'] and o.get('budget_breach') is not True:
            raise BetaBlocked('UNREVIEWED_SHADOW_BUDGET_BREACH')
        active+=o['state'] not in TERMINAL
    if active>1:raise BetaBlocked('SHADOW_ONE_OPEN_ORDER_LIMIT')

class ShadowTrader:
    def __init__(self,path,*,clock=time.time,monotonic_ns=time.monotonic_ns):
        self.path=Path(path);self.clock=clock;self.monotonic_ns=monotonic_ns
        self.stop_flag=threading.Event();self.stop_flag.set();self.authorization=ShadowAuthorization()
        self.store=None;self.rows=[];self.last_frame=None;self.load_error=False;self.lease=None;self.last_evaluation_ns=None;self.report_pending=False
        if self.path.exists():
            try:
                self.store=TrialStore(self.path,validate=validate)
                with self.store.lock:
                    if self.store.clock['phase']=='COMPLETE':
                        if self.state()['mode']!='COMPLETE':raise BetaBlocked('COMPLETE_TRIAL_MODEL_CLOCK_CONFLICT')
                    else:
                        begin_run(self.store.clock,wall=self.clock(),mono_ns=self.monotonic_ns())
                        state=self.state();active=self._active(state)
                        unresolved=bool(active and active['dispatch_count'] or any(not f['settled'] for f in state['fills'].values()))
                        mode='RECONCILIATION_REQUIRED' if unresolved else 'RECOVERING' if self.store.clock['wanted'] else 'PAUSED'
                        def recover(s):
                            if 'research_metrics' not in s:s['research_metrics']=new_metrics(self.clock(),complete_history=False,prior_reviews=s['reviews'])
                            s.update(mode=mode,reason='RESTORED_NO_OFFLINE_FILLS',last_performance=None)
                        self._change('RECOVERY',{},recover)
                        if unresolved:self.store.clock.update(phase='REVIEW_REQUIRED',reason='REPLAY_RECONCILIATION_REQUIRED')
                        if self.store.clock['wanted'] and not unresolved:self.stop_flag.clear()
                        self.store.flush_clock()
            except Exception:
                # Preserve the failed database in place. Never initialize a clean
                # replacement over an incomplete/corrupt checkpoint.
                self.load_error=True;self.store=None;self.stop_flag.set()
            if self.store is not None and self.store.clock['phase']=='COMPLETE':
                try:self.write_report()
                except (OSError,ValueError):self.report_pending=True
    def state(self):return None if self.store is None else self.store.state()
    def _change(self,kind,payload,action,event_id=None,*,evidence=None):
        return self.store.change(kind,event_id or uuid.uuid4().hex,payload,action,evidence=evidence)
    def start(self,account,config):
        if self.load_error:raise BetaBlocked('SAVED_TRIAL_REVIEW_REQUIRED_NO_RESET')
        config=config.checked();PortfolioInventory(account);now=self.clock()
        if not 0<=now-account['at']<=30:raise BetaBlocked('FRESH_STARTING_PORTFOLIO_REQUIRED')
        if self.store is None:
            wallet={a:exact(account['available'].get(a,D(0)))+exact(account['holds'].get(a,D(0))) for a in WATCH_ASSETS}
            if not any(wallet.values()):raise BetaBlocked('STARTING_PORTFOLIO_EMPTY')
            state=dict(schema=2,trial_id=uuid.uuid4().hex,strategy=POLICY,config_digest=digest(asdict(config)),
                provider='READ_ONLY_SHADOW_WITH_EXPLICIT_REPLAY',mode='RECOVERING',portfolio=account['portfolio'],
                wallet=wallet,original=deepcopy(wallet),actual_last=deepcopy(wallet),external_changes=[],
                venue_holds={a:exact(account['holds'].get(a,D(0))) for a in WATCH_ASSETS},
                config=asdict(config),started_at=now,expires_at=now+config.duration_s,last_at=now,last_review=None,
                orders={},fills={},observations=[],reviews=0,reason='EXPLICIT_SHADOW_START',last_performance=None,
                research_metrics=new_metrics(now),
                initial_usd=None,initial_valuation_at=None,peak_usd=None,max_drawdown=D(0),pending_replacement=None)
            self.store=TrialStore(self.path,initial=state,validate=validate)
            begin_run(self.store.clock,wall=now,mono_ns=self.monotonic_ns())
        else:
            state=self.state()
            if state['portfolio']!=account['portfolio']:raise BetaBlocked('SHADOW_PORTFOLIO_SCOPE_CHANGED')
            if state['config']!=asdict(config):raise BetaBlocked('SHADOW_SETTINGS_FROZEN_FOR_ORIGINAL_TRIAL')
            if state['mode']=='RECONCILIATION_REQUIRED':raise BetaBlocked('SHADOW_RESTART_RECONCILIATION_REQUIRED')
            if self.store.clock['phase']=='COMPLETE':raise BetaBlocked('COMPLETED_TRIAL_FROZEN')
        with self.store.lock:
            self.store.clock.update(wanted=True,phase='RECOVERING',previous_valid=False)
            self.stop_flag.clear();self.lease=None
            self._change('RESUME',{'at':now},lambda s:s.update(mode='RECOVERING',reason='SHADOW_ONLY_WAIT_FOR_FRESH_EVALUATION'))
    def heartbeat(self,*,persist=False):
        if self.store is None:return
        with self.store.lock:
            c=self.store.clock;mono=self.monotonic_ns();coverage=0;valid=False
            if (self.lease is not None and 0<=mono-self.lease['mono']<=25*NS and
                    0<=self.clock()-self.lease['wall']<=25):
                coverage=self.lease['coverage'];valid=self.lease['valid']
            if self.state()['mode']=='RECONCILIATION_REQUIRED':
                c.update(phase='REVIEW_REQUIRED',previous_valid=False,reason='UNRECONCILED_ORDER_OR_FEE')
            advance(c,wall=self.clock(),mono_ns=mono,valid=valid,coverage=coverage,run_id=c['run_id'])
            if c['phase']=='COMPLETE' and self.state()['mode']!='COMPLETE':
                self.stop_flag.set();self._change('COMPLETE_168_HOURS',{},lambda s:s.update(mode='COMPLETE',reason='TRIAL_COMPLETE_NO_NEW_PERMISSION'))
                try:self.write_report()
                except (OSError,ValueError):self.report_pending=True
            elif persist:self.store.flush_clock()
    def shutdown(self):
        if self.store is None:return
        self.heartbeat()
        with self.store.lock:
            end_run(self.store.clock,wall=self.clock());self.store.flush_clock()
        self.stop_flag.set()
    def progress(self):return None if self.store is None else progress(self.store.clock,self.clock())
    def research_summary(self):return None if self.store is None else evidence_summary(self.state(),self.progress())
    def write_report(self):
        if self.store is None:return None
        from coincat_beta_store import pack
        path=self.path.with_name('trial-'+self.state()['trial_id']+'-summary.json')
        if path.is_symlink() or path.with_suffix('.tmp').is_symlink():raise BetaBlocked('TRIAL_REPORT_SYMLINK_REJECTED')
        raw=pack(dict(classification='HYPOTHETICAL_RESEARCH_NOT_REALIZED_PROFIT',progress=self.progress(),
            research_summary=self.research_summary(),trial=self.state()))
        path.with_suffix('.tmp').write_text(raw,encoding='utf-8');path.with_suffix('.tmp').replace(path)
        return path
    @staticmethod
    def _active(state):return next((o for o in state['orders'].values() if o['state'] not in TERMINAL),None)
    @staticmethod
    def _free(state):
        available={a:state['wallet'][a]-state['venue_holds'][a] for a in WATCH_ASSETS}
        o=ShadowTrader._active(state)
        if o:available[o['source']]-=max(D(0),o['reserved']-o['spent'])
        if any(q<0 for q in available.values()):raise BetaBlocked('SHADOW_INVENTORY_OR_HOLDS_UNRECONCILED')
        return available
    @staticmethod
    def _charged(state):
        # Completed fractions retain the original fee buffer in the durable
        # capital charge; native third-asset commissions do not erase it.
        return sum((o['risk_usd']*(max(o['spent']/o['reserve_initial'],o['filled']/o['size']) if o['state'] in TERMINAL else 1)
            for o in state['orders'].values()),D(0))
    @staticmethod
    def _cancel(state,order,reason):
        if order['state'] in TERMINAL:return
        if order['dispatch_count']==0 and order['filled']==0:
            order.update(state='CANCELED',reserved=D(0),reconciled=True,reason='UNDISPATCHED_LOCAL_PROPOSAL_RETIRED')
        else:order.update(state='UNKNOWN' if order['state']=='UNKNOWN' else 'CANCEL_PENDING',reason=reason)
    def stop(self):
        if self.store is None:return
        self.heartbeat();self.stop_flag.set();self.lease=None
        with self.store.lock:self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False)
        def pause(s):
            o=self._active(s)
            if o:self._cancel(s,o,'STOP_AWAITS_RECONCILED_REPLAY_CANCEL')
            s.update(mode='RECONCILIATION_REQUIRED' if o and o['state']=='UNKNOWN' else 'PAUSED',reason='STOP_NO_LIQUIDATION',last_performance=None)
        self._change('STOP',{},pause)
    def reconcile_restart(self):
        if self.store is None:return
        def reconcile(s):
            o=self._active(s)
            if o:
                if o['dispatch_count'] or o['filled']:raise BetaBlocked('EXPLICIT_REPLAY_RECONCILIATION_REQUIRED')
                self._cancel(s,o,'RESTART_LOCAL_CANCEL')
            if any(not f['settled'] for f in s['fills'].values()):raise BetaBlocked('UNSETTLED_REPLAY_FILL_REMAINS')
            s.update(mode='PAUSED',reason='REPLAY_RECONCILED_RESUME_AVAILABLE')
            self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False)
        self._change('RECONCILE_RESTART',{},reconcile)
    def observation_gap(self,at,reason='GET_ONLY_OBSERVATION_UNAVAILABLE'):
        if self.store is None:return
        self.heartbeat();self.lease=None
        with self.store.lock:prime_quality(self.store.clock,valid=False,coverage=0)
        def gap(s):
            s['reason']=reason;s['last_performance']=None
            if at>=s['expires_at']:
                o=self._active(s)
                if o:self._cancel(s,o,'EXPIRED_WITHOUT_FRESH_QUOTES')
                s['mode']='EXPIRED'
        self._change('OBSERVATION_GAP',dict(at=at,reason=reason),gap)
    def archive(self):
        self.stop()
        if self.store is None:return
        s=self.state()
        if self._active(s) or any(not f['settled'] for f in s['fills'].values()):raise BetaBlocked('RECONCILE_SHADOW_BEFORE_ARCHIVING')
        archive=self.path.with_name('completed-'+uuid.uuid4().hex+'.sqlite3')
        if archive.exists() or self.path.is_symlink() or self.path.parent.is_symlink():raise BetaBlocked('SHADOW_ARCHIVE_PATH_REJECTED')
        self.path.rename(archive);self.store.path=archive;self.store=None;self.rows=[];self.last_frame=None
    @native_math
    def review(self,frame):
        if self.store is None or self.stop_flag.is_set():return
        config=PortfolioConfig(**self.state()['config']);now=frame['at'];state=self.state()
        if state['mode'] not in ('ACTIVE','RECOVERING','LIMIT_REACHED','EXPIRED'):return
        if frame['portfolio']!=state['portfolio']:self.stop();raise BetaBlocked('SHADOW_PORTFOLIO_SCOPE_CHANGED')
        mono=self.monotonic_ns()
        self.heartbeat()
        if self.stop_flag.is_set():return
        valid,coverage=frame_quality(frame)
        self.lease=dict(mono=mono,wall=self.clock(),valid=valid,coverage=coverage)
        with self.store.lock:prime_quality(self.store.clock,valid=valid,coverage=coverage)
        if not valid:
            from coincat_portfolio_policy import DIRECTIONS
            self.rows=[dict(**v,state='HOLD',reason='PARTIAL_OR_UNVERIFIED_INPUTS') for v in DIRECTIONS]
            self._change('PARTIAL_OBSERVATION',dict(at=now,coverage=coverage),lambda s:s.update(reason='PARTIAL_COVERAGE_NO_FULL_HOURS',last_performance=None));return
        self.last_frame=deepcopy(frame)
        if self.last_evaluation_ns is not None and mono-self.last_evaluation_ns<30*NS:return
        self.last_evaluation_ns=mono
        def decide(s):
            if self.stop_flag.is_set() or s['mode'] not in ('ACTIVE','RECOVERING','LIMIT_REACHED','EXPIRED'):return
            s['mode']='ACTIVE'
            s.update(last_at=now,last_review=now,reviews=s['reviews']+1)
            if now>=s['expires_at']:
                o=self._active(s)
                if o:self._cancel(s,o,'ORIGINAL_SESSION_EXPIRED')
                s['reason']='ORIGINAL_INTENT_AUTHORIZATION_EXPIRED_OBSERVE_ONLY'
            try:
                marks,_=usd_marks(frame)
                s['observations'].append(dict(at=now,marks=marks));s['observations']=s['observations'][-256:]
            except (ValueError,TypeError,KeyError,ArithmeticError):
                s['reason']='UNKNOWN_VALUATION_HOLD';return
            if s['initial_usd'] is None:
                from coincat_portfolio_policy import portfolio_value
                s['initial_usd']=portfolio_value(s['original'],marks);s['initial_valuation_at']=now
            account=frame.get('account')
            if account and account['portfolio']==s['portfolio']:
                actual={a:exact(account['available'].get(a,0))+exact(account['holds'].get(a,0)) for a in WATCH_ASSETS}
                change={a:actual[a]-s['actual_last'][a] for a in WATCH_ASSETS}
                if any(change.values()):
                    s['external_changes'].append(dict(at=account['at'],native_changes=change,classification='ACTUAL_ACCOUNT_CHANGE_EXCLUDED_FROM_SHADOW'));s['external_changes']=s['external_changes'][-128:]
                s['actual_last']=actual
            current=self._active(s)
            # Evaluate a possible replacement with the current reservation still
            # counted in capital, then retire it only after reconciliation.
            available=self._free(s)
            if current:available[current['source']]+=current['reserved']
            charged=self._charged(s)
            if current:charged-=current['risk_usd']
            self.rows,chosen=select_candidates(frame,s['wallet'],available,s['original'],s['observations'],config,
                remaining_capital=config.max_turnover_usd-charged)
            if 'research_metrics' not in s:s['research_metrics']=new_metrics(now,complete_history=False,prior_reviews=s['reviews']-1)
            observe(s['research_metrics'],self.rows,now)
            s['last_performance']=performance(frame,s['wallet'],s['original'],s['observations'],config,
                initial_usd=s['initial_usd'],fills=s['fills'],
                accounting_complete=not any(not f['settled'] for f in s['fills'].values()) and
                    not any(o['state'] in ('UNKNOWN','CANCEL_PENDING') for o in s['orders'].values()))
            perf=s['last_performance']
            if perf.get('portfolio_usd') is not None:
                value=perf['portfolio_usd'];s['peak_usd']=max(value,s['peak_usd'] or value)
                s['max_drawdown']=max(s['max_drawdown'],(s['peak_usd']-value)/s['peak_usd'])
                perf['max_drawdown_fraction']=s['max_drawdown']
            if now>=s['expires_at'] or self.store.clock['calendar_uncertain']:
                chosen=None;s['reason']='NO_NEW_INTENTS_ORIGINAL_EXPIRY_OR_CLOCK_UNCERTAINTY'
            if current:
                if current['state'] in ('UNKNOWN','CANCEL_PENDING'):s['reason']='RECONCILE_BEFORE_ANY_REPLACEMENT';return
                if now-current['created_at']<120:s['reason']='REVIEW_RETAIN_NO_TWO_MINUTE_TRADE_REQUIREMENT';return
                same=next((r for r in self.rows if r['pair']==current['pair'] and r['side']==current['side']),None)
                justified=same is not None and same['state']=='SHADOW_CANDIDATE'
                changed=justified and same['price']!=current['price']
                if justified and not changed:s['reason']='RESTING_PRICE_STILL_JUSTIFIED_RETAIN';return
                self._cancel(s,current,'CONDITIONAL_REVIEW_CANCEL_NO_REPLACE_BEFORE_RECONCILIATION')
                if current['state'] not in TERMINAL:s['reason']='WAIT_CANCEL_QUANTITY_AND_HOLDS';return
                s['pending_replacement']=current['reference']
                # Unsent proposals have known zero fills/holds. Other orders can
                # reach terminal only via explicit replay reconciliation.
                if chosen and current['filled']:
                    chosen=None
            if chosen is None:s['reason']='HOLD_COSTS_UNCERTAINTY_OR_RISK_NOT_JUSTIFIED';return
            if len(s['orders'])>=config.max_orders:s.update(reason='DURABLE_ORDER_ATTEMPT_LIMIT_OBSERVE_HOLD');return
            ref=uuid.uuid4().hex;source=chosen['source']
            parent=s['orders'].get(s.get('pending_replacement'))
            root=ref;prior_spent=D(0);root_size=chosen['size'];root_budget=chosen['reserve']
            if parent and parent['pair']==chosen['pair'] and parent['side']==chosen['side']:
                root=parent['root'];prior_spent=sum((o['spent'] for o in s['orders'].values() if o['root']==root),D(0))
                filled=sum((o['filled'] for o in s['orders'].values() if o['root']==root),D(0))
                root_size=parent['root_size'];root_budget=parent['root_budget']
                remaining=root_size-filled;budget=root_budget-prior_spent
                inc=exact(frame['rules'][chosen['pair']]['base_increment'])
                size=min(chosen['size'],remaining)
                if chosen['side']=='BUY':size=min(size,budget/(chosen['price']*(1+config.fee_ceiling)))
                else:size=min(size,budget/(1+config.fee_ceiling))
                size=(size//inc)*inc
                try:ticket_values(dict(pair=chosen['pair'],side=chosen['side'],size=size,price=chosen['price'],post_only=True),frame['rules'][chosen['pair']],frame['books'][chosen['pair']])
                except (ValueError,TypeError,ArithmeticError):s['reason']='REMAINING_SIZE_OR_NATIVE_MINIMUM_HOLD';return
                chosen=dict(chosen,size=size,reserve=size*(chosen['price'] if chosen['side']=='BUY' else 1)*(1+config.fee_ceiling))
                chosen=assess_ticket(frame,s['wallet'],s['original'],s['observations'],config,chosen)
                if chosen['state']!='SHADOW_CANDIDATE':s['reason']='REMAINING_SIZE_NO_COST_RISK_JUSTIFIED_EDGE';return
            if chosen['reserve']>self._free(s)[source]:raise BetaBlocked('SHADOW_RESERVE_CONFLICT')
            s['orders'][ref]=dict(reference=ref,pair=chosen['pair'],side=chosen['side'],source=source,target=chosen['target'],
                size=chosen['size'],price=chosen['price'],post_only=True,state='RESERVED',created_at=now,
                reserved=chosen['reserve'],reserve_initial=chosen['reserve'],root_budget=root_budget,root=root,
                root_size=root_size,prior_spent=prior_spent,
                risk_usd=chosen['reserve_usd'],filled=D(0),spent=D(0),dispatch_count=0,venue_id=None,
                reconciled=False,reason='LOCAL_SHADOW_PROPOSAL_NO_EXCHANGE_REQUEST',decision=deepcopy(chosen))
            s['reason']='SHADOW_PROPOSAL_ONLY_NO_FILL_ASSUMED'
            s['pending_replacement']=None
        def recorded_decision(s):
            result=decide(s);last=(s.get('research_metrics') or {}).get('last_review')
            if last is not None and last['at']==now:last['execution_reason']=s['reason']
            return result
        self._change('MARKET_REVIEW',dict(frame=frame),recorded_decision,
            evidence=lambda s:deepcopy((s.get('research_metrics') or {}).get('last_review')))

    @native_math
    def replay(self,event,event_id):
        """Explicit simulation input only; never called by market-price reads."""
        if event.get('source')!='EXPLICIT_SIMULATED_REPLAY':raise BetaBlocked('REPLAY_SOURCE_ACK_REQUIRED')
        if self.store is None:raise BetaBlocked('SHADOW_SESSION_MISSING')
        def apply(s):
            ref=event.get('reference');o=s['orders'].get(ref)
            if o is None:raise BetaBlocked('REPLAY_ORDER_UNKNOWN')
            at=float(event['at'])
            if at<s['last_at']:raise BetaBlocked('REPLAY_TIME_MOVED_BACKWARDS')
            s['last_at']=at;kind=event.get('kind')
            if kind=='DISPATCH':
                if o['state']!='RESERVED' or o['dispatch_count']:raise BetaBlocked('REPLAY_DISPATCH_ALREADY_CONSUMED')
                o.update(dispatch_count=1,state='UNKNOWN');s.update(mode='RECONCILIATION_REQUIRED',last_performance=None,reason='AWAIT_REPLAY_DISPATCH_RESULT');return
            if kind=='ACK':
                if o['dispatch_count']!=1 or o['state'] not in ('UNKNOWN','RESERVED'):raise BetaBlocked('REPLAY_ACK_WITHOUT_DISPATCH')
                venue=fill_identity(event['venue_id'])
                if any(x['reference']!=ref and x['venue_id']==venue for x in s['orders'].values()):raise BetaBlocked('REPLAY_DUPLICATE_VENUE_ID')
                o.update(venue_id=venue,state='SIMULATED_OPEN')
                self.store.clock.update(phase='RECOVERING' if self.store.clock['wanted'] else 'PAUSED',previous_valid=False)
                s['mode']='RECOVERING' if self.store.clock['wanted'] else 'PAUSED';return
            if kind=='UNKNOWN_POST':
                if o['dispatch_count']!=1:raise BetaBlocked('REPLAY_UNKNOWN_WITHOUT_DISPATCH')
                o['state']='UNKNOWN';s.update(mode='RECONCILIATION_REQUIRED',reason='UNKNOWN_POST_NEVER_RETRY',last_performance=None);return
            if kind in ('FILL','FEE_EVIDENCE'):
                if o['dispatch_count']!=1 or o['state'] in TERMINAL:raise BetaBlocked('REPLAY_FILL_ORDER_NOT_OPEN')
                if o['venue_id'] is None or event.get('venue_id')!=o['venue_id']:raise BetaBlocked('REPLAY_FILL_VENUE_IDENTITY_CONFLICT')
                raw=deepcopy(event['fill']);tid=fill_identity(raw['trade_id'])
                if raw.get('product_id',o['pair'])!=o['pair'] or raw.get('side',o['side'])!=o['side']:raise BetaBlocked('REPLAY_FILL_NATIVE_IDENTITY_CONFLICT')
                raw.update(product_id=o['pair'],side=o['side']);s['last_performance']=None
                previous=s['fills'].get(tid)
                if previous and previous['reference']!=ref:raise BetaBlocked('REPLAY_FILL_ORDER_IDENTITY_CONFLICT')
                if previous and previous['settled']:
                    if previous['raw']!=raw:raise BetaBlocked('REPLAY_FILL_CONFLICT')
                    return
                if previous:
                    for key in ('size','price','commission','size_in_quote'):
                        if raw.get(key)!=previous['raw'].get(key):raise BetaBlocked('REPLAY_FEE_EVIDENCE_CHANGED_FILL')
                native=normalize_fill(raw);quantity=native['base_qty'];price=native['price']
                if not 0<quantity<=o['size']-o['filled']:raise BetaBlocked('REPLAY_FILLED_SIZE_EXCEEDS_REMAINING')
                if (price>o['price'] if o['side']=='BUY' else price<o['price']):raise BetaBlocked('REPLAY_PRICE_VIOLATES_LIMIT')
                try:flow=native_fill_changes(raw)
                except BetaBlocked:
                    s['fills'][tid]=dict(reference=ref,raw=raw,settled=False);o['state']='UNKNOWN'
                    s.update(mode='RECONCILIATION_REQUIRED',reason='ACTUAL_COMMISSION_UNITS_UNKNOWN');return
                updated={a:s['wallet'][a]+flow['changes'][a] for a in WATCH_ASSETS}
                spent=-flow['changes'][o['source']]
                if any(v<s['venue_holds'][a] for a,v in updated.items()):
                    s['fills'][tid]=dict(reference=ref,raw=raw,settled=False);o['state']='UNKNOWN'
                    s.update(mode='RECONCILIATION_REQUIRED',reason='REPLAY_INVENTORY_CONFLICT_PRESERVE_EVIDENCE');return
                if o['prior_spent']+o['spent']+spent>o['root_budget']:
                    o['budget_breach']=True;s.update(mode='RECONCILIATION_REQUIRED',reason='KNOWN_REPLAY_COST_ACCOUNTED_BUDGET_REVIEW_REQUIRED')
                s['wallet']=updated;o['filled']+=quantity;o['spent']+=spent
                # Partial proceeds remain unavailable while the single order is
                # unresolved. Source reserve stays until terminal reconciliation.
                s['fills'][tid]=dict(reference=ref,raw=raw,settled=True,flow=flow)
                o['state']='SIMULATED_PARTIAL'
                base,quote=o['pair'].split('-')
                fraction=flow['commission']/(flow['gross_quote'] if flow['fee_currency']==quote else flow['base_qty']) if flow['fee_currency'] in (base,quote) else None
                if fraction is None or fraction>PortfolioConfig(**s['config']).fee_ceiling:
                    s.update(mode='RECONCILIATION_REQUIRED',reason='ACTUAL_FEE_ACCOUNTED_POLICY_REVIEW_REQUIRED')
                if raw.get('liquidity_indicator') not in ('M','MAKER'):
                    s.update(mode='RECONCILIATION_REQUIRED',reason='NON_MAKER_FILL_ACCOUNTED_POLICY_REVIEW_REQUIRED')
                return
            if kind=='CANCEL_ACK':
                if o['dispatch_count']!=1 or o['state'] in TERMINAL:raise BetaBlocked('REPLAY_CANCEL_STATE_INVALID')
                if event.get('venue_id')!=o['venue_id'] or o['venue_id'] is None:raise BetaBlocked('REPLAY_CANCEL_IDENTITY_CONFLICT')
                o['state']='CANCEL_PENDING';s['last_performance']=None;return
            if kind=='RECONCILE':
                if o['dispatch_count']!=1 or any(not f['settled'] for f in s['fills'].values() if f['reference']==ref):
                    raise BetaBlocked('REPLAY_FILL_OR_DISPATCH_RECONCILIATION_INCOMPLETE')
                if o['venue_id'] is None:
                    if event.get('client_reference')!=ref:raise BetaBlocked('UNKNOWN_POST_IDENTITY_REMAINS_UNPROVEN')
                    o['venue_id']=fill_identity(event.get('venue_id'))
                expected={k for k,f in s['fills'].items() if f['reference']==ref}
                if (set(event.get('fill_ids',[]))!=expected or exact(event['filled_base'])!=o['filled'] or
                        event.get('complete') is not True or event.get('order_hold_released') is not True or
                        event.get('inventory')!=s['wallet'] or event.get('venue_id')!=o['venue_id']):
                    raise BetaBlocked('REPLAY_CANCEL_QUANTITY_HOLDS_OR_INVENTORY_UNVERIFIED')
                status=event['status']
                if status not in TERMINAL or status=='FILLED' and o['filled']!=o['size'] or status=='REJECTED' and o['filled']:
                    raise BetaBlocked('REPLAY_TERMINAL_STATE_INVALID')
                o.update(state=status,reserved=D(0),reconciled=True)
                if status=='CANCELED' and o['filled']<o['size']:s['pending_replacement']=ref
                s.update(mode='PAUSED',reason='REPLAY_RECONCILED_EXPLICIT_RESUME_REQUIRED',last_performance=None)
                self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False);return
            raise BetaBlocked('REPLAY_EVENT_KIND_UNSUPPORTED')
        self._change('EXPLICIT_REPLAY',deepcopy(event),apply,event_id=event_id)

    def public(self):
        from coincat_shadow_public import project
        s=self.state();p=self.progress()
        return project(dict(state='REVIEW_REQUIRED' if self.load_error or s and s['mode']=='RECONCILIATION_REQUIRED' else 'OFF' if p is None else p['state'],
            valid_seconds=0 if p is None else int(p['valid_seconds']),
            restart_count=0 if p is None else p['restart_count'],
            coverage_percent=0 if p is None else round(p['coverage_percent'],2),
            reviews=0 if s is None else s['reviews'],orders=0 if s is None else len(s['orders']),
            fills=0 if s is None else sum(f['settled'] for f in s['fills'].values()),
            unresolved=0 if s is None else sum(o['state'] not in TERMINAL for o in s['orders'].values()),
            evidence=self.research_summary()))
