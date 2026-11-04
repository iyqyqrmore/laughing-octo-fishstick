"""Explicitly armed, bounded real maker-order journal; no tax/legacy mutation.

All create-order transport is in LiveBroker.submit. This controller journals
ownership and exactly-once dispatch grants, never fabricates exchange fills.
"""
from copy import deepcopy
from dataclasses import dataclass,asdict
from decimal import Decimal as D,localcontext
import math
from pathlib import Path
import threading
import time
import uuid
from functools import wraps

from coincat_beta_store import BetaStore,BetaBlocked,digest
from coincat_continuity import eth_funding
from coincat_fill_units import normalize_fill,summarize_fills,verify_order_totals
from coincat_global_paper import (revision,settings_at,validate_history,global_candidates,
    qualification,completed_reports,usd_reference,source_budget,initial_campaign)
from coincat_paper_policy import AutoConfig,direction_defaults,paper_frame,reference_costs
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

APP_ID=0x43434C42
TERMINAL={'FILLED','CANCELED','REJECTED'}
MODES={'PAUSED','ACTIVE','RECONCILIATION_REQUIRED','EXPIRED','UNKNOWN_LOCKED'}


def native_math(method):
    @wraps(method)
    def run(*args,**kwargs):
        with localcontext() as context:
            context.prec=80
            return method(*args,**kwargs)
    return run


@dataclass(frozen=True)
class LiveLimits:
    max_eth:D=D('.005')
    max_order_usd:D=D(5)
    max_orders:int=4
    duration_s:int=1800
    max_fee_fraction:D=D('.02')

    def checked(self):
        eth,usd,fee=map(exact,(self.max_eth,self.max_order_usd,self.max_fee_fraction))
        if not 0<eth<=D(1) or not 0<usd<=D(1000) or not 0<fee<D('.05'):raise BetaBlocked('INVALID_LIVE_BETA_CAPS')
        if type(self.max_orders) is not int or not 1<=self.max_orders<=16:raise BetaBlocked('LIVE_ORDER_CAP_OUT_OF_BOUND')
        if type(self.duration_s) is not int or not 60<=self.duration_s<=86400:raise BetaBlocked('LIVE_DURATION_OUT_OF_BOUND')
        return LiveLimits(eth,usd,self.max_orders,self.duration_s,fee)


def _at(value):
    if isinstance(value,bool):raise BetaBlocked('INVALID_LIVE_TIME')
    value=float(value)
    if not math.isfinite(value):raise BetaBlocked('INVALID_LIVE_TIME')
    return value


def _scope(value):
    try:return str(uuid.UUID(value))
    except (ValueError,TypeError,AttributeError):raise BetaBlocked('LIVE_PORTFOLIO_IDENTITY_REQUIRED') from None


def _validate(state):
    if state.get('schema')!=1 or state.get('classification')!='REAL_BETA_SESSION_NOT_TAX_LEDGER' or state.get('mode') not in MODES:
        raise BetaBlocked('INVALID_LIVE_STATE')
    _scope(state['portfolio']);limits=LiveLimits(**state['beta_limits']).checked()
    if not 0<state['initial_eth']<=limits.max_eth:raise BetaBlocked('LIVE_INITIAL_ALLOCATION_INVALID')
    validate_history(state['auto']['global_history'])
    if len(state['orders'])>limits.max_orders or len(state['fills'])>512:raise BetaBlocked('LIVE_HISTORY_LIMIT')
    if any(a not in WATCH_ASSETS or exact(q)<0 for a,q in state['wallet'].items()):raise BetaBlocked('LIVE_WALLET_INVALID')
    active=0;reserved={a:D(0) for a in WATCH_ASSETS};exchange_ids=set()
    for cid,order in state['orders'].items():
        if order['reference']!=cid or order['pair'] not in WATCH_PAIRS or order['side'] not in ('BUY','SELL'):
            raise BetaBlocked('LIVE_ORDER_IDENTITY_INVALID')
        if order['state'] not in TERMINAL|{'RESERVED','SENDING','OPEN','PARTIAL','CANCEL_PENDING','UNKNOWN'}:
            raise BetaBlocked('LIVE_ORDER_STATE_INVALID')
        if type(order.get('reconciliation_unknown',False)) is not bool:raise BetaBlocked('LIVE_RECONCILIATION_FLAG_INVALID')
        if order['order_id'] is not None:
            if order['order_id'] in exchange_ids:raise BetaBlocked('LIVE_DUPLICATE_EXCHANGE_IDENTITY')
            exchange_ids.add(order['order_id'])
        if not 0<=order['filled_base']<=order['base_size'] or not 0<=order['reserved']<=order['source_budget']:
            raise BetaBlocked('LIVE_NATIVE_TOTALS_INVALID')
        if order['state'] in TERMINAL:
            if order['reserved']!=0:raise BetaBlocked('LIVE_TERMINAL_RESERVE_INVALID')
        else:
            active+=1;reserved[order['source']]+=order['reserved'];reserved[order['target']]+=order['received_target']
        if order['global_policy_version']>len(state['auto']['global_history']):raise BetaBlocked('LIVE_ORDER_POLICY_UNKNOWN')
    if active>1 or any(q>state['wallet'].get(a,D(0)) for a,q in reserved.items()):raise BetaBlocked('LIVE_DOUBLE_RESERVATION')
    reference_costs(state)


def upper_usd(frame,reference,asset):
    """Conservative commitment mark, not an exchange/USD trading bridge."""
    ref=usd_reference(frame,reference);stamps=[]
    with localcontext() as ctx:
        ctx.prec=60
        if asset=='ETH':value=ref['ask']
        elif asset=='BTC':
            book=frame.book('ETH-BTC');stamps.append(book[2]);value=ref['ask']/book[0]
        else:
            book=frame.book(asset+'-ETH');stamps.append(book[2]);value=book[1]*ref['ask']
        usd_reference(frame,ref,stamps=stamps)
        return value


class LiveBeta:
    def __init__(self,directory,*,clock=time.time,monotonic=time.monotonic):
        self.directory=Path(directory);self.clock=clock;self.monotonic=monotonic
        self.store=None;self.config=None;self.view_rows={};self.problem=None
        self.blocked=threading.Event();self.blocked.set();self.stop_requested=threading.Event()
        self.last_frame=None;self.last_reference=None;self.account=None;self.permissions_at=None
        self.deadline_mono=None;self.accepted_mono={};self.last_review_mono=None
        self.dispatch_lock=threading.RLock();self._authorized=False
        path=self.directory/'active.sqlite3'
        if path.exists():
            try:
                self.store=BetaStore(path,APP_ID,validate=_validate)
                self.config=AutoConfig(**self.private_state()['auto']['config']).checked()
                self._change('RESTORE',{},lambda s:s.update(mode='RECONCILIATION_REQUIRED',reason='RESTART_BLOCK_ON_RECONCILE_REQUIRED'))
            except (ValueError,TypeError,KeyError,OSError,ArithmeticError):self.problem='LIVE_STORE_REVIEW_REQUIRED'

    def _change(self,kind,payload,action):
        if self.store is None:raise BetaBlocked('NO_LIVE_SESSION')
        return self.store.change(kind,kind.lower()+'_'+uuid.uuid4().hex,payload,action)

    def private_state(self):return None if self.store is None else self.store.state()

    def available(self,asset):
        state=self.private_state()
        if state is None or state['mode'] in ('UNKNOWN_LOCKED','RECONCILIATION_REQUIRED'):return None
        held=sum((o['reserved'] if o['source']==asset else o['received_target'] if o['target']==asset else D(0)
            for o in state['orders'].values() if o['state'] not in TERMINAL),D(0))
        return state['wallet'].get(asset,D(0))-held

    def create(self,limits,settings,*,funding,portfolio,at=None):
        if self.store is not None or self.problem:raise BetaBlocked('EXISTING_LIVE_SESSION_RECONCILE_FIRST')
        now=self.clock() if at is None else _at(at);limits=limits.checked();settings=settings.checked();portfolio=_scope(portfolio)
        approved=eth_funding(now=now,**funding)
        if not approved['valid']:raise BetaBlocked('FRESH_WORKING_ETH_REQUIRED')
        amount=min(limits.max_eth,approved['row']['working']*settings.initial_pct/100)
        if amount<=0:raise BetaBlocked('POSITIVE_LIVE_WORKING_SLICE_REQUIRED')
        cfg=AutoConfig(amount,direction_defaults(),opt_in=True,fee_ceiling=limits.max_fee_fraction).checked()
        state=dict(schema=1,classification='REAL_BETA_SESSION_NOT_TAX_LEDGER',portfolio=portfolio,
            mode='PAUSED',reason='LIVE_SETTINGS_APPLIED_START_REQUIRED',initial_eth=amount,wallet={'ETH':amount},
            beta_limits=asdict(limits),limits=dict(products=WATCH_PAIRS,source_caps={'ETH':amount},max_orders=limits.max_orders,
                max_open_orders=1,expires_at=now+limits.duration_s,max_fee_fraction=limits.max_fee_fraction),
            created_at=now,last_at=now,orders={},fills={},last_sample=None,
            auto=dict(config=cfg.frozen(),global_history=[revision(settings,1,now)],global_initial_slice=True,
                intent_meta={},completed_rotations={},kickoff_reference=None))
        self.store=BetaStore(self.directory/'active.sqlite3',APP_ID,initial=state,validate=_validate)
        self.config=cfg;self.deadline_mono=self.monotonic()+limits.duration_s

    def set_blocked(self,value):
        if type(value) is not bool:raise BetaBlocked('LIVE_SWITCH_REQUIRES_BOOLEAN')
        if value:
            self.blocked.set();self.stop_requested.set();self._authorized=False
        else:self.blocked.clear()

    def start(self,*,at=None):
        now=self.clock() if at is None else _at(at);state=self.private_state()
        if self.blocked.is_set() or state is None or self.problem:raise BetaBlocked('LIVE_ORDERS_BLOCKED')
        if state['mode'] in ('UNKNOWN_LOCKED','RECONCILIATION_REQUIRED'):raise BetaBlocked('LIVE_RECONCILIATION_REQUIRED')
        if any(o['state'] not in TERMINAL for o in state['orders'].values()):raise BetaBlocked('LIVE_OWNED_ORDER_STILL_UNSETTLED')
        if now<state['last_at'] or now>=state['limits']['expires_at']:raise BetaBlocked('LIVE_CLOCK_OR_ORIGINAL_EXPIRY_BLOCKED')
        proposed=self.monotonic()+min(state['beta_limits']['duration_s'],state['limits']['expires_at']-now)
        self.deadline_mono=proposed if self.deadline_mono is None else min(self.deadline_mono,proposed)
        if self.monotonic()>=self.deadline_mono:raise BetaBlocked('LIVE_ORIGINAL_MONOTONIC_DEADLINE')
        self.stop_requested.clear();self._authorized=True
        self._change('START',dict(at=now),lambda s:s.update(mode='ACTIVE',reason='LIVE_BETA_EXPLICIT_START',last_at=now))

    def apply_settings(self,settings,*,at=None):
        now=self.clock() if at is None else _at(at);settings=settings.checked();before=self.private_state()
        if settings_at(before).initial_pct!=settings.initial_pct:raise BetaBlocked('LIVE_FUNDING_FROZEN_FOR_SESSION')
        if settings_at(before)==settings:return len(before['auto']['global_history'])
        def apply(s):
            if now<s['last_at']:raise BetaBlocked('LIVE_TIME_MOVED_BACKWARDS')
            s['auto']['global_history'].append(revision(settings,len(s['auto']['global_history'])+1,now))
            s.update(reason='LIVE_GLOBAL_SETTINGS_APPLIED_FUTURE_INTENTS',last_at=now)
        self._change('APPLY_SETTINGS',dict(settings=settings.frozen(),at=now),apply)
        self.last_review_mono=None;return len(self.private_state()['auto']['global_history'])

    def _eligible(self,state,now):
        if self.blocked.is_set() or self.stop_requested.is_set() or not self._authorized:raise BetaBlocked('LIVE_ORDERS_BLOCKED')
        if state['mode']!='ACTIVE' or self.deadline_mono is None or self.monotonic()>=self.deadline_mono or now>=state['limits']['expires_at']:
            raise BetaBlocked('LIVE_SESSION_NOT_ACTIVE_OR_EXPIRED')

    @native_math
    def prepare(self,frame,reference,*,account):
        """Reserve one fully qualified canonical maker receipt before any POST."""
        now=frame.at;self.last_frame=frame;self.last_reference=deepcopy(reference);self.account=deepcopy(account)
        state=self.private_state();self._eligible(state,now)
        if now<state['last_at']:raise BetaBlocked('LIVE_TIME_MOVED_BACKWARDS')
        if any(o['state'] not in TERMINAL for o in state['orders'].values()):return None
        if len(state['orders'])>=state['beta_limits']['max_orders']:raise BetaBlocked('LIVE_ORDER_BUDGET_EXHAUSTED')
        if not 0<=now-account['at']<=30 or _scope(account['portfolio'])!=state['portfolio']:raise BetaBlocked('LIVE_BALANCE_SCOPE_OR_AGE_INVALID')
        # Available already excludes venue holds. If outside activity consumed
        # the tracked inventory, do not quietly shrink/relabel the discrepancy.
        for asset,owned in state['wallet'].items():
            reported=exact(account['available'].get(asset,D(0)))-exact(account.get('carveouts',{}).get(asset,D(0)))
            if owned>max(D(0),reported):
                self.lock_unknown(None,'LIVE_BALANCE_BELOW_OWNED_FUNDS');return None
        settings=settings_at(state)
        if self.last_review_mono is not None and self.monotonic()-self.last_review_mono<settings.review_s:return None
        self.last_review_mono=self.monotonic()
        try:planning=paper_frame(frame,self.config,planning=True)
        except (ValueError,KeyError,TypeError,ArithmeticError):
            from coincat_paper_policy import DIRECTIONS
            self.view_rows={v['id']:dict(v,state='HOLD',reason='LIVE_CURRENT_MARKET_OR_FEE_EVIDENCE_UNKNOWN_HOLD') for v in DIRECTIONS}
            if state['reason']!='LIVE_CURRENT_MARKET_OR_FEE_EVIDENCE_UNKNOWN_HOLD':
                self._change('HOLD',{},lambda s:s.update(reason='LIVE_CURRENT_MARKET_OR_FEE_EVIDENCE_UNKNOWN_HOLD'))
            return None
        ceilings={}
        for asset in WATCH_ASSETS:
            spendable=account['available'].get(asset,D(0))-account.get('carveouts',{}).get(asset,D(0))
            try:ceilings[asset]=min(max(D(0),spendable),state['beta_limits']['max_order_usd']/upper_usd(planning,reference,asset))
            except (ValueError,KeyError,ArithmeticError):ceilings[asset]=D(0)
        parent=list(state['orders'].values())[-1] if state['orders'] else None
        if parent is not None and parent['state']!='FILLED':
            ceilings[parent['source']]=min(ceilings.get(parent['source'],D(0)),parent['source_budget']-parent['spent_source'])
        rows=global_candidates(self,planning,self.config,settings,reference,kickoff=initial_campaign(state),budget_limits=ceilings)
        self.view_rows=rows
        if parent and parent['state']!='FILLED' and now>=parent['campaign_deadline']:
            for row in rows.values():
                if row['source']==parent['source']:row['state']='HOLD'
        candidates=[r for r in rows.values() if r['state']=='CANDIDATE']
        if not candidates:
            if state['reason']!='LIVE_PROFIT_UNKNOWN_OR_BELOW_TARGET_HOLD':
                self._change('HOLD',{},lambda s:s.update(reason='LIVE_PROFIT_UNKNOWN_OR_BELOW_TARGET_HOLD'))
            return None
        selected=max(candidates,key=lambda r:(r['priority'],r['score'],r['id']))
        cid=str(uuid.uuid4());budget=selected['source_budget'];plan=selected['plan'];version=len(state['auto']['global_history'])
        expiry=state['limits']['expires_at']
        if parent and parent['state']!='FILLED' and parent['source']==selected['source']:expiry=min(expiry,parent['campaign_deadline'])
        def reserve(s):
            self._eligible(s,now)
            if any(o['state'] not in TERMINAL for o in s['orders'].values()):raise BetaBlocked('LIVE_OPEN_ORDER_LIMIT')
            if len(s['orders'])>=s['beta_limits']['max_orders']:raise BetaBlocked('LIVE_ORDER_BUDGET_EXHAUSTED')
            if version!=len(s['auto']['global_history']):raise BetaBlocked('LIVE_SETTINGS_CHANGED_REFRESH')
            maximum=source_budget(s,self.available(selected['source']),selected,settings,initial=initial_campaign(s))
            if budget>maximum or budget>ceilings[selected['source']]:raise BetaBlocked('LIVE_SOURCE_CAP_EXCEEDED')
            proof=qualification(s,planning,plan,budget,reference,settings)
            if proof['state']!='CONDITIONAL_QUALIFIED':raise BetaBlocked('LIVE_PROFIT_NOT_QUALIFIED')
            proof['classification']='CONDITIONAL_LIVE_BETA_ESTIMATE_NOT_REALIZED_PROFIT'
            record=dict(reference=cid,client_order_id=cid,order_id=None,pair=selected['pair'],side=selected['side'],
                source=selected['source'],target=selected['target'],source_budget=budget,reserved=budget,
                state='RESERVED',base_size=plan['gross_base_quantity'],limit_price=selected['limit_price'],
                price_increment=exact(frame._rules[selected['pair']].get('price_increment',frame._rules[selected['pair']]['quote_increment'])),
                filled_base=D(0),spent_source=D(0),received_target=D(0),created_at=now,accepted_at=None,
                expires_at=min(now+settings.reconsider_s,expiry),campaign_deadline=expiry,
                global_policy_version=version,qualification=proof,post_only=True,dispatch_count=0,cancel_count=0,
                last_cancel_at=None,last_checked_at=None,plan_receipt=deepcopy(plan),initial_slice_order=initial_campaign(s))
            s['orders'][cid]=record
            if selected['target'] not in s['limits']['source_caps']:s['limits']['source_caps'][selected['target']]=plan['output_quantity']
            s['auto']['intent_meta'][cid]=dict(direction=selected['id'])
            s.update(reason='LIVE_QUALIFIED_RESERVATION_NOT_A_FILL',last_at=now)
        self._change('RESERVE',dict(client_order_id=cid,version=version),reserve)
        return cid

    def claim(self,cid):
        now=self.clock();state=self.private_state();self._eligible(state,now)
        if self.last_frame is None or not 0<=now-self.last_frame.at<=30:raise BetaBlocked('LIVE_FRAME_STALE')
        if self.account is None or not 0<=now-self.account['at']<=30:raise BetaBlocked('LIVE_BALANCE_STALE')
        def claim(s):
            self._eligible(s,now);order=s['orders'].get(cid)
            if not order or order['state']!='RESERVED' or order['dispatch_count']!=0:raise BetaBlocked('LIVE_DISPATCH_ALREADY_CLAIMED_OR_UNKNOWN')
            if order['global_policy_version']!=len(s['auto']['global_history']):raise BetaBlocked('LIVE_SETTINGS_CHANGED_REFRESH')
            if order['expires_at']<=now:raise BetaBlocked('LIVE_CHILD_ORIGINAL_EXPIRY')
            order.update(state='SENDING',dispatch_count=1,sent_at=now)
            return deepcopy(order)
        return self._change('CLAIM_DISPATCH',dict(client_order_id=cid),claim)

    def sent_result(self,cid,response,*,definitely_not_sent=False):
        now=self.clock()
        def accept(s):
            order=s['orders'][cid]
            if definitely_not_sent:
                order.update(state='REJECTED',reserved=D(0));s['reason']='LIVE_LOCAL_RECHECK_REJECTED_NO_POST';return
            oid=(response.get('success_response') or {}).get('order_id') if isinstance(response,dict) else None
            if oid and response.get('success') is True:
                oid=_scope(oid)
                if any(ref!=cid and prior['order_id']==oid for ref,prior in s['orders'].items()):
                    order['state']='UNKNOWN';s.update(mode='UNKNOWN_LOCKED',reason='LIVE_DUPLICATE_EXCHANGE_ORDER_ID');return
                order.update(order_id=_scope(oid),state='OPEN',accepted_at=now,
                    expires_at=min(now+settings_at(s,order['global_policy_version']).reconsider_s,order['campaign_deadline']))
                self.accepted_mono[cid]=self.monotonic();s['reason']='LIVE_ORDER_ACKNOWLEDGED_NOT_A_FILL'
            elif isinstance(response,dict) and response.get('success') is False and not oid:
                order.update(state='REJECTED',reserved=D(0));s['reason']='LIVE_POST_ONLY_REJECTED_NO_FALLBACK'
            else:
                order['state']='UNKNOWN';s.update(mode='UNKNOWN_LOCKED',reason='LIVE_PLACEMENT_UNKNOWN_NO_RETRY')
        self._change('PLACEMENT_RESULT',dict(client_order_id=cid,response=response),accept)
        if self.private_state()['mode']=='UNKNOWN_LOCKED':
            self.blocked.set();self.stop_requested.set();self._authorized=False

    def placement_unknown(self,cid):
        self.blocked.set();self.stop_requested.set();self._authorized=False
        self.sent_result(cid,{})

    def lock_unknown(self,cid,reason='LIVE_RECONCILIATION_UNKNOWN'):
        allowed={'LIVE_CANCEL_IDENTITY_MISMATCH','LIVE_CANCEL_RESPONSE_UNCERTAIN','LIVE_FILL_EVIDENCE_INCOMPLETE',
            'LIVE_ORDER_OR_FILL_CONFLICT','LIVE_FEE_UNITS_UNKNOWN','LIVE_RECONCILIATION_UNKNOWN','LIVE_BALANCE_BELOW_OWNED_FUNDS'}
        reason=reason if reason in allowed else 'LIVE_RECONCILIATION_UNKNOWN'
        self.blocked.set();self.stop_requested.set();self._authorized=False
        def lock(s):
            if cid in s['orders']:
                s['orders'][cid]['reconciliation_unknown']=True
                if s['orders'][cid]['state'] not in TERMINAL:s['orders'][cid]['state']='UNKNOWN'
            s.update(mode='UNKNOWN_LOCKED',reason=reason)
        self._change('LOCK_UNKNOWN',dict(reference=cid,reason=reason),lock)

    def claim_cancel(self,cid):
        now=self.clock();state=self.private_state();order=state['orders'].get(cid)
        if not order or order['state'] in TERMINAL:return None
        if not order['order_id']:raise BetaBlocked('LIVE_PLACEMENT_UNKNOWN_REQUIRES_IDENTITY_RECOVERY')
        if order['cancel_count']>=3:return None
        if order['last_cancel_at'] is not None and now-order['last_cancel_at']<30:return None
        def claim(s):
            item=s['orders'][cid]
            if item['state'] in TERMINAL:return None
            item.update(state='CANCEL_PENDING',cancel_count=item['cancel_count']+1,last_cancel_at=now)
            s['reason']='LIVE_CANCEL_REQUEST_NOT_TERMINAL_CONFIRMATION'
            return deepcopy(item)
        return self._change('CLAIM_CANCEL',dict(reference=cid,at=now),claim)

    def cancel_result(self,cid,response):
        # Even success=True is only acknowledgment of a REQUEST. Keep reserves.
        self._change('CANCEL_RESPONSE',dict(reference=cid,response=response),
            lambda s:s.update(reason='LIVE_CANCEL_REQUEST_ACK_AWAIT_TERMINAL_AND_FILLS'))

    def recover_identity(self,cid,actual):
        state=self.private_state();order=state['orders'][cid]
        if (actual.get('client_order_id')!=cid or actual.get('product_id')!=order['pair'] or
                actual.get('side')!=order['side'] or _scope(actual.get('retail_portfolio_id'))!=state['portfolio']):
            raise BetaBlocked('LIVE_RECOVERY_IDENTITY_MISMATCH')
        oid=_scope(actual.get('order_id'))
        def record(s):
            item=s['orders'][cid]
            if item['order_id'] is not None and item['order_id']!=oid:raise BetaBlocked('LIVE_RECOVERY_IDENTITY_CONFLICT')
            item['order_id']=oid
            s['reason']='LIVE_IDENTITY_RECOVERED_RECONCILE_BEFORE_START'
        self._change('RECOVER_IDENTITY',dict(reference=cid,order_id=oid),record)

    @native_math
    def reconcile_order(self,cid,actual,fills,*,complete):
        """Actual native receipts once, with exact order totals before unlocking."""
        state=self.private_state();order=state['orders'][cid];now=self.clock()
        try:
            if (actual.get('order_id')!=order['order_id'] or actual.get('client_order_id')!=cid or
                    actual.get('retail_portfolio_id')!=state['portfolio'] or actual.get('product_id')!=order['pair'] or
                    actual.get('side')!=order['side'] or complete is not True):
                raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
            from coincat_manual_trade import fill_count
            expected=fill_count(actual.get('number_of_fills'))
            if not isinstance(fills,list) or expected!=len(fills) or not 0<=expected<=512:raise BetaBlocked('LIVE_FILL_EVIDENCE_INCOMPLETE')
            if fills:
                totals=summarize_fills(fills,order_id=order['order_id'],pair=order['pair'],side=order['side'])
                verify_order_totals(actual,totals)
            else:totals=dict(base_qty=D(0),quote_qty=D(0),fees=D(0))
            for field,key in (('filled_size','base_qty'),('filled_value','quote_qty'),('total_fees','fees')):
                if exact(actual.get(field))!=totals[key]:raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
            exchange_state=actual.get('status')
            terminal=exchange_state in ('FILLED','COMPLETED','CANCELED','CANCELLED','EXPIRED','FAILED','REJECTED')
            if exchange_state in ('FILLED','COMPLETED') and totals['base_qty']!=order['base_size']:
                raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
            normalized=[]
            from coincat_manual_trade import explicit_fee_currency,explicit_size_flag,fill_identity
            from coincat_order_book import utc_stamp
            for raw in sorted(fills,key=lambda f:(f.get('trade_time',''),str(f.get('trade_id','')))):
                if (raw.get('retail_portfolio_id')!=state['portfolio'] or raw.get('order_id')!=order['order_id'] or
                        raw.get('product_id')!=order['pair'] or raw.get('side')!=order['side']):
                    raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                if explicit_fee_currency(raw)!=order['pair'].split('-')[1]:raise BetaBlocked('LIVE_FEE_UNITS_UNKNOWN')
                explicit_size_flag(raw.get('size_in_quote'))
                if raw.get('liquidity_indicator') not in ('M','MAKER'):raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                at=utc_stamp(raw.get('trade_time'));n=normalize_fill(raw)
                if (at<order['created_at'] or (order['side']=='BUY' and n['price']>order['limit_price']) or
                        (order['side']=='SELL' and n['price']<order['limit_price']) or
                        n['commission']>n['quote_qty']*state['beta_limits']['max_fee_fraction']):
                    raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                tid=fill_identity(raw.get('trade_id'));normalized.append((tid,deepcopy(raw),n,at))
            def settle(s):
                item=s['orders'][cid]
                for tid,raw,n,at in normalized:
                    existing=s['fills'].get(tid)
                    if existing:
                        if existing['fingerprint']!=digest(raw):raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                        continue
                    qty,gross,fee=n['base_qty'],n['quote_qty'],n['commission']
                    debit=gross+fee if item['side']=='BUY' else qty
                    credit=qty if item['side']=='BUY' else gross-fee
                    if credit<0 or debit>item['reserved'] or debit>s['wallet'].get(item['source'],D(0)):
                        raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                    s['wallet'][item['source']]-=debit;s['wallet'][item['target']]=s['wallet'].get(item['target'],D(0))+credit
                    item['reserved']-=debit;item['spent_source']+=debit;item['received_target']+=credit;item['filled_base']+=qty
                    s['fills'][tid]=dict(reference=cid,raw=dict(raw,at=at,fee_currency=explicit_fee_currency(raw)),
                        fingerprint=digest(raw),settled=True,source=item['source'],target=item['target'],debit=debit,credit=credit,
                        settle_index=len(s['fills'])+1,classification='AUTHENTICATED_EXCHANGE_FILL')
                if item['filled_base']!=totals['base_qty']:raise BetaBlocked('LIVE_ORDER_OR_FILL_CONFLICT')
                if terminal:
                    item.update(state='FILLED' if exchange_state in ('FILLED','COMPLETED') else 'REJECTED' if exchange_state in ('FAILED','REJECTED') and not item['filled_base'] else 'CANCELED',reserved=D(0))
                else:item['state']='CANCEL_PENDING' if item['cancel_count'] else 'PARTIAL' if item['filled_base'] else 'OPEN'
                item['reconciliation_unknown']=False
                item['last_checked_at']=now;s['last_at']=max(now,s['last_at']);s['reason']='LIVE_NATIVE_RECEIPTS_RECONCILED'
            self._change('RECONCILE_ORDER',dict(reference=cid,order=actual,fills=fills),settle)
            return True
        except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError) as error:
            reason=str(error) if isinstance(error,BetaBlocked) else 'LIVE_ORDER_OR_FILL_CONFLICT'
            def retain(s):
                history=s.setdefault('unresolved_evidence',{}).setdefault(cid,[])
                item=dict(order=deepcopy(actual),fills=deepcopy(fills))
                if not history or digest(history[-1]['evidence'])!=digest(item):
                    if len(history)>=32:raise BetaBlocked('LIVE_UNRESOLVED_EVIDENCE_BOUND')
                    history.append(dict(at=now,evidence=item))
            self._change('UNRESOLVED_EVIDENCE',dict(reference=cid,order=actual,fills=fills),retain)
            self.lock_unknown(cid,reason);return False

    def finish_reconciliation(self):
        state=self.private_state()
        if any(o['state'] not in TERMINAL or o.get('reconciliation_unknown') for o in state['orders'].values()):raise BetaBlocked('LIVE_OWNED_ORDER_STILL_UNSETTLED')
        self.blocked.set();self.stop_requested.set();self._authorized=False
        self._change('RECONCILED_PAUSED',{},lambda s:s.update(mode='PAUSED',reason='LIVE_RECONCILED_BLOCK_ON_EXPLICIT_START_REQUIRED'))

    def sample(self,frame,reference):
        state=self.private_state()
        reports=completed_reports(state,frame,reference)
        # Same canonical lineage; the output is REAL settled slices, not paper.
        for report in reports.values():report['classification']='REAL_SETTLED_ETH_RETURN_SLICE_NOT_TAX_PROFIT'
        from coincat_paper_policy import eth_mark
        try:marked=eth_mark(state['wallet'],frame)
        except (ValueError,KeyError,ArithmeticError):marked=None
        def sample(s):
            for key,prior in s['auto']['completed_rotations'].items():
                if reports.get(key)!=prior:raise BetaBlocked('LIVE_COMPLETION_RESULT_IMMUTABLE')
            s['auto']['completed_rotations']=reports
            s['last_sample']=dict(at=frame.at,marked_eth=marked,hold_eth=s['initial_eth'],
                delta_eth=None if marked is None else marked-s['initial_eth'],basis='MIDPOINT_REFERENCE_BEFORE_EXIT_COSTS')
        self._change('SAMPLE',dict(at=frame.at),sample)

    def public(self):
        state=self.private_state()
        return dict(blocked=self.blocked.is_set(),state='UNAVAILABLE' if self.problem else 'OFF' if state is None else state['mode'],
            orders=0 if state is None else len(state['orders']),fills=0 if state is None else len(state['fills']),
            unresolved=0 if state is None else sum(o['state'] not in TERMINAL or bool(o.get('reconciliation_unknown')) for o in state['orders'].values()),
            settings_version=0 if state is None else len(state['auto']['global_history']),
            classification='REAL_BETA_EXECUTION',profit='NOT_ESTABLISHED',provider='COINBASE_LIMIT_POST_ONLY',
            reason=self.problem or ('LIVE_BLOCK_ON_STARTUP' if state is None else state['reason']))
