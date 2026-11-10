"""Shared restart-safe maker SHADOW lifecycle; policy adapters hold no live grant."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from coincat_assumed_math import rounded,fee_rate
from coincat_beta_store import BetaBlocked,digest,pack
from coincat_execution_limits import native_math
from coincat_order_services import native_fill_changes,ShadowAuthorization
from coincat_manual_trade import explicit_fee_currency
from coincat_opportunity_venue import accept,modeled_fill
from coincat_portfolio_policy import DIRECTIONS,portfolio_value,valid_book
from coincat_trial_clock import begin_run,advance,prime_quality,end_run,progress,NS
from coincat_trial_store import TrialStore
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

STATES={'NEW','OPEN','PARTIAL','CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'}
TERMINAL={'FILLED','CANCELED'}
MODES={'RECOVERING','ACTIVE','PAUSED','REVIEW_REQUIRED','FINALIZING','COMPLETE'}
COUNTERS=('reviews','direction_checks','qualified_checks','rejected_checks','opportunity_episodes',
    'orders','fill_events','modeled_fills','replay_fills','partials','canceled','nonfills','replacements','gaps','unknown_events')
ORDER_FIXED=('reference','campaign','pair','side','price','size','post_only','created_at','expires_at')
ROOT_FIXED=('id','pair','side','source','budget','initial_size','created_at','expires_at','episode')
TRANSITIONS={
    'NEW':{'NEW','OPEN','CANCEL_PENDING','CANCELED','UNKNOWN'},
    'OPEN':{'OPEN','PARTIAL','CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'},
    'PARTIAL':{'PARTIAL','CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'},
    'CANCEL_PENDING':{'CANCEL_PENDING','FILLED','CANCELED','UNKNOWN'},
    'UNKNOWN':{'UNKNOWN','OPEN','PARTIAL','CANCEL_PENDING','FILLED','CANCELED'},
    'FILLED':{'FILLED'},'CANCELED':{'CANCELED'}}

def active(state):return None if state['active'] is None else state['orders'][state['active']]

def free(state,*,own=False):
    values=deepcopy(state['wallet']);order=active(state)
    if order is not None and not own:values[order['source']]-=order['reserved']
    if any(v<0 for v in values.values()):raise BetaBlocked('OPPORTUNITY_RESERVATIONS_EXCEED_WALLET')
    return values

def metrics():
    return dict(**{k:0 for k in COUNTERS},rejections={},fees_usd_at_fill=D(0),marked_change_at_fills_usd=D(0),
        unknown_fill_marks=0,last_fill_change_usd=None)

@native_math
def validate(s,policy):
    if (s.get('schema')!=1 or s.get('strategy')!=policy.name or s.get('provider')!=policy.provider or
            s.get('mode') not in MODES or s.get('config_digest')!=digest(s['config'])):raise BetaBlocked('INVALID_OPPORTUNITY_CHECKPOINT')
    config=policy.config(s['config'])
    if s['expires_at'] is not None or s['portfolio']!=policy.portfolio:raise BetaBlocked('INVALID_OPPORTUNITY_PORTFOLIO_SCOPE')
    for key in ('wallet','original','seed_marks','fees_native'):
        if set(s[key])!=set(WATCH_ASSETS) or any(exact(v)<0 for v in s[key].values()):raise BetaBlocked('INVALID_OPPORTUNITY_NATIVE_WALLET')
    if any(type(s['metrics'][k]) is not int or s['metrics'][k]<0 for k in COUNTERS):raise BetaBlocked('INVALID_OPPORTUNITY_COUNTERS')
    if s['metrics']['direction_checks']!=14*s['metrics']['reviews'] or s['metrics']['qualified_checks']+s['metrics']['rejected_checks']!=s['metrics']['direction_checks']:
        raise BetaBlocked('INVALID_OPPORTUNITY_REVIEW_COUNTS')
    if 'rejection_detail' in s['metrics']:policy.validate_rejections(s['metrics']['rejection_detail'],s['metrics']['rejected_checks'])
    if len(s['observations'])>201 or len(s['orders'])>40 or len(s['campaigns'])>40:raise BetaBlocked('OPPORTUNITY_CACHE_BOUND')
    count=0
    for ref,o in s['orders'].items():
        if (o['reference']!=ref or o['pair'] not in WATCH_PAIRS or o['side'] not in ('BUY','SELL') or o['state'] not in STATES or
                o['post_only'] is not True or not 0<=o['filled']<=o['size'] or o['size']<=0 or o['price']<=0 or o['reserved']<0):
            raise BetaBlocked('INVALID_OPPORTUNITY_ORDER')
        if o['state']=='FILLED' and o['filled']!=o['size']:raise BetaBlocked('OPPORTUNITY_FILLED_QUANTITY_CONFLICT')
        if o['state'] in TERMINAL and o['reserved']!=0:raise BetaBlocked('TERMINAL_OPPORTUNITY_HOLD_NOT_RELEASED')
        if o['expires_at']!=min(o['created_at']+config.order_lifetime_s,s['campaigns'][o['campaign']]['expires_at']):
            raise BetaBlocked('OPPORTUNITY_ORIGINAL_ORDER_EXPIRY_CHANGED')
        if len(o['fills'])>1024:raise BetaBlocked('OPPORTUNITY_ORDER_FILL_EVIDENCE_BOUND')
        count+=o['state'] not in TERMINAL
    if count>1 or count!=int(s['active'] is not None):raise BetaBlocked('OPPORTUNITY_ONE_OPEN_ORDER_REQUIRED')
    for root in s['campaigns'].values():
        if (not 1<=root['attempts']<=config.retry_budget+1 or not 0<=root['filled']<=root['initial_size'] or
                root['spent']<0 or root['age_s']<0 or root['expires_at']!=root['created_at']+config.campaign_lifetime_s):
            raise BetaBlocked('OPPORTUNITY_CAMPAIGN_BUDGET_OR_LIFETIME_INVALID')
    free(s);policy.validate_extra(s)

def trim(s):
    # Only the small GUI cache is bounded. Append-only transaction evidence stays.
    for ref,o in list(s['orders'].items()):
        if len(s['orders'])<=32:break
        if o['state'] in TERMINAL:del s['orders'][ref]
    used={o['campaign'] for o in s['orders'].values()}
    for ref,root in list(s['campaigns'].items()):
        if len(s['campaigns'])<=32:break
        if ref not in used and root['closed']:del s['campaigns'][ref]

class MakerShadowTrader:
    def __init__(self,path,*,policy,clock=time.time,monotonic_ns=time.monotonic_ns):
        self.policy=policy
        self.path=Path(path);self.clock=clock;self.monotonic_ns=monotonic_ns;self.authorization=ShadowAuthorization()
        self.stop_flag=threading.Event();self.stop_flag.set();self.store=None;self.load_error=False
        self.lease=None;self.last_frame=None;self.last_review_ns=None;self.age_pending=0.;self._view={}
        self.pending_config=self.policy.config();self.reason='START_OPPORTUNITY_SHADOW';self.report_saved=False
        if self.path.exists():
            try:
                self.store=TrialStore(self.path,validate=self.validate);self.pending_config=self.policy.config(self.state()['config'])
                if self.store.clock['phase']!='COMPLETE':
                    gap=max(0,self.clock()-self.store.clock['last_wall'])
                    begin_run(self.store.clock,wall=self.clock(),mono_ns=self.monotonic_ns())
                    def recover(s):
                        self._age(s,gap);o=active(s)
                        unresolved=bool(o is not None and (o.get('pending_fill') is not None or
                            o['state']=='UNKNOWN' and o.get('unknown_kind')!='RESTART_GAP'))
                        if o is not None:
                            if not unresolved:o.update(state='UNKNOWN',unknown_kind='RESTART_GAP',reason='RECONCILE_LOCAL_VENUE_NO_DOWNTIME_FILLS')
                            o['venue']=None
                        s.update(mode='REVIEW_REQUIRED' if unresolved else 'RECOVERING' if self.store.clock['wanted'] else 'PAUSED',
                            reason='EXPLICIT_UNKNOWN_REQUIRES_RECEIPT' if unresolved else 'RECOVERED_WAIT_FOR_FRESH_DATA',last_performance=None)
                    self._change('RECOVERY',{},recover)
                    if self.store.clock['wanted'] and self.state()['mode']!='REVIEW_REQUIRED':self.stop_flag.clear()
                self.reason=self.state()['reason']
            except (ValueError,OSError,TypeError,KeyError,ArithmeticError,sqlite3.Error):
                self.store=None;self.load_error=True;self.reason='SAVED_OPPORTUNITY_TRIAL_REVIEW_REQUIRED_NO_RESET'
        self.update_view()

    def validate(self,s):return validate(s,self.policy)

    @property
    def running(self):return not self.stop_flag.is_set()
    def state(self):return None if self.store is None else self.store.state()
    def current_pair(self):
        o=self._view.get('active_order');return None if o is None else o['pair']
    def _change(self,kind,payload,action,event_id=None):
        with self.store.lock:return self._locked_change(kind,payload,action,event_id)

    def _locked_change(self,kind,payload,action,event_id=None):
        before=self.state()
        def evidence(s):
            # Retain each intent/projection and every new native receipt once,
            # including a terminal fill whose active pointer is now empty.
            # Do not copy 100 trade-ID hashes and old receipts every 10 seconds
            # throughout a 168-hour trial. The checkpoint owns that queue cache.
            changed=[]
            for ref,o in s['orders'].items():
                prior=before['orders'].get(ref)
                fields=('reference','campaign','state','filled','reserved','reason','reconciled')
                row={k:deepcopy(o[k]) for k in fields}
                row['new_fills']={k:deepcopy(v) for k,v in o['fills'].items() if prior is None or k not in prior['fills']}
                if prior is None:row['intent']={k:deepcopy(v) for k,v in o.items() if k not in ('venue','fills')}
                if o.get('pending_fill') is not None and (prior is None or o['pending_fill']!=prior.get('pending_fill')):
                    row['pending_fill']=deepcopy(o['pending_fill'])
                if prior is None or row['new_fills'] or any(o[k]!=prior[k] for k in fields) or 'pending_fill' in row:changed.append(row)
            o=active(s);venue=None if o is None else o.get('venue')
            decisions=None
            if s['metrics']['reviews']!=before['metrics']['reviews']:
                keys=('pair','side','state','reason','size','price','projected_advantage_usd','projected_entry_fee_native',
                    'fee_currency','estimated_future_exit_cost_usd','forecast_uncertainty_usd','execution_uncertainty_usd')
                decisions=[{k:row[k] for k in keys if k in row} for row in s['rows']]
            result=dict(wallet=s['wallet'],fees_native=s['fees_native'],active=s['active'],orders=changed,decisions=decisions,
                venue=None if venue is None else {k:venue[k] for k in ('queue_left','through_count','data_state')},metrics=s['metrics'])
            self.policy.audit_state(result,s);return result
        def guarded(s):
            if s['mode']=='COMPLETE':raise BetaBlocked('COMPLETED_OPPORTUNITY_TRIAL_FROZEN')
            result=action(s)
            if hasattr(self.policy,'compact'):self.policy.compact(s)
            if s['mode']=='REVIEW_REQUIRED' and self.store.clock['phase']!='COMPLETE':
                self.store.clock.update(phase='REVIEW_REQUIRED',previous_valid=False)
            for ref,o in before['orders'].items():
                if ref in s['orders']:
                    after=s['orders'][ref]
                    if (any(after[k]!=o[k] for k in ORDER_FIXED) or after['filled']<o['filled'] or after['age_s']<o['age_s'] or
                            after['state'] not in TRANSITIONS[o['state']]):
                        raise BetaBlocked('OPPORTUNITY_ORDER_IMMUTABILITY_CONFLICT')
            for ref,root in before['campaigns'].items():
                if ref in s['campaigns']:
                    after=s['campaigns'][ref]
                    if any(after[k]!=root[k] for k in ROOT_FIXED) or any(after[k]<root[k] for k in ('attempts','filled','spent','age_s')):
                        raise BetaBlocked('OPPORTUNITY_ROOT_BUDGET_CANNOT_RESET')
            return result
        try:
            return self.store.change(kind,event_id or uuid.uuid4().hex,payload,guarded,
                evidence=evidence)
        except (sqlite3.Error,OSError):self.stop_flag.set();self.load_error=True;raise
        except BetaBlocked as exc:
            if str(exc).startswith(('TRIAL_','STALE_TRIAL_','WRONG_TRIAL_')):self.stop_flag.set();self.load_error=True
            raise

    def start(self,config=None):
        if self.load_error:raise BetaBlocked('SAVED_OPPORTUNITY_TRIAL_REVIEW_REQUIRED_NO_RESET')
        config=(config or self.pending_config).checked()
        if self.store is not None:
            if asdict(config)!=self.state()['config']:raise BetaBlocked('OPPORTUNITY_POLICY_FROZEN_FOR_ORIGINAL_TRIAL')
            if self.store.clock['phase']=='COMPLETE':raise BetaBlocked('COMPLETED_OPPORTUNITY_TRIAL_FROZEN')
            if self.state()['mode']=='REVIEW_REQUIRED':raise BetaBlocked('OPPORTUNITY_RECONCILIATION_REQUIRED')
            self.store.clock.update(wanted=True,phase='RECOVERING',previous_valid=False)
            self._change('RESUME',{},lambda s:s.update(mode='RECOVERING',reason='RESUME_NEEDS_FRESH_OBSERVATIONS'))
        self.pending_config=config;self.lease=None;self.stop_flag.clear();self.update_view()

    @native_math
    def _initialize(self,frame):
        config=self.pending_config.checked();funding=self.policy.seed(frame,self.clock(),config);initial=portfolio_value(funding['original'],funding['seed_marks'])
        state=dict(schema=1,strategy=self.policy.name,provider=self.policy.provider,trial_id=uuid.uuid4().hex,
            started_at=self.clock(),expires_at=None,portfolio=self.policy.portfolio,config=asdict(config),config_digest=digest(asdict(config)),
            mode='RECOVERING',reason='WAIT_FOR_PROSPECTIVE_RISK_WINDOW',wallet=funding['wallet'],original=funding['original'],seed_marks=funding['seed_marks'],
            initial_usd=initial,fees_native={a:D(0) for a in WATCH_ASSETS},orders={},campaigns={},active=None,observations=[],
            episodes={d['id']:dict(number=0,qualified=False,started=False,campaign=None) for d in DIRECTIONS},
            metrics=metrics(),rows=[],last_review_at=None,last_observation_at=None,last_performance=None,
            peak_usd=initial,max_drawdown=D(0),completed_report=None)
        self.policy.initialize(state,frame,config)
        self.store=TrialStore(self.path,initial=state,validate=self.validate)
        begin_run(self.store.clock,wall=self.clock(),mono_ns=self.monotonic_ns());self.store.flush_clock()

    @staticmethod
    def _age(s,seconds):
        for root in s['campaigns'].values():
            if not root['closed']:root['age_s']+=seconds
        o=active(s)
        if o is not None:o['age_s']+=seconds

    @staticmethod
    def _request_cancel(s,o,now,reason,*,replace=False):
        if o['state'] in TERMINAL:return
        if o['state']=='UNKNOWN' and o.get('unknown_kind')!='RESTART_GAP':
            o['reason']='UNKNOWN_OUTCOME_REQUIRES_EXPLICIT_RECONCILIATION';s.update(mode='REVIEW_REQUIRED',reason=o['reason']);return
        if o.get('pending_fill') is not None:
            s.update(mode='REVIEW_REQUIRED',reason='UNSETTLED_NATIVE_FEE_OR_QUANTITY');return
        if o['state']!='CANCEL_PENDING':o.update(state='CANCEL_PENDING',cancel_requested_at=now,cancel_due=now+2,reason=reason)
        s['campaigns'][o['campaign']]['pending_replace']=replace

    def _cancel_ack(self,s,o,now):
        if o.get('pending_fill') is not None:raise BetaBlocked('CANCEL_REQUIRES_SETTLED_FILL_QUANTITIES')
        if o['state'] in TERMINAL:raise BetaBlocked('OPPORTUNITY_TERMINAL_STATUS_CANNOT_CHANGE')
        root=s['campaigns'][o['campaign']]
        o.update(state='CANCELED',reserved=D(0),reconciled=True,closed_at=now);s['active']=None
        s['metrics']['canceled']+=1;s['metrics']['nonfills']+=int(o['filled']==0)
        config=self.policy.config(s['config'])
        if (not root['pending_replace'] or root['attempts']>=config.retry_budget+1 or root['filled']==root['initial_size'] or
                root['age_s']>=config.campaign_lifetime_s or now>=root['expires_at']):root.update(closed=True,pending_replace=False)

    @native_math
    def _fill(self,s,o,raw,frame,now,source):
        fingerprint=digest(raw);ref=raw.get('trade_id')
        if not isinstance(ref,str) or not 1<=len(ref)<=100:raise BetaBlocked('OPPORTUNITY_FILL_ID_REQUIRED')
        if ref in o['fills']:
            if o['fills'][ref]['fingerprint']!=fingerprint:raise BetaBlocked('CONFLICTING_OPPORTUNITY_FILL_RECEIPT')
            return
        if o['state'] in TERMINAL:raise BetaBlocked('OPPORTUNITY_FILL_AFTER_TERMINAL_REQUIRES_REVIEW')
        for key in ('size','price'):
            if exact(raw.get(key))<=0:raise BetaBlocked('INVALID_OPPORTUNITY_FILL_NATIVE_AMOUNT')
        if raw.get('product_id')!=o['pair'] or raw.get('side')!=o['side'] or raw.get('size_in_quote') is not False:
            raise BetaBlocked('OPPORTUNITY_FILL_BINDING_CONFLICT')
        q,price=exact(raw['size']),exact(raw['price']);inc=exact(o['rules']['base_increment'])
        if q%inc or q>o['size']-o['filled'] or (price>o['price'] if o['side']=='BUY' else price<o['price']):raise BetaBlocked('OPPORTUNITY_FILL_REMAINING_OR_LIMIT_CONFLICT')
        try:currency=explicit_fee_currency(raw)
        except BetaBlocked:currency=None
        if raw.get('commission') is None or currency is None:
            o.update(state='UNKNOWN',pending_fill=deepcopy(raw),unknown_kind='UNSETTLED_FEE',reason='FEE_CURRENCY_OR_AMOUNT_UNKNOWN')
            s.update(mode='REVIEW_REQUIRED',reason='FEE_CURRENCY_OR_AMOUNT_UNKNOWN');s['metrics']['unknown_events']+=1;return
        exact(raw['commission']);flow=native_fill_changes(raw)
        after={a:s['wallet'][a]+flow['changes'][a] for a in WATCH_ASSETS}
        if any(v<0 for v in after.values()):raise BetaBlocked('OPPORTUNITY_FILL_EXCEEDS_NATIVE_INVENTORY')
        marked=None;fee_usd=None
        try:
            marks,stamps=self.policy.marks(frame)
            if not 0<=now-frame['at']<=30 or any(not 0<=now-at<=30 for at in stamps):raise ValueError()
            marked=portfolio_value(after,marks)-portfolio_value(s['wallet'],marks);fee_usd=flow['commission']*marks[flow['fee_currency']]
        except (ValueError,TypeError,KeyError,ArithmeticError):pass
        root=s['campaigns'][o['campaign']];spent=-flow['changes'][o['source']]
        s['wallet']=after;s['fees_native'][flow['fee_currency']]+=flow['commission'];root['filled']+=q;root['spent']+=spent
        o['filled']+=q;o['fills'][ref]=dict(fingerprint=fingerprint,receipt=deepcopy(raw),flow=flow,source=source,at=now,marked_change_usd=marked)
        o['pending_fill']=None
        s['metrics']['fill_events']+=1;s['metrics']['modeled_fills' if source=='PUBLIC_TRADE_QUEUE_MODEL' else 'replay_fills']+=1
        s['metrics']['partials']+=int(o['filled']<o['size']);s['metrics']['last_fill_change_usd']=marked
        if marked is None:s['metrics']['unknown_fill_marks']+=1
        else:s['metrics']['marked_change_at_fills_usd']+=marked
        if fee_usd is not None:s['metrics']['fees_usd_at_fill']+=fee_usd
        remaining=o['size']-o['filled'];o['reserved']=remaining*(o['price']*(1+o['maker_rate']) if o['side']=='BUY' else 1)
        if remaining==0:
            o.update(state='FILLED',reserved=D(0),reconciled=True,closed_at=now);s['active']=None;root.update(closed=True,pending_replace=False)
            # A completed fill changes the portfolio. A later fresh evaluation
            # may identify a new opportunity; failed retries never reset this way.
            s['episodes'][o['pair']+'_'+o['side']].update(qualified=False,started=False,campaign=None)
        elif o['state'] not in ('CANCEL_PENDING','UNKNOWN'):o['state']='PARTIAL'
        if root['spent']>root['budget']:
            root['budget_breach']=True;o['reserved']=min(o['reserved'],s['wallet'][o['source']])
            s.update(mode='REVIEW_REQUIRED',reason='ACTUAL_NATIVE_COST_EXCEEDED_ORIGINAL_MODEL_BUDGET')
            if remaining:o.update(state='UNKNOWN',unknown_kind='COST_REVIEW')

    @native_math
    def _place(self,s,row,now,root=None):
        if not self.running:return
        config=self.policy.config(s['config']);direction=row['pair']+'_'+row['side'];episode=s['episodes'][direction]
        if root is None:
            ref='CAM-'+uuid.uuid4().hex
            root=dict(id=ref,pair=row['pair'],side=row['side'],source=row['source'],budget=row['reserve'],initial_size=row['size'],
                filled=D(0),spent=D(0),attempts=0,created_at=now,expires_at=now+config.campaign_lifetime_s,age_s=0.,
                episode=episode['number'],closed=False,pending_replace=False)
            s['campaigns'][ref]=root;episode.update(started=True,campaign=ref)
        if root['closed'] or root['attempts']>=config.retry_budget+1 or now>=root['expires_at']:raise BetaBlocked('OPPORTUNITY_RETRY_OR_ORIGINAL_LIFETIME_EXHAUSTED')
        ref='OPP-'+uuid.uuid4().hex;root['attempts']+=1;root['pending_replace']=False
        order=dict(reference=ref,campaign=root['id'],pair=row['pair'],side=row['side'],source=row['source'],
            price=row['price'],size=row['size'],post_only=True,state='NEW',filled=D(0),reserved=row['reserve'],maker_rate=row['maker_rate'],
            rules=deepcopy(self.last_frame['rules'][row['pair']]),created_at=now,expires_at=min(now+config.order_lifetime_s,root['expires_at']),age_s=0.,
            accepted_at=None,venue=None,fills={},pending_fill=None,reconciled=False,reason='POSITIVE_MODEL_ADVANTAGE_NEW_MAKER',projection=deepcopy(row))
        s['orders'][ref]=order;s['active']=ref;s['metrics']['orders']+=1;s['metrics']['replacements']+=int(root['attempts']>1);trim(s)
        if hasattr(self.policy,'placed'):self.policy.placed(s,order)

    def _consume_age(self,s):
        self._age(s,self.age_pending)

    def _timers(self,s,now):
        config=self.policy.config(s['config']);o=active(s)
        for root in s['campaigns'].values():
            if root['age_s']>=config.campaign_lifetime_s or now>=root['expires_at']:root.update(closed=True,pending_replace=False)
        if o is None:return
        root=s['campaigns'][o['campaign']]
        if o['state']=='UNKNOWN' and o.get('unknown_kind')=='RESTART_GAP':
            self._request_cancel(s,o,now,'RESTART_LOCAL_VENUE_RECONCILIATION',replace=not root['closed'])
        elif o['state']=='CANCEL_PENDING' and now>=o['cancel_due']:
            # This is our own deterministic shadow venue's ledger receipt, not
            # a guessed exchange cancellation. All known fills settle first.
            self._cancel_ack(s,o,now)
        elif o['state'] in ('NEW','OPEN','PARTIAL') and (o['age_s']>=config.order_lifetime_s or now>=o['expires_at'] or root['closed']):
            self._request_cancel(s,o,now,'FINITE_ORDER_LIFETIME_REACHED',replace=not root['closed'])

    def _venue(self,s,frame,now):
        o=active(s)
        if o is None:return
        config=self.policy.config(s['config'])
        if o['state']=='NEW' and now-o['created_at']>=2:
            try:accept(o,frame,config,now)
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                if isinstance(exc,BetaBlocked) and str(exc)=='WAIT_FOR_PUBLIC_TRADE_ANCHOR':o['reason']=str(exc)
                else:self._request_cancel(s,o,now,'POST_ONLY_ACCEPTANCE_OR_PRODUCT_CHANGED',replace=False)
            return
        if o['state'] not in ('OPEN','PARTIAL','CANCEL_PENDING'):return
        try:
            receipt=modeled_fill(o,frame,config,now)
            if (o.get('venue') or {}).get('data_state')=='TRADE_WINDOW_GAP_NO_FILL':s['metrics']['gaps']+=1
            if receipt:self._fill(s,o,receipt,frame,now,'PUBLIC_TRADE_QUEUE_MODEL')
        except (ValueError,TypeError,KeyError,ArithmeticError):
            o['reason']='PUBLIC_TRADE_OR_NATIVE_FEE_EVIDENCE_UNCERTAIN'

    @native_math
    def _replacement(self,s,row,frame,root):
        config=self.policy.config(s['config']);remaining=root['initial_size']-root['filled']
        budget=root['budget']-root['spent'];price=row['price'];rate=fee_rate(frame,'MAKER')
        inc=exact(frame['rules'][row['pair']]['base_increment'])
        affordable=budget/(price*(1+rate)) if row['side']=='BUY' else budget
        quantity=self.policy.replacement_size(row,remaining,affordable,inc)
        ticket=dict(pair=row['pair'],side=row['side'],size=quantity,price=price,post_only=True)
        evaluated=self.policy.assess(frame,s['wallet'],s['original'],s['observations'],config,ticket)
        if evaluated['state']!='QUALIFIED' or evaluated['reserve']>budget:raise BetaBlocked('REPLACEMENT_NO_REMAINING_NATIVE_ADVANTAGE_OR_BUDGET')
        return evaluated

    @native_math
    def _decide(self,s,frame,now):
        config=self.policy.config(s['config']);o=active(s)
        rows,_=self.policy.evaluate(frame,s['wallet'],free(s),s['original'],s['observations'],config)
        self.policy.record_rejections(s['metrics'],rows)
        s['metrics']['reviews']+=1;s['metrics']['direction_checks']+=14;s['last_review_at']=now;s['rows']=rows
        for row in rows:
            episode=s['episodes'][row['id']];qualified=row['state']=='QUALIFIED'
            s['metrics']['qualified_checks' if qualified else 'rejected_checks']+=1
            if qualified and not episode['qualified']:
                episode.update(number=episode['number']+1,qualified=True,started=False,campaign=None);s['metrics']['opportunity_episodes']+=1
            elif self.policy.resets_episode(row):episode['qualified']=False
            if not qualified:
                reason=row['reason'];s['metrics']['rejections'][reason]=s['metrics']['rejections'].get(reason,0)+1
        if o is not None:
            if o['state'] not in ('OPEN','PARTIAL'):return
            root=s['campaigns'][o['campaign']]
            try:
                remaining=dict(pair=o['pair'],side=o['side'],size=o['size']-o['filled'],price=o['price'],post_only=True)
                assessed=self.policy.assess(frame,s['wallet'],s['original'],s['observations'],config,remaining,resting=True)
                o['latest_projection']=assessed
                if assessed['reserve']>root['budget']-root['spent']:
                    self._request_cancel(s,o,now,'REMAINING_ORIGINAL_NATIVE_BUDGET_CHANGED',replace=False);return
                if assessed['state']!='QUALIFIED':
                    self._request_cancel(s,o,now,'EXPECTED_RISK_ADJUSTED_ADVANTAGE_LOST',replace=False);return
                if o['age_s']>=config.reconsider_s:
                    book=valid_book(frame,o['pair']);tick=exact(frame['rules'][o['pair']].get('price_increment',frame['rules'][o['pair']]['quote_increment']))
                    competitive=book['bid']-o['price']<=2*tick if o['side']=='BUY' else o['price']-book['ask']<=2*tick
                    if not competitive:self._request_cancel(s,o,now,'UNCOMPETITIVE_AT_120_SECOND_REVIEW',replace=True)
            except (ValueError,TypeError,KeyError,ArithmeticError):
                self._request_cancel(s,o,now,'RISK_OR_INPUT_EVALUATION_UNCERTAIN',replace=False)
            return
        if s['mode'] in ('REVIEW_REQUIRED','FINALIZING','COMPLETE'):return
        candidates=[]
        for row in rows:
            if row['state']!='QUALIFIED':continue
            episode=s['episodes'][row['id']];root=s['campaigns'].get(episode['campaign'])
            if not episode['started']:candidates.append((row,None));continue
            if root is None or root['closed'] or not root['pending_replace']:continue
            if root['attempts']>=config.retry_budget+1 or root['age_s']>=config.campaign_lifetime_s:
                root.update(closed=True,pending_replace=False);continue
            try:candidates.append((self._replacement(s,row,frame,root),root))
            except (ValueError,TypeError,KeyError,ArithmeticError):
                root.update(closed=True,pending_replace=False)
        if candidates:
            selected,root=max(candidates,key=lambda r:(r[0]['projected_advantage_usd'],r[0]['pair'],r[0]['side']))
            self._place(s,selected,now,root)

    @native_math
    def _mark(self,s,frame):
        if any(o.get('pending_fill') is not None or o['state']=='UNKNOWN' for o in s['orders'].values()):s['last_performance']=None;return
        try:
            if not self.policy.mark_fresh(frame,self.clock()):raise ValueError()
            if not all(0<=self.clock()-at<=30 for at in self.policy.marks(frame)[1]):raise ValueError()
            perf=self.policy.performance(frame,s['wallet'],s['original'],s['initial_usd']);s['last_performance']=perf
            self.policy.mark(s,frame,perf)
            s['peak_usd']=max(s['peak_usd'],perf['portfolio_usd'])
            if s['peak_usd']>0:s['max_drawdown']=max(s['max_drawdown'],1-perf['portfolio_usd']/s['peak_usd'])
        except (ValueError,TypeError,KeyError,ArithmeticError):s['last_performance']=None

    def review(self,frame):
        if not self.running:return
        now=self.clock()
        if frame.get('state')!='OBSERVED' or not 0<=now-frame.get('at',0)<=30:
            self.observation_gap();return
        if self.store is None:
            try:self._initialize(frame)
            except (sqlite3.Error,OSError):
                self.stop_flag.set();self.load_error=True;self.reason='OPPORTUNITY_INITIALIZATION_STORAGE_REVIEW_REQUIRED';self.update_view();raise
            except (ValueError,TypeError,KeyError,ArithmeticError):
                self.reason='FRESH_FIVE_ASSET_SEED_REFERENCES_REQUIRED';self.update_view();return
        self.heartbeat()
        if not self.running:return
        if self.last_frame is not None and frame['at']<=self.last_frame['at']:return
        valid,coverage=self.policy.frame_quality(frame)
        try:
            self.policy.validate_frame(frame)
            if any(not 0<=now-b['at']<=30 for b in frame['books'].values()):valid=False
        except (ValueError,TypeError,KeyError,ArithmeticError):valid=False
        valid=valid and self.policy.decision_fresh(frame,now)
        try:reference_times=self.policy.marks(frame)[1]
        except (ValueError,TypeError,KeyError,ArithmeticError):reference_times=()
        self.lease=dict(mono=self.monotonic_ns(),wall=now,valid=valid,coverage=coverage,
            valid_until=min(tuple(b['at']+30 for b in frame.get('books',{}).values())+tuple(at+30 for at in reference_times),default=now))
        self.last_frame=deepcopy(frame)
        with self.store.lock:
            prime_quality(self.store.clock,valid=valid,coverage=coverage)
            due=self.last_review_ns is None or self.monotonic_ns()-self.last_review_ns>=30*NS
            age=self.age_pending
            def observe(s):
                self._consume_age(s);self._timers(s,now);self._venue(s,frame,now);self.policy.observe(s,frame,now)
                if s['mode']=='REVIEW_REQUIRED':return
                s['mode']='ACTIVE';s['reason']='HOLD_UNLESS_MODEL_ADVANTAGE_POSITIVE' if valid else 'PARTIAL_INPUTS_NO_NEW_OPPORTUNITY'
                if due:
                    if valid:
                        marks,_=self.policy.marks(frame);s['observations'].append(dict(at=frame['at'],marks=marks));s['observations']=s['observations'][-201:]
                    if self.running:self._decide(s,frame,now) if self.policy.decision_fresh(frame,now) and self.policy.can_decide(frame,valid) else self._unpriced_review(s,frame)
                self._mark(s,frame);s['last_observation_at']=frame['at']
            self._change('OBSERVATION',dict(at=frame['at'],valid=valid,coverage=coverage,trade_status=frame.get('trade_status','UNSUPPLIED')),observe)
            self.age_pending=max(0,self.age_pending-age)
            if due:self.last_review_ns=self.monotonic_ns()
        if self.state()['mode']=='REVIEW_REQUIRED':self.stop_flag.set()
        self.update_view()

    def _unpriced_review(self,s,frame=None):
        self.policy.on_unpriced(s,frame,self.clock(),self)
        s['rows']=[dict(**d,state='HOLD',reason=self.policy.unpriced_reason(frame)) for d in DIRECTIONS]
        self.policy.record_rejections(s['metrics'],s['rows'])
        s['metrics']['reviews']+=1;s['metrics']['direction_checks']+=14;s['metrics']['rejected_checks']+=14
        reason=self.policy.unpriced_reason(frame);s['metrics']['rejections'][reason]=s['metrics']['rejections'].get(reason,0)+14

    def heartbeat(self,*,persist=False):
        if self.store is None or self.load_error:return
        with self.store.lock:
            c=self.store.clock;now=self.clock();mono=self.monotonic_ns();valid=False;coverage=0
            elapsed=0 if c['last_mono_ns'] is None else max(0,(mono-c['last_mono_ns'])/NS)
            self.age_pending+=max(elapsed,max(0,now-c['last_wall']))
            if self.lease is not None and 0<=mono-self.lease['mono']<=25*NS and 0<=now-self.lease['wall']<=25 and now<=self.lease['valid_until']:
                valid=self.lease['valid'];coverage=self.lease['coverage']
            advance(c,wall=now,mono_ns=mono,valid=valid,coverage=coverage,run_id=c['run_id'])
            s=self.state();o=active(s);config=self.policy.config(s['config'])
            timer=bool(o and (o['state']=='UNKNOWN' and o.get('unknown_kind')=='RESTART_GAP' or
                o['state']=='CANCEL_PENDING' and now>=o['cancel_due'] or
                o['state'] in ('NEW','OPEN','PARTIAL') and (o['age_s']+self.age_pending>=config.order_lifetime_s or now>=o['expires_at'])))
            finishing=c['phase']=='COMPLETE' and s['mode']!='COMPLETE'
            begin_completion=finishing and s['mode'] not in ('FINALIZING','REVIEW_REQUIRED')
            finalize=finishing and o is None and s['mode']!='REVIEW_REQUIRED'
            if c['phase']=='REVIEW_REQUIRED':
                self.stop_flag.set()
                if s['mode']!='REVIEW_REQUIRED':self._change('CLOCK_REVIEW',{},lambda x:x.update(mode='REVIEW_REQUIRED',reason='MONOTONIC_CLOCK_REVIEW_REQUIRED'))
                elif persist:self.store.flush_clock()
            elif timer or begin_completion or finalize or persist and o is not None:
                age=self.age_pending
                def timers(x):
                    self._consume_age(x)
                    if begin_completion:
                        self.stop_flag.set();x['mode']='FINALIZING';owned=active(x)
                        if owned is not None:self._request_cancel(x,owned,now,'168_VALID_HOURS_END_CANCEL_RECONCILE',replace=False)
                    self._timers(x,now)
                    if finishing and active(x) is None and x['mode']!='REVIEW_REQUIRED':
                        x.update(mode='COMPLETE',reason='168_VALID_HOURS_COMPLETE_NO_PROFIT_PROOF')
                        x['completed_report']=dict(classification='CONDITIONAL_SHADOW_NOT_PROVEN_PROFIT',
                            performance=deepcopy(x['last_performance']),metrics=deepcopy(x['metrics']),wallet=deepcopy(x['wallet']),
                            original=deepcopy(x['original']),fees_native=deepcopy(x['fees_native']),max_drawdown=x['max_drawdown'])
                self._change('TIMER_OR_COMPLETION',dict(at=now),timers);self.age_pending=max(0,self.age_pending-age)
            elif persist:self.store.flush_clock()
        self.update_view()
        if self.state()['mode']=='COMPLETE' and not self.report_saved:
            self.write_report();self.report_saved=True

    def observation_gap(self):
        if self.load_error:return
        self.heartbeat();self.lease=None;self.reason='WAIT_FOR_FRESH_OPPORTUNITY_INPUTS'
        if self.store is not None:
            with self.store.lock:
                prime_quality(self.store.clock,valid=False,coverage=0)
                if self.state()['mode'] not in ('COMPLETE','FINALIZING','REVIEW_REQUIRED'):
                    def gap(s):
                        s.update(mode='RECOVERING' if self.store.clock['wanted'] else 'PAUSED',reason='WAIT_FOR_FRESH_OPPORTUNITY_INPUTS',last_performance=None)
                        self.policy.on_unpriced(s,None,self.clock(),self)
                        o=active(s)
                        if o is not None and o['age_s']+self.age_pending>=120:self._request_cancel(s,o,self.clock(),'UNPRICED_AT_ORDER_REVIEW',replace=False)
                    if self.state()['reason']!='WAIT_FOR_FRESH_OPPORTUNITY_INPUTS':self._change('OBSERVATION_GAP',{},gap)
        self.update_view()

    def pause(self):
        self.stop_flag.set();self.heartbeat();self.lease=None
        if self.store is not None and self.state()['mode']!='COMPLETE':
            if self.store.clock['phase']=='COMPLETE':
                self.update_view();return
            self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False)
            def pause(s):
                s.update(mode='PAUSED',reason='PAUSED_CANCEL_ORDER_KEEP_INVENTORY');o=active(s)
                if o is not None:self._request_cancel(s,o,self.clock(),'USER_PAUSE',replace=False)
            self._change('PAUSE',{},pause)
        self.update_view()

    def shutdown(self):
        self.stop_flag.set();self.heartbeat()
        if self.store is None:return
        with self.store.lock:
            end_run(self.store.clock,wall=self.clock())
            if self.state()['mode']!='COMPLETE':
                def leave(s):
                    self._consume_age(s);o=active(s)
                    if o is not None and (o['state']!='UNKNOWN' or o.get('unknown_kind')=='RESTART_GAP'):
                        o.update(state='UNKNOWN',unknown_kind='RESTART_GAP',reason='OWNED_SIM_ORDER_REQUIRES_RESTART_RECONCILIATION')
                    s['reason']='CHECKPOINTED_NO_DOWNTIME_FILLS'
                self._change('SHUTDOWN',{},leave);self.age_pending=0
            else:self.store.flush_clock()
        self.lease=None;self.update_view()

    def progress(self):return None if self.store is None or self.load_error else progress(self.store.clock,self.clock())

    def replay(self,event,event_id):
        if self.store is None:raise BetaBlocked('START_OPPORTUNITY_TRIAL_BEFORE_REPLAY')
        if not isinstance(event,dict) or event.get('source')!='EXPLICIT_SIMULATED_REPLAY':raise BetaBlocked('EXPLICIT_OPPORTUNITY_REPLAY_REQUIRED')
        kind=event.get('kind');fields={'FILL':{'receipt'},'FEE_EVIDENCE':{'receipt'},'UNKNOWN':set(),
            'RECONCILE':{'status','filled','inventory','held_source','complete'}}
        if kind not in fields or set(event)!={'source','reference','kind','at'}|fields[kind]:raise BetaBlocked('INVALID_OPPORTUNITY_REPLAY_SCHEMA')
        now=self.clock()
        if type(event['at']) not in (int,float) or not 0<=now-event['at']<=30:raise BetaBlocked('OPPORTUNITY_REPLAY_TIME_UNVERIFIED')
        def apply(s):
            o=s['orders'].get(event['reference'])
            if o is None or event['at']<o['created_at']:raise BetaBlocked('OPPORTUNITY_REPLAY_ORDER_UNVERIFIED')
            if kind in ('FILL','FEE_EVIDENCE'):
                if kind=='FEE_EVIDENCE':
                    pending=o.get('pending_fill');raw=event['receipt']
                    if (pending is None or any(pending.get(k)!=raw.get(k) for k in ('trade_id','product_id','side','size_in_quote')) or
                            any(exact(pending[k])!=exact(raw[k]) for k in ('size','price'))):
                        raise BetaBlocked('OPPORTUNITY_FEE_RESOLUTION_BINDING_CONFLICT')
                self._fill(s,o,event['receipt'],self.last_frame or {},event['at'],'EXPLICIT_SIMULATED_REPLAY')
            elif kind=='UNKNOWN':
                o.update(state='UNKNOWN',unknown_kind='EXPLICIT_REPLAY',reason='EXPLICIT_AMBIGUOUS_SIMULATED_OUTCOME')
                s.update(mode='REVIEW_REQUIRED',reason='RECONCILE_BEFORE_ANY_REPLACEMENT');s['metrics']['unknown_events']+=1
            else:
                if event['complete'] is not True or o.get('pending_fill') is not None or exact(event['filled'])!=o['filled']:
                    raise BetaBlocked('COMPLETE_OPPORTUNITY_RECONCILIATION_REQUIRED')
                if (not isinstance(event['inventory'],dict) or set(event['inventory'])!=set(WATCH_ASSETS) or
                        {a:exact(q) for a,q in event['inventory'].items()}!=s['wallet']):raise BetaBlocked('OPPORTUNITY_RECONCILED_INVENTORY_CONFLICT')
                status=event['status']
                if status not in ('OPEN','FILLED','CANCELED'):raise BetaBlocked('INVALID_OPPORTUNITY_RECONCILED_STATUS')
                expected=0 if status in TERMINAL else (o['size']-o['filled'])*(o['price']*(1+o['maker_rate']) if o['side']=='BUY' else 1)
                if exact(event['held_source'])!=expected:raise BetaBlocked('OPPORTUNITY_RECONCILED_HOLD_CONFLICT')
                if status=='FILLED' and o['filled']!=o['size']:raise BetaBlocked('OPPORTUNITY_RECONCILED_FILL_CONFLICT')
                if status=='CANCELED':self._cancel_ack(s,o,event['at'])
                else:
                    o.update(state='PARTIAL' if status=='OPEN' and o['filled'] else status,reserved=exact(expected),reconciled=True)
                    if status=='FILLED':s['active']=None
                if self.store.clock['phase']=='COMPLETE':
                    s.update(mode='FINALIZING',reason='RECONCILED_AFTER_OBSERVATION_COMPLETION')
                else:
                    self.store.clock.update(wanted=False,phase='PAUSED',previous_valid=False)
                    s.update(mode='PAUSED',reason='RECONCILED_EXPLICIT_RESUME_REQUIRED')
            self._mark(s,self.last_frame or {})
        result=self._change('REPLAY',event,apply,event_id=event_id)
        if self.state()['mode'] in ('REVIEW_REQUIRED','PAUSED'):self.stop_flag.set()
        self.update_view();return result

    def update_view(self):
        s=self.state()
        if s is None:self._view=dict(state=None,rows=[],active_order=None,orders=[],reason=self.reason,performance=None);return
        self.reason=s['reason']
        self._view=dict(state={k:deepcopy(s[k]) for k in ('trial_id','mode','wallet','original','fees_native','metrics','config','max_drawdown','completed_report')+self.policy.view_keys},
            rows=deepcopy(s['rows']),active_order=deepcopy(active(s)),orders=deepcopy(list(s['orders'].values())[-32:]),reason=s['reason'],
            performance=deepcopy(s['last_performance']))
    def view(self):return deepcopy(self._view)
    def public(self):
        # A worker may commit/publish during this call. All model counters and
        # order facts must come from this one immutable published observation.
        view=self.view();s=view.get('state');p=self.progress();m={} if s is None else s['metrics']
        phase='REVIEW_REQUIRED' if self.load_error else 'OFF' if s is None and not self.running else 'WAITING' if s is None else s['mode']
        return self.policy.public(dict(state=phase,valid_seconds=0 if p is None else int(p['valid_seconds']),restart_count=0 if p is None else p['restart_count'],
            order_state='NONE' if view.get('active_order') is None else view['active_order']['state'],
            rejection_breakdown=self.policy.rejection_summary(m),**{k:m.get(k,0) for k in COUNTERS}),self,view)
    def write_report(self):
        if self.store is None:return None
        path=self.path.with_name(self.policy.report_prefix+self.state()['trial_id']+'-summary.json')
        if path.is_symlink() or path.with_suffix('.tmp').is_symlink():raise BetaBlocked('OPPORTUNITY_REPORT_PATH_REJECTED')
        if self.state()['mode']=='COMPLETE' and path.exists():return path
        value=dict(**self.policy.report_metadata(),classification='CONDITIONAL_MODEL_NOT_PROFITABILITY_EVIDENCE',progress=self.progress(),trial=self.state())
        path.with_suffix('.tmp').write_text(pack(value),encoding='utf-8');path.with_suffix('.tmp').replace(path);return path
