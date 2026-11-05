"""Explicit manual LIMIT orders. No strategy, paper wallet or automatic submit.

The private journal owns identities, not account inventory. Every submission is
one operator click; unknown POST results can only be recovered, never replayed.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal as D,localcontext
from pathlib import Path
import threading
import time
import uuid

from coincat_beta_store import BetaStore,BetaBlocked,digest
from coincat_execution_limits import LiveLimits,native_math
from coincat_manual_trade import identity
from coincat_order_services import LimitOrderServices,PortfolioInventory,ticket_values,bind_owned_order
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS

APP_ID=0x4343534D
TERMINAL={'FILLED','CANCELED','REJECTED'}
STATES=TERMINAL|{'SENDING','UNKNOWN','OPEN','PARTIAL','CANCEL_PENDING'}


def validate(state):
    if state.get('schema')!=1 or state.get('classification')!='MANUAL_REAL_LIMIT_NOT_TAX_LEDGER':
        raise BetaBlocked('INVALID_MANUAL_EXECUTION_JOURNAL')
    limits=LiveLimits(**state['limits']).checked()
    if len(state['orders'])>limits.max_orders:raise BetaBlocked('MANUAL_ORDER_CAP')
    if state['portfolio'] is not None:identity(state['portfolio'])
    ids=set();active=0
    for cid,o in state['orders'].items():
        identity(cid)
        if (o['cid']!=cid or o['pair'] not in WATCH_PAIRS or o['side'] not in ('BUY','SELL') or
                type(o['post_only']) is not bool or o['state'] not in STATES):raise BetaBlocked('INVALID_MANUAL_ORDER')
        if not 0<=exact(o['filled'])<=exact(o['size']) or exact(o['size'])<=0 or exact(o['price'])<=0:
            raise BetaBlocked('INVALID_MANUAL_ORDER_AMOUNTS')
        if o['order_id'] is not None:
            oid=identity(o['order_id'])
            if oid in ids:raise BetaBlocked('DUPLICATE_MANUAL_ORDER_ID')
            ids.add(oid)
        active+=o['state'] not in TERMINAL
        if len(o['fills'])>512:raise BetaBlocked('MANUAL_FILL_BOUND')
    if active>1:raise BetaBlocked('ONE_MANUAL_ORDER_AT_A_TIME')


class ManualExecution:
    def __init__(self,path,reader,*,clock=time.time,legacy_pending=lambda:False):
        self.reader=reader;self.client=reader.client;self.clock=clock;self.legacy_pending=legacy_pending
        self.block=threading.Event();self.block.set();self.dispatch_lock=threading.Lock()
        self.store=BetaStore(Path(path),APP_ID,initial=dict(schema=1,classification='MANUAL_REAL_LIMIT_NOT_TAX_LEDGER',
            portfolio=None,started=None,limits=asdict(LiveLimits()),orders={}),validate=validate)
        self.services=LimitOrderServices(lambda:self.reader,clock=clock,
            manual_guard=lambda cid:not self.block.is_set() and not self.expired() and
                self.state()['orders'].get(cid,{}).get('state')=='SENDING',
            owned_guard=lambda cid,oid:oid is not None and self.state()['orders'].get(cid,{}).get('order_id')==oid)
        # Any interrupted dispatch is ambiguous on restart. Never resubmit it.
        if any(o['state']=='SENDING' for o in self.state()['orders'].values()):
            self._change('RESTART_LOCK',{},lambda s:[o.update(state='UNKNOWN') for o in s['orders'].values() if o['state']=='SENDING'])

    def state(self):return self.store.state()
    def expired(self):
        state=self.state()
        return state['started'] is not None and not 0<=self.clock()-state['started']<state['limits']['duration_s']
    def _change(self,kind,payload,action):return self.store.change(kind,uuid.uuid4().hex,payload,action)
    def set_blocked(self,blocked):
        if type(blocked) is not bool:raise BetaBlocked('INVALID_LIVE_BLOCK')
        if blocked:self.block.set()
        else:
            if self.expired():raise BetaBlocked('SESSION_EXPIRED_ARCHIVE_COMPLETED_ORDERS_BEFORE_NEW_SESSION')
            if any(o['state'] in ('SENDING','UNKNOWN','CANCEL_PENDING') for o in self.state()['orders'].values()):
                raise BetaBlocked('RECONCILE_PENDING_ORDER_BEFORE_UNBLOCKING')
            if self.legacy_pending():raise BetaBlocked('OLDER_LIVE_SESSION_REQUIRES_RECONCILIATION')
            self.block.clear()

    def configure(self,limits):
        limits=limits.checked()
        with self.dispatch_lock:
            if self.state()['orders']:raise BetaBlocked('SESSION_LIMITS_FROZEN_AFTER_FIRST_SUBMISSION')
            self._change('LIMITS',asdict(limits),lambda s:s.update(limits=asdict(limits)))

    def new_session(self):
        """Explicit owner action only; keep the entire completed journal."""
        with self.dispatch_lock:
            self.block.set();state=self.state()
            if any(o['state'] not in TERMINAL for o in state['orders'].values()):
                raise BetaBlocked('RECONCILE_ALL_ORDERS_BEFORE_NEW_SESSION')
            if not state['orders']:return
            path=self.store.path
            archive=path.with_name('completed-'+uuid.uuid4().hex+'.sqlite3')
            if archive.exists() or path.is_symlink() or path.parent.is_symlink():raise BetaBlocked('SESSION_ARCHIVE_PATH_REJECTED')
            path.rename(archive);self.store.path=archive
            self.store=BetaStore(path,APP_ID,initial=dict(schema=1,classification='MANUAL_REAL_LIMIT_NOT_TAX_LEDGER',
                portfolio=None,started=None,limits=deepcopy(state['limits']),orders={}),validate=validate)
            self.block.set()

    def _fresh(self,*values):
        if any(not 0<=self.clock()-v<=30 for v in values):raise BetaBlocked('REFRESH_STALE_MANUAL_PREFLIGHT')

    @native_math
    def _preflight(self,ticket):
        r=self.reader;r.begin();scope=r.scope(trading=True);account=r.balances(scope)
        rules=r.product(ticket.get('pair'),force=True);book=r.book(ticket['pair'])
        t=ticket_values(ticket,rules,book);tier=r.fees(force=True);fx=r.fx(t['pair'].split('-')[1])
        s=self.state();limits=LiveLimits(**s['limits']).checked()
        if s['portfolio'] is not None and scope!=s['portfolio']:raise BetaBlocked('MANUAL_SESSION_PORTFOLIO_CHANGED')
        if s['started'] is not None and not 0<=self.clock()-s['started']<limits.duration_s:
            self.block.set();raise BetaBlocked('MANUAL_SESSION_EXPIRED')
        if self.legacy_pending():raise BetaBlocked('OLDER_LIVE_SESSION_REQUIRES_RECONCILIATION')
        if any(o['state'] not in TERMINAL for o in s['orders'].values()):raise BetaBlocked('RECONCILE_OR_CANCEL_CURRENT_ORDER_FIRST')
        if len(s['orders'])>=limits.max_orders:raise BetaBlocked('MANUAL_SESSION_ORDER_CAP_REACHED')
        parent=identity(ticket['replaces']) if ticket.get('replaces') is not None else None
        if parent is not None:
            prior=s['orders'].get(identity(parent))
            if (prior is None or prior['state']!='CANCELED' or prior['report'] is None or
                    any(o.get('replaces')==parent for o in s['orders'].values()) or
                    any(t[k]!=prior[k] for k in ('pair','side','post_only')) or t['size']!=prior['size']-prior['filled']):
                raise BetaBlocked('REPLACEMENT_MUST_USE_ONLY_ONCE_CONFIRMED_REMAINING_SIZE')
        rate=tier['maker'] if t['post_only'] else max(tier['maker'],tier['taker'])
        if rate>limits.max_fee_fraction:raise BetaBlocked('ACCOUNT_FEE_RATE_EXCEEDS_SESSION_CEILING')
        base,quote=t['pair'].split('-');source=base if t['side']=='SELL' else quote
        with localcontext() as context:
            context.prec=80
            gross=t['size']*t['price'];reserve=(t['size'] if t['side']=='SELL' else gross)*(1+limits.max_fee_fraction)
            if PortfolioInventory(account).available(source)<reserve:raise BetaBlocked('INSUFFICIENT_AVAILABLE_SOURCE_INCLUDING_FEE_BUFFER')
            # A low SELL limit cannot evade the cap by undervaluing its source.
            exposure=t['size']*(max(t['price'],book['ask']) if t['side']=='SELL' else t['price'])*(1+limits.max_fee_fraction)
            usd=exposure*fx['usd_upper'];eth=exposure*fx['eth_upper']
            charged=sum((o['risk_eth']*(o['filled']/o['size'] if o['state'] in TERMINAL else 1)
                for o in s['orders'].values()),D(0))
            if usd>limits.max_order_usd:raise BetaBlocked('ORDER_EXCEEDS_VISIBLE_USD_CAP_REDUCE_AMOUNT')
            if charged+eth>limits.max_eth:raise BetaBlocked('ORDER_EXCEEDS_REMAINING_ETH_EQUIVALENT_SESSION_CAP')
        self._fresh(account['at'],book['at'],fx['at'],r.permissions['at'],tier['at'])
        return t,dict(portfolio=scope,at=self.clock(),risk_eth=eth,risk_usd=usd,rate=rate,
            fee_quote_estimate=gross*rate,source=source,reserve=reserve,book=book,account_at=account['at'],fx_at=fx['at'])

    @native_math
    def submit(self,ticket,click_id):
        """Called only by the explicit Buy/Sell button; never by a timer."""
        cid=identity(click_id)
        with self.dispatch_lock:
            if cid in self.state()['orders']:
                old=self.state()['orders'][cid]
                if any(ticket.get(k)!=old[k] for k in ('pair','side','post_only')) or any(exact(ticket.get(k))!=old[k] for k in ('size','price')):
                    raise BetaBlocked('CONFLICTING_MANUAL_CLICK_ID')
                return deepcopy(old)
            if self.block.is_set():raise BetaBlocked('LIVE_ORDERS_BLOCKED_SWITCH_IS_ON')
            t,evidence=self._preflight(ticket)
            # SDK 1.8.4 uses requests.Session with zero retries. Refuse an
            # externally replaced adapter that might replay a create POST.
            self.services.check_no_retries()
            try:
                preview=self.services.preview(t,evidence['portfolio'])
                if not isinstance(preview.get('errs'),list) or preview['errs']:raise BetaBlocked('EXCHANGE_PREVIEW_REJECTED_TICKET')
                if exact(preview.get('base_size'))!=t['size']:raise BetaBlocked('EXCHANGE_PREVIEW_SIZE_CONFLICT')
                fee=exact(preview.get('commission_total'))
                if not 0<=fee<=t['size']*t['price']*LiveLimits(**self.state()['limits']).checked().max_fee_fraction:
                    raise BetaBlocked('EXCHANGE_PREVIEW_FEE_EXCEEDS_BUFFER')
            except BetaBlocked:raise
            except Exception:raise BetaBlocked('PREVIEW_UNAVAILABLE_NO_ORDER_WAS_SENT') from None
            self._fresh(evidence['at'],evidence['account_at'],evidence['book']['at'],evidence['fx_at'])
            if self.block.is_set():raise BetaBlocked('STOPPED_BEFORE_ORDER_DISPATCH')
            order=dict(**t,cid=cid,order_id=None,state='SENDING',at=self.clock(),filled=D(0),fills=[],
                replaces=identity(ticket['replaces']) if ticket.get('replaces') is not None else None,
                risk_eth=evidence['risk_eth'],risk_usd=evidence['risk_usd'],report=None,record=None,
                preview_fee=fee,preview_fee_currency='ESTIMATED_QUOTE_MODEL_NOT_REPORTED_COMMISSION_UNIT')
            def reserve(s):
                s['portfolio']=evidence['portfolio']
                if s['started'] is None:s['started']=self.clock()
                s['orders'][cid]=deepcopy(order)
            self._change('EXPLICIT_MANUAL_CLICK',order,reserve)
            if self.block.is_set():
                self._change('STOP_BEFORE_POST',dict(cid=cid),lambda s:s['orders'][cid].update(state='REJECTED'))
                raise BetaBlocked('STOPPED_BEFORE_ORDER_DISPATCH')
            try:
                grant=self.services.manual_grant(cid,t,evidence['portfolio'])
                ack=self.services.create(t,evidence['portfolio'],grant)
                if ack.get('success') is False and isinstance(ack.get('error_response'),dict) and ack['error_response']:
                    self._change('EXCHANGE_REJECTED',dict(cid=cid),lambda s:s['orders'][cid].update(state='REJECTED'))
                else:
                    data=ack.get('success_response') or {};oid=identity(data.get('order_id'))
                    if ack.get('success') is not True or data.get('client_order_id')!=cid:
                        raise BetaBlocked('CREATE_ACK_IDENTITY_UNVERIFIED')
                    if any(data.get(k,t[k])!=t[k] for k in ('side',)) or data.get('product_id',t['pair'])!=t['pair']:
                        raise BetaBlocked('CREATE_ACK_PRODUCT_UNVERIFIED')
                    self._change('ACKNOWLEDGED',dict(cid=cid,oid=oid),lambda s:s['orders'][cid].update(order_id=oid,state='OPEN'))
            except Exception:
                self.block.set()
                self._change('AMBIGUOUS_CREATE_LOCK',dict(cid=cid),lambda s:s['orders'][cid].update(state='UNKNOWN'))
                raise BetaBlocked('ORDER_RESULT_UNKNOWN_DO_NOT_RESUBMIT_REFRESH_TO_RECOVER') from None
            if self.block.is_set():self.cancel(cid)
            return self.state()['orders'][cid]

    def _history(self,oid,portfolio):
        return self.services.history(oid,portfolio)

    def _bind(self,o,raw):
        bind_owned_order(o,raw,self.state()['portfolio'])

    @native_math
    def reconcile(self,cid):
        o=self.state()['orders'][identity(cid)];self.reader.begin()
        if self.reader.scope()!=self.state()['portfolio']:raise BetaBlocked('MANUAL_SESSION_PORTFOLIO_CHANGED')
        if o['order_id'] is None:
            if o['state']=='REJECTED':return o
            found=[];cursor=None;seen=set()
            for _ in range(4):
                args=dict(product_ids=[o['pair']],product_type='SPOT',retail_portfolio_id=self.state()['portfolio'],limit=100)
                if cursor:args['cursor']=cursor
                page=self.reader.call('list_orders',**args)
                rows=page.get('orders')
                if not isinstance(rows,list) or len(rows)>100:raise BetaBlocked('RECOVERY_HISTORY_UNAVAILABLE')
                found.extend(r for r in rows if r.get('client_order_id')==cid)
                if page.get('has_next') is False or (page.get('has_next') is None and not page.get('cursor')):break
                cursor=page.get('cursor')
                if not isinstance(cursor,str) or not cursor or cursor in seen:break
                seen.add(cursor)
            if len(found)!=1:raise BetaBlocked('UNKNOWN_ORDER_REMAINS_LOCKED_NO_SAFE_RETRY')
            self._bind(o,found[0]);oid=identity(found[0].get('order_id'))
            self._change('RECOVERED_ID',dict(cid=cid,oid=oid),lambda s:s['orders'][cid].update(order_id=oid))
            o=self.state()['orders'][cid]
        record=self._history(o['order_id'],self.state()['portfolio']);self._bind(o,record['order'])
        report=record['report'];filled=report['base_qty']
        old={f['trade_id']:f for f in o['fills']};new={f['trade_id']:f for f in record['fills']}
        if (not record['complete'] or report['coverage']!='COMPLETE_AS_REPORTED' or filled is None or
                not o['filled']<=filled<=o['size'] or any(k not in new or digest(v)!=digest(new[k]) for k,v in old.items())):
            self.block.set();raise BetaBlocked('ORDER_QUANTITY_OR_FILL_COVERAGE_UNCERTAIN_RETRY_READ_ONLY')
        state={'CANCELED_PARTIAL':'CANCELED','CANCELED_UNFILLED':'CANCELED'}.get(report['state'],report['state'])
        if state not in TERMINAL|{'OPEN','PARTIAL'} or (state=='FILLED' and filled!=o['size']):
            self.block.set();raise BetaBlocked('ORDER_TERMINAL_OR_QUANTITY_STATE_UNVERIFIED')
        if o['state'] in TERMINAL and (o['state']!=state or o['filled']!=filled):
            self.block.set();raise BetaBlocked('TERMINAL_ORDER_CHANGED_RECONCILIATION_REQUIRED')
        self._change('EXCHANGE_RECONCILIATION',dict(cid=cid,record=record),lambda s:s['orders'][cid].update(
            state=state,filled=filled,fills=deepcopy(record['fills']),report=deepcopy(report),record=deepcopy(record)))
        return self.state()['orders'][cid]

    def cancel(self,cid):
        cid=identity(cid);o=self.state()['orders'][cid]
        if o['state'] in TERMINAL:return o
        # Cancellation remains available when live creation is blocked.
        if o['order_id'] is None:o=self.reconcile(cid)
        if o['state'] in TERMINAL:return o
        self.reader.begin()
        if self.reader.scope()!=self.state()['portfolio']:raise BetaBlocked('MANUAL_SESSION_PORTFOLIO_CHANGED')
        observed=self.reader.call('get_order',order_id=o['order_id']).get('order')
        if not isinstance(observed,dict) or observed.get('order_id')!=o['order_id']:raise BetaBlocked('CANCEL_ORDER_IDENTITY_UNVERIFIED')
        self._bind(o,observed)
        if observed.get('status') in ('FILLED','COMPLETED','CANCELED','CANCELLED','EXPIRED','FAILED','REJECTED'):
            return self.reconcile(cid)
        self._change('EXPLICIT_CANCEL',dict(cid=cid),lambda s:s['orders'][cid].update(state='CANCEL_PENDING'))
        try:
            result=self.services.cancel_owned(o)
            rows=result.get('results')
            if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('order_id')!=o['order_id']:
                raise BetaBlocked('CANCEL_ACK_UNVERIFIED')
        except Exception:
            self.block.set();raise BetaBlocked('CANCEL_RESULT_UNCERTAIN_REFRESH_TO_RECONCILE') from None
        # Even a successful cancel acknowledgment is not settlement evidence.
        return self.reconcile(cid)

    @native_math
    def remaining_ticket(self,cid):
        cid=identity(cid)
        o=self.state()['orders'][identity(cid)]
        if o['state']!='CANCELED' or o['report'] is None or o['report']['coverage']!='COMPLETE_AS_REPORTED':
            raise BetaBlocked('CONFIRM_TERMINAL_CANCELLATION_BEFORE_REPLACEMENT')
        remaining=o['size']-o['filled']
        if remaining<=0:raise BetaBlocked('NO_UNFILLED_SIZE_TO_REPLACE')
        self.reader.begin();book=self.reader.book(o['pair'])
        return dict(pair=o['pair'],side=o['side'],post_only=o['post_only'],size=remaining,
            replaces=cid,
            price=book['bid'] if o['side']=='BUY' and o['post_only'] else book['ask'])

    def poll(self):
        s=self.state()
        if s['started'] is not None and not 0<=self.clock()-s['started']<s['limits']['duration_s']:self.block.set()
        for cid,o in s['orders'].items():
            if o['state'] not in TERMINAL:
                if self.block.is_set():self.cancel(cid)
                else:self.reconcile(cid)
        return self.state()

    def public(self):
        orders=list(self.state()['orders'].values());pending=sum(o['state'] not in TERMINAL for o in orders)
        return dict(blocked=self.block.is_set(),state='UNKNOWN_LOCKED' if any(o['state'] in ('UNKNOWN','SENDING','CANCEL_PENDING') for o in orders)
            else 'EXPIRED' if self.expired() else 'RESTING' if pending else 'BLOCKED' if self.block.is_set() else 'READY',orders=len(orders),
            fills=sum(len(o['fills']) for o in orders),unresolved=pending,
            completed=sum(o['state']=='FILLED' for o in orders),canceled=sum(o['state']=='CANCELED' for o in orders),
            provider='COINBASE_MANUAL_LIMIT_GTC',automation=False,profit='NOT_ASSESSED')
