"""One persistent, opt-in simulated portfolio for the normal scanner workflow."""
from copy import deepcopy
from decimal import Decimal as D,localcontext
import json
import os
from pathlib import Path
import sqlite3
import uuid

from coincat_adaptive_eth import recoverable_inventory
from coincat_paper_engine import PaperEngine,PaperLimits,PaperBlocked,TERMINAL
from coincat_paper_policy import (AutoConfig,POLICY,MODELS,DIRECTIONS,candidates,
    select_candidate,paper_frame,reference_costs,eth_mark)
from coincat_paper_venue import StressVenue
from coincat_watchlist import WATCH_PAIRS

PUBLIC_COUNTS=('orders','fills','non_fills','partials','gaps','enabled_views','reviews')
PUBLIC_STATES=('OFF','ACTIVE','PAUSED','RECONCILIATION_REQUIRED','EXPIRED','UNAVAILABLE','WAITING_FOR_FRAME')


def public_status(value=None):
    value=value if isinstance(value,dict) else {}
    out={k:value.get(k,0) if type(value.get(k,0)) is int and 0<=value.get(k,0)<=1000000000 else 0 for k in PUBLIC_COUNTS}
    out.update(state=value.get('state') if value.get('state') in PUBLIC_STATES else 'OFF',
        model=value.get('model') if value.get('model') in MODELS else 'UNOBSERVED',
        policy=POLICY,provider='SEEDED_BBO_STRESS_NOT_EXCHANGE_MATCHING',classification='SIMULATED_ASSUMPTION',
        valuation=value.get('valuation') if value.get('valuation') in ('PAPER_ETH_CASH','UNKNOWN') else 'UNKNOWN',
        actual_profit='NOT_ESTABLISHED',edge='NO_DEMONSTRATED_EDGE',live_permission=False)
    return out


def validate_public(value):
    if not isinstance(value,dict) or value!=public_status(value) or set(value)!=set(public_status()):
        raise ValueError('INVALID_AUTO_PAPER_PUBLIC_SCHEMA')
    if any(type(value[k]) is not int for k in PUBLIC_COUNTS):raise ValueError('INVALID_AUTO_PAPER_PUBLIC_COUNT')
    if type(value['live_permission']) is not bool:raise ValueError('INVALID_AUTO_PAPER_PUBLIC_PERMISSION')
    return value


class AutoPaper:
    def __init__(self,directory,*,load=True):
        self.directory=Path(directory);self.engine=None;self.config=None;self.venue=None
        self.view_rows={};self.last_problem=None;self.session_id=None
        if load:self._load()

    def _load(self):
        index=self.directory/'active_session.json'
        if not index.exists():return
        try:
            if self.directory.is_symlink() or index.is_symlink() or index.stat().st_size>512:raise ValueError()
            raw=json.loads(index.read_text(encoding='utf-8'))
            if set(raw)!={'schema','session'} or raw['schema']!=1:raise ValueError()
            identity=raw['session']
            if not isinstance(identity,str) or len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise ValueError()
            engine=PaperEngine.restore(self.directory/('paper_'+identity+'.sqlite3'))
            context=engine.private_state().get('auto',{})
            if context.get('schema')!=1 or context.get('policy')!=POLICY or context.get('session')!=identity:raise ValueError()
            config=AutoConfig(**context['config']).checked()
            venue=StressVenue(config)
            if context.get('model_assumptions')!=venue.assumptions():raise ValueError('PAPER_MODEL_VERSION_REVIEW_REQUIRED')
            self.engine=engine;self.config=config;self.venue=venue;self.session_id=identity
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,ArithmeticError):
            self.last_problem='STORED_PAPER_SESSION_UNAVAILABLE_NO_REPLACEMENT'

    def create(self,config,*,at,funding):
        if self.last_problem:raise PaperBlocked(self.last_problem)
        if self.engine is not None:raise PaperBlocked('EXISTING_PAPER_SESSION_USE_RESUME_OR_EXPLICIT_NEW')
        config=config.checked()
        if not config.opt_in:raise PaperBlocked('EXPLICIT_PAPER_OPT_IN_REQUIRED')
        if self.directory.is_symlink():raise PaperBlocked('PAPER_SYMLINK_REJECTED')
        self.directory.mkdir(parents=True,exist_ok=True)
        identity=uuid.uuid4().hex
        products=tuple(p for p in WATCH_PAIRS if any(v['pair']==p and config.directions[v['id']]['enabled'] for v in DIRECTIONS))
        limits=PaperLimits(products,{'ETH':config.amount_eth},1,config.max_orders,at+config.duration_s,config.fee_ceiling)
        engine=PaperEngine.from_proposal(self.directory/('paper_'+identity+'.sqlite3'),amount_eth=config.amount_eth,
            limits=limits,at=at,simulation_ack='SIMULATION_ONLY',**funding)
        context=dict(schema=1,policy=POLICY,session=identity,config=config.frozen(),kickoff_reference=None,
            intent_meta={},venue={},pending=[],last_observed_at=None,last_review=None,last_order_at=None,
            reviews=0,last_reason='WAITING_FOR_FIRST_QUALIFYING_FRAME',performance={},history=[],detail_truncated=False,
            horizon=None,native_cap_rule='FIRST_CANONICAL_RECEIPT_CEILING_NEVER_FUNDS',pause_at=None,replacement_deadline=None,
            model_assumptions=StressVenue(config).assumptions())
        engine.checkpoint_context(context)
        index=self.directory/'active_session.json';temporary=index.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(schema=1,session=identity)),encoding='utf-8');os.replace(temporary,index)
        self.engine=engine;self.config=config;self.venue=StressVenue(config);self.session_id=identity
        engine.start('explicit_session_start',at=at)

    def new_session(self):
        if self.engine is not None and self.engine.private_state()['mode']=='ACTIVE':raise PaperBlocked('PAUSE_CURRENT_SESSION_FIRST')
        if self.last_problem:raise PaperBlocked(self.last_problem)
        # The previous database and its index remain until a new initialized
        # session is atomically selected. No record, loss or reservation is erased.
        self.engine=None;self.config=None;self.venue=None;self.view_rows={}

    def start(self,*,at):
        if self.engine is None:raise PaperBlocked('NO_PAPER_SESSION')
        if self.last_problem:raise PaperBlocked('PAPER_REVIEW_RECONCILE_BEFORE_START')
        context=self.engine.private_state()['auto']
        for meta in context['venue'].values():
            meta.update(consecutive=0,cross_started=None,last_quote_at=None)
        context.update(pause_at=None,last_reason='EXPLICIT_PAPER_SESSION_START')
        self.engine.checkpoint_context(context)
        self.engine.start('start_'+str(self.engine._revision),at=at)

    def pause(self,*,at):
        if self.engine is None:return
        context=self.engine.private_state()['auto'];context.update(pause_at=at,last_reason='PAPER_STOP_RESERVATIONS_RETAINED')
        self.engine.checkpoint_context(context)
        self.engine.stop('stop_'+str(self.engine._revision),at=at)
        # Already determined explicit receipts may settle; STOP never creates a
        # new intent, price-derived execution or cancellation confirmation.
        self.venue.settle_due(self.engine,at=at)

    def reconcile(self,*,at):
        if self.engine is None:raise PaperBlocked('NO_PAPER_SESSION')
        wallet,orders=self.venue.reconciliation_snapshot(self.engine,at=at)
        self.engine.reconcile('reconcile_'+str(self.engine._revision),wallet=wallet,orders=orders,at=at,
            source='EXPLICIT_SIMULATION')
        state=self.engine.private_state();context=state['auto']
        context['pending']=[p for p in context['pending'] if state['orders'][p['reference']]['state'] not in TERMINAL]
        for meta in context['venue'].values():meta.update(consecutive=0,cross_started=None,last_quote_at=None)
        context['last_reason']='RECONCILED_PAUSED_EXPLICIT_START_REQUIRED'
        self.engine.checkpoint_context(context)
        self.last_problem=None

    def _reason(self,reason):
        context=self.engine.private_state()['auto'];context['last_reason']=reason
        self.engine.checkpoint_context(context)

    def _sample(self,frame):
        state=self.engine.private_state();context=state['auto'];performance=context['performance']
        references,realized,fees=reference_costs(state)
        try:marked=eth_mark(state['wallet'],frame)
        except (ValueError,TypeError,KeyError,ArithmeticError):marked=None
        recovery=recoverable_inventory(state['wallet'],frame)
        if state['mode']=='RECONCILIATION_REQUIRED':recovery['recoverable_eth']=None
        previous_at=performance.get('at');previous_mark=performance.get('marked_eth')
        with localcontext() as precision:
            precision.prec=60
            delta=None if marked is None else marked-state['initial_eth']
            peak=max(performance.get('peak_midpoint_eth',state['initial_eth']),marked or D(0))
            drawdown=None if marked is None else max(D(0),(1-marked/peak)*100)
            elapsed=0 if previous_at is None else max(0,frame.at-previous_at)
            continuous=elapsed<=30 and previous_mark is not None and marked is not None
            underwater=performance.get('observed_underwater_s',0)
            if continuous and previous_mark<state['initial_eth'] and marked<state['initial_eth']:underwater+=elapsed
            performance.update(at=frame.at,initial_hold_eth=state['initial_eth'],marked_eth=marked,
                midpoint_delta_eth=delta,peak_midpoint_eth=peak,midpoint_drawdown_pct=drawdown,
                max_midpoint_drawdown_pct=max(performance.get('max_midpoint_drawdown_pct',D(0)),drawdown or D(0)),
                observed_underwater_s=underwater,unobserved_s=performance.get('unobserved_s',0)+(0 if continuous else elapsed),
                recoverable_eth=recovery['recoverable_eth'],valuation_reasons=recovery['reasons'],
                realized_paper_delta_eth=realized,fees=fees,reference_eth=references,
                actual_profit_eth=None,edge='NO_DEMONSTRATED_EDGE')
        if not context['history'] or frame.at-context['history'][-1]['at']>=60:
            if len(context['history'])<2048:
                context['history'].append(dict(at=frame.at,marked_eth=marked,recoverable_eth=recovery['recoverable_eth'],
                    midpoint_delta_eth=delta,mode=state['mode'],fills=state['simulated_fills']))
            else:context['detail_truncated']=True
        deadline=state['limits']['expires_at']
        if context['horizon'] is None and frame.at>=deadline:
            context['horizon']=dict(at=frame.at,deadline=deadline,
                state='MISSED_HORIZON' if frame.at-deadline>30 else
                    'UNKNOWN_AT_HORIZON' if recovery['recoverable_eth'] is None else 'CONDITIONAL_OUTCOME',
                marked_eth=marked if frame.at-deadline<=30 else None,
                recoverable_eth=recovery['recoverable_eth'] if frame.at-deadline<=30 else None,
                hold_eth=state['initial_eth'],metrics=deepcopy(performance) if frame.at-deadline<=30 else None)
        self.engine.checkpoint_context(context)

    def on_frame(self,frame):
        if self.engine is None or self.last_problem:return
        state=self.engine.private_state();context=state['auto']
        last=context['last_observed_at']
        if last is not None and frame.at<=last:return
        try:
            if self.config.frozen()!=context['config']:raise PaperBlocked('FROZEN_PAPER_POLICY_CHANGED')
            if self.venue.assumptions()!=context['model_assumptions']:raise PaperBlocked('FROZEN_PAPER_MODEL_CHANGED')
            self.venue.settle_due(self.engine,at=frame.at,frame=frame)
            state=self.engine.private_state()
            expired=any(o['state'] not in TERMINAL and frame.at>=o['expires_at'] for o in state['orders'].values())
            if expired or (state['mode']=='ACTIVE' and frame.at>=state['limits']['expires_at']):
                self.engine.tick('expiry_'+str(self.engine._revision),at=frame.at)
            self.venue.advance(self.engine,frame)
            state=self.engine.private_state();context=state['auto']
            context['last_observed_at']=frame.at;self.engine.checkpoint_context(context)
            self._sample(frame)
            state=self.engine.private_state();context=state['auto']
            if state['mode']!='ACTIVE':return
            try:paper_frame(frame,self.config)
            except (ValueError,TypeError,KeyError,ArithmeticError):
                self._reason('WAITING_FRESH_ELIGIBLE_QUOTES_AND_ACCOUNT_FEES');return
            if context['last_review'] is not None and frame.at-context['last_review']<self.config.review_s:return
            context['last_review']=frame.at;context['reviews']+=1;self.engine.checkpoint_context(context)
            open_orders=[o for o in state['orders'].values() if o['state'] not in TERMINAL]
            current=open_orders[0] if open_orders else None
            kickoff=context['kickoff_reference'] is None
            if not kickoff:
                first=state['orders'][context['kickoff_reference']]
                if first['state'] in TERMINAL and first['filled_base']==0:
                    self._reason('KICKOFF_UNFILLED_NO_SUBSTITUTE_SEED');return
            self.view_rows=candidates(self.engine,frame,self.config,
                review_reference=current['reference'] if current and current['state']=='OPEN' else None,kickoff=kickoff)
            selected=select_candidate(self.view_rows,kickoff=self.config.kickoff if kickoff else None)
            if current is not None:
                original=context['intent_meta'].get(current['reference'],{})
                if (current['state']=='OPEN' and original.get('kind')=='RETURN_ETH' and selected is not None and
                        selected['kind']=='ROTATION' and selected['priority']>1):
                    context.update(replacement_deadline=current['expires_at'],
                        last_reason='BETTER_CONDITIONAL_ROTATION_CANCEL_BEFORE_REPLACEMENT')
                    self.engine.request_cancel('rotate_cancel_'+str(self.engine._revision),current['reference'],context_after=context)
                    self.venue.advance(self.engine,frame)
                else:self._reason('REVIEW_RETAIN_RESTING_ORDER_OR_LOCKED_PARTIAL')
                return
            if selected is None:
                self._reason(self.view_rows[self.config.kickoff]['reason'] if kickoff else 'HOLD_NO_ELIGIBLE_AFTER_COST_CANDIDATE');return
            if context['last_order_at'] is not None and frame.at-context['last_order_at']<self.config.cooldown_s:
                self._reason('PAPER_COOLDOWN');return
            if selected['kind']=='RETURN_ETH' and selected['priority']==1:
                last_acquisition=max((f['raw']['at'] for f in state['fills'].values()
                    if f['settled'] and f.get('target')==selected['source']),default=0)
                expired_return=any(o['state']=='CANCELED' and o['source']==selected['source'] and
                    frame.at>=o['expires_at']>=last_acquisition and context['intent_meta'].get(ref,{}).get('kind')=='RETURN_ETH'
                    for ref,o in state['orders'].items())
                if expired_return:
                    self._reason('HOLD_PRIOR_PATIENT_RETURN_EXPIRED_NO_BLIND_REPOST');return
            inherited=context.get('replacement_deadline')
            if inherited is not None and frame.at>=inherited:
                context.update(replacement_deadline=None,last_reason='ROTATION_WINDOW_EXPIRED_REEVALUATE_FRESH_NEXT_REVIEW')
                self.engine.checkpoint_context(context);return
            reference='a'+self.session_id[:12]+'_'+str(len(state['orders'])+1)
            context=self.engine.private_state()['auto']
            if kickoff:context['kickoff_reference']=reference
            context['intent_meta'][reference]=dict(direction=selected['id'],kind=selected['kind'],
                required_eth=selected.get('required_eth'),reason=selected['reason'])
            context.update(last_order_at=frame.at,last_reason=selected['reason'])
            expiry=min(frame.at+self.config.directions[selected['id']]['wait_s'],state['limits']['expires_at'])
            if inherited is not None:
                expiry=min(expiry,inherited);context['replacement_deadline']=None
            try:
                self.engine.place('intent_'+reference,reference=reference,pair=selected['pair'],side=selected['side'],
                    source_budget=selected['source_budget'],limit_price=selected['limit_price'],expires_at=expiry,
                    frame=paper_frame(frame,self.config,planning=True),context_after=context,target_cap_from_receipt=True)
            except PaperBlocked as exc:
                if str(exc) in ('PAPER_POST_ONLY_WOULD_CROSS_OR_BAD_TICK','PAPER_FUNDS_UNAVAILABLE_OR_RESERVED',
                        'PAPER_NATIVE_CAP_EXCEEDED','PAPER_PRODUCT_INELIGIBLE'):
                    selected.update(state='BLOCKED',reason='BLOCKED_POST_ONLY_FUNDING_OR_ELIGIBILITY')
                    self._reason(selected['reason']);return
                raise
            self.venue.advance(self.engine,frame)
        except (PaperBlocked,ValueError,TypeError,KeyError,OSError,sqlite3.Error,ArithmeticError):
            # Fixed public status only. Never log account inputs or raw errors.
            self.last_problem='PAPER_MODEL_OR_STORAGE_REVIEW_REQUIRED'
            try:self.engine.stop('attention_'+str(self.engine._revision),at=frame.at)
            except (ValueError,OSError,sqlite3.Error):pass

    def public(self):
        if self.engine is None:return public_status({'state':'UNAVAILABLE' if self.last_problem else 'OFF'})
        state=self.engine.private_state();context=state['auto'];orders=list(state['orders'].values())
        mode='UNAVAILABLE' if self.last_problem else state['mode']
        if mode=='PAUSED' and context.get('horizon') is not None:mode='EXPIRED'
        return public_status(dict(state=mode,model=self.config.model,orders=len(orders),fills=state['simulated_fills'],
            non_fills=sum(o['state'] in ('CANCELED','REJECTED') and o['filled_base']==0 for o in orders),
            partials=sum(0<o['filled_base']<o['base_size'] for o in orders),
            gaps=sum(m['gaps'] for m in context['venue'].values()),reviews=context['reviews'],
            enabled_views=sum(s['enabled'] for s in self.config.directions.values()),
            valuation='PAPER_ETH_CASH' if mode!='RECONCILIATION_REQUIRED' and
                context['performance'].get('recoverable_eth') is not None else 'UNKNOWN'))
