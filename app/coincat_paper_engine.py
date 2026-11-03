"""Paper-only post-only lifecycle driven by explicit simulation/replay events.

No Coinbase client, network, credentials, production ledger or live authorization.
Planning uses research_order; fill units use the existing normalize_fill primitive.
Native settlement here applies explicitly supplied simulated executions, never BBO
inference. Private SQLite state is separate from every financial/research database.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass,asdict
from decimal import Decimal as D,localcontext
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from coincat_adaptive_eth import ResearchFunds
from coincat_continuity import eth_funding
from coincat_eth_maker import post_only_eligible
from coincat_fill_units import normalize_fill,FillUnitError
from coincat_multicurrency import research_order
from coincat_research_journal import _encode,_decode
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

APP_ID=0x43435045
MAX_STATE_BYTES=524288
MAX_DB_BYTES=32*1024*1024
MAX_EVENTS=4096
MAX_FILLS=512
TERMINAL={'FILLED','CANCELED','REJECTED'}
ORDER_STATES=TERMINAL|{'PENDING_NEW','OPEN','PARTIAL','PENDING_CANCEL','UNKNOWN'}
SOURCES={'EXPLICIT_SIMULATION','SIMULATED_REPLAY'}


class PaperBlocked(ValueError):
    pass


def _positive(value):
    n=exact(value)
    if n<=0:raise PaperBlocked('POSITIVE_EXACT_AMOUNT_REQUIRED')
    return n


def _at(value):
    if isinstance(value,bool):raise PaperBlocked('INVALID_SIMULATION_TIME')
    try:n=float(value)
    except (TypeError,ValueError,OverflowError):raise PaperBlocked('INVALID_SIMULATION_TIME') from None
    if not math.isfinite(n):raise PaperBlocked('INVALID_SIMULATION_TIME')
    return n


def _id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
        raise PaperBlocked('INVALID_SIMULATION_REFERENCE')
    return value


def _pack(value):
    raw=json.dumps(_encode(value),separators=(',',':'),allow_nan=False)
    if len(raw.encode('utf-8'))>MAX_STATE_BYTES:raise PaperBlocked('PAPER_STATE_LIMIT')
    return raw


def _unpack(raw):
    if len(raw.encode('utf-8'))>MAX_STATE_BYTES:raise PaperBlocked('PAPER_STATE_LIMIT')
    def reject(value):raise PaperBlocked('INVALID_PAPER_STATE')
    try:return _decode(json.loads(raw,parse_constant=reject))
    except (ValueError,TypeError,KeyError,ArithmeticError,RecursionError):
        raise PaperBlocked('INVALID_PAPER_STATE') from None


def _digest(value):return hashlib.sha256(_pack(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class PaperLimits:
    products:tuple
    source_caps:dict
    max_open_orders:int
    max_orders:int
    expires_at:float
    max_fee_fraction:D

    def checked(self):
        if (not isinstance(self.products,tuple) or not self.products or
                len(set(self.products))!=len(self.products) or not set(self.products)<=set(WATCH_PAIRS)):
            raise PaperBlocked('EXPLICIT_APPROVED_PRODUCTS_REQUIRED')
        if type(self.max_open_orders) is not int or not 1<=self.max_open_orders<=16:
            raise PaperBlocked('INVALID_PAPER_OPEN_ORDER_LIMIT')
        if type(self.max_orders) is not int or not self.max_open_orders<=self.max_orders<=64:
            raise PaperBlocked('INVALID_PAPER_SESSION_ORDER_LIMIT')
        if not isinstance(self.source_caps,dict) or not self.source_caps or not set(self.source_caps)<=set(WATCH_ASSETS):
            raise PaperBlocked('EXPLICIT_NATIVE_CAPS_REQUIRED')
        caps={a:_positive(q) for a,q in self.source_caps.items()}
        fee=exact(self.max_fee_fraction)
        if not 0<=fee<D('.05'):raise PaperBlocked('UNSUPPORTED_PAPER_FEE_LIMIT')
        return PaperLimits(tuple(self.products),caps,self.max_open_orders,self.max_orders,_at(self.expires_at),fee)


class PaperEngine:
    """One funded simulation and durable, idempotent paper order state machine.

    A single session start authorizes routine paper intents inside supplied limits.
    There is no live mode, and restoring never automatically resumes ordering.
    """
    def __init__(self,path,state,revision):
        self.path=Path(path);self._state=state;self._revision=revision;self._stale=False
        self._invariants(state)

    @classmethod
    def create(cls,path,*,initial_eth,limits,at,simulation_ack):
        if simulation_ack!='SIMULATION_ONLY':raise PaperBlocked('SIMULATION_ACK_REQUIRED')
        path=Path(path)
        if path.is_symlink() or path.parent.is_symlink():raise PaperBlocked('PAPER_SYMLINK_REJECTED')
        if path.exists() and path.stat().st_size:raise PaperBlocked('PAPER_DESTINATION_MUST_BE_EMPTY')
        limits=limits.checked();now=_at(at)
        if now>=limits.expires_at:raise PaperBlocked('PAPER_SESSION_EXPIRED')
        funds=ResearchFunds(initial_eth)
        state=dict(schema=1,classification='SIMULATED_ASSUMPTION',mode='PAUSED',initial_eth=funds.initial_eth,
            wallet=funds.inventory(),orders={},fills={},commands=[],limits=asdict(limits),
            last_at=now,last_issue=None,simulated_fills=0)
        path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path,timeout=1)) as db,db:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                raise PaperBlocked('PAPER_DESTINATION_MUST_BE_EMPTY')
            db.execute('PRAGMA application_id='+str(APP_ID))
            db.execute('CREATE TABLE paper_state(rowid INTEGER PRIMARY KEY CHECK(rowid=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL)')
            db.execute('CREATE TABLE paper_events(event_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,outcome TEXT NOT NULL)')
            raw=_pack(state)
            db.execute('INSERT INTO paper_state VALUES(1,0,?,?)',(raw,hashlib.sha256(raw.encode()).hexdigest()))
        return cls(path,state,0)

    @classmethod
    def from_proposal(cls,path,*,amount_eth,limits,at,simulation_ack,working_fraction=None,**proposal):
        funding=eth_funding(now=at,**proposal);amount=_positive(amount_eth)
        if not funding['valid'] or amount>funding['row'].get('working',D(0)):
            raise PaperBlocked('PAPER_WORKING_ETH_UNAVAILABLE')
        if working_fraction is not None:
            fraction=exact(working_fraction)
            if not 0<fraction<=D('.5') or amount>funding['row']['working']*fraction:
                raise PaperBlocked('PAPER_INITIAL_WORKING_SLICE_LIMIT')
        engine=cls.create(path,initial_eth=amount,limits=limits,at=at,simulation_ack=simulation_ack)
        if working_fraction is not None:
            engine._apply('working_slice_confirmed',dict(kind='WORKING_SLICE_CAP',fraction=fraction),
                lambda s:s.update(funding_working_eth=funding['row']['working'],funding_fraction=fraction))
        return engine

    @classmethod
    def _read(cls,path):
        path=Path(path)
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
            raise PaperBlocked('PAPER_STATE_NOT_AVAILABLE')
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:
                raise PaperBlocked('WRONG_PAPER_DATABASE')
            row=db.execute('SELECT revision,payload,digest FROM paper_state WHERE rowid=1').fetchone()
        if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[2]:
            raise PaperBlocked('INVALID_PAPER_STATE_DIGEST')
        state=_unpack(row[1]);cls._invariants(state)
        return state,row[0]

    @classmethod
    def inspect(cls,path):
        """Bounded private local inspection, without a restore/write/resume."""
        return cls._read(path)[0]

    @classmethod
    def restore(cls,path):
        state,revision=cls._read(path);engine=cls(path,state,revision)
        # This is a control transition only; quantities/deadlines remain untouched.
        engine._apply('restore_'+str(revision),{'kind':'RESTORE'},
            lambda s:s.update(mode='RECONCILIATION_REQUIRED',last_issue='RESTART_RECONCILIATION_REQUIRED'))
        return engine

    def private_state(self):return deepcopy(self._state)

    def local_events(self,reference,*,limit=128):
        _id(reference)
        if type(limit) is not int or not 1<=limit<=256:raise PaperBlocked('INVALID_PAPER_EVENT_VIEW_BOUND')
        with closing(self._db()) as db:
            rows=db.execute('SELECT kind,payload FROM paper_events ORDER BY rowid DESC LIMIT ?',
                (MAX_EVENTS,)).fetchall()
        selected=[]
        for kind,raw in rows:
            payload=_unpack(raw)
            if payload.get('reference')==reference:
                selected.append(dict(kind=kind,payload=payload))
                if len(selected)>=limit:break
        return list(reversed(selected))

    def _db(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():raise PaperBlocked('PAPER_SYMLINK_REJECTED')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=1)
        if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:
            db.close();raise PaperBlocked('WRONG_PAPER_DATABASE')
        return db

    @staticmethod
    def _invariants(state):
        if (state.get('schema')!=1 or state.get('classification')!='SIMULATED_ASSUMPTION' or
                state.get('mode') not in ('PAUSED','ACTIVE','RECONCILIATION_REQUIRED')):
            raise PaperBlocked('INVALID_PAPER_STATE')
        limits=PaperLimits(**state['limits']).checked()
        if 'funding_fraction' in state:
            fraction=exact(state['funding_fraction']);working=exact(state['funding_working_eth'])
            if not 0<fraction<=D('.5') or not 0<state['initial_eth']<=working*fraction:
                raise PaperBlocked('INVALID_ORIGINAL_WORKING_SLICE')
        if 'global_history' in state.get('auto',{}):
            from coincat_global_paper import validate_history
            validate_history(state['auto']['global_history'])
        if len(state['orders'])>limits.max_orders or len(state['fills'])>MAX_FILLS:
            raise PaperBlocked('PAPER_HISTORY_LIMIT')
        for asset,qty in state['wallet'].items():
            if asset not in WATCH_ASSETS or exact(qty)<0:raise PaperBlocked('PAPER_WALLET_INVALID')
        reserved={a:D(0) for a in WATCH_ASSETS}
        with localcontext() as ctx:
            ctx.prec=60
            identities=set()
            for ref,order in state['orders'].items():
                version=order.get('global_policy_version',0)
                if 'global_policy_version' in order:
                    from coincat_global_paper import settings_at
                    if type(version) is not int or version<1:raise PaperBlocked('INVALID_ORDER_POLICY_VERSION')
                    applied=settings_at(state,version);proof=order.get('qualification',{})
                    if (applied is None or not isinstance(proof,dict) or proof.get('state')!='CONDITIONAL_QUALIFIED' or
                            proof.get('minimum_usd')!=applied.min_net_usd or proof.get('actual_profit_usd') is not None or
                            type(order.get('initial_slice_order')) is not bool):
                        raise PaperBlocked('INVALID_ORDER_POLICY_EVIDENCE')
                if (order['reference']!=ref or order['pair'] not in limits.products or
                        order['side'] not in ('BUY','SELL')):raise PaperBlocked('PAPER_ORDER_INVALID')
                base,quote=order['pair'].split('-')
                if (order['source'],order['target'])!=((quote,base) if order['side']=='BUY' else (base,quote)):
                    raise PaperBlocked('PAPER_ORDER_INVALID')
                identity=order['venue_order_id']
                if identity is not None:
                    if _id(identity) in identities:raise PaperBlocked('PAPER_VENUE_ID_REUSED')
                    identities.add(identity)
                if order['state'] not in ORDER_STATES or not 0<=order['filled_base']<=order['base_size']:
                    raise PaperBlocked('PAPER_ORDER_INVALID')
                if ((order['state']=='FILLED' and order['filled_base']!=order['base_size']) or
                        (order['state'] in ('PENDING_NEW','OPEN','REJECTED') and order['filled_base']!=0) or
                        (order['state']=='PARTIAL' and not 0<order['filled_base']<order['base_size'])):
                    raise PaperBlocked('PAPER_ORDER_TOTALS_INVALID')
                if (not 0<=order['reserved']<=order['source_budget'] or
                        not 0<=order['spent_source']<=order['source_budget'] or order['received_target']<0):
                    raise PaperBlocked('PAPER_RESERVATION_INVALID')
                if order['state'] in TERMINAL and order['reserved']!=0:
                    raise PaperBlocked('TERMINAL_PAPER_RESERVATION')
                if order['state'] not in TERMINAL and order['reserved']!=order['source_budget']-order['spent_source']:
                    raise PaperBlocked('PAPER_RESERVATION_INVALID')
                reserved[order['source']]+=order['reserved']
                if order['state'] not in TERMINAL:reserved[order['target']]+=order['received_target']
            if any(q>state['wallet'].get(a,D(0)) for a,q in reserved.items()):
                raise PaperBlocked('PAPER_DOUBLE_ALLOCATION')

    def _apply(self,event_id,payload,action,*,critical=False,order_ref=None,context_after=None,journal=True):
        event_id=_id(event_id);fingerprint=_digest(payload);before=self._state
        if not journal and payload!={'kind':'AUTO_CONTEXT_CHECKPOINT'}:
            raise PaperBlocked('PAPER_CONTEXT_ONLY_CHECKPOINT_REQUIRED')
        if self.path.stat().st_size>=MAX_DB_BYTES:raise PaperBlocked('PAPER_STORAGE_LIMIT')
        issue=None;result=None
        with closing(self._db()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            revision=db.execute('SELECT revision FROM paper_state WHERE rowid=1').fetchone()[0]
            if revision!=self._revision:
                self._stale=True;raise PaperBlocked('STALE_PAPER_INSTANCE_RELOAD_REQUIRED')
            previous=db.execute('SELECT fingerprint FROM paper_events WHERE event_id=?',(event_id,)).fetchone() if journal else None
            if previous and previous[0]==fingerprint:return {'result':'DUPLICATE_IGNORED'}
            if journal and db.execute('SELECT COUNT(*) FROM paper_events').fetchone()[0]>=MAX_EVENTS:
                raise PaperBlocked('PAPER_EVENT_HISTORY_LIMIT')
            draft=deepcopy(before)
            try:
                if previous:raise PaperBlocked('CONFLICTING_PAPER_EVENT_ID')
                with localcontext() as ctx:
                    ctx.prec=60
                    result=action(draft)
                    if context_after is not None:
                        if not isinstance(context_after,dict):raise PaperBlocked('INVALID_PAPER_CONTEXT')
                        original=before.get('auto',{})
                        if original.get('policy') in ('PATIENT_MAKER_ETH_V1','SHORT_LIVED_ETH_V1') and (
                                context_after.get('policy')!=original.get('policy') or
                                context_after.get('config')!=original.get('config') or
                                context_after.get('model_assumptions')!=original.get('model_assumptions') or
                                context_after.get('session')!=original.get('session')):
                            raise PaperBlocked('FROZEN_PAPER_POLICY_CANNOT_CHANGE_WITHIN_SESSION')
                        if original.get('kickoff_reference') is not None and (
                                context_after.get('kickoff_reference')!=original['kickoff_reference']):
                            raise PaperBlocked('PAPER_KICKOFF_IDENTITY_CANNOT_CHANGE')
                        draft['auto']=deepcopy(context_after)
                    if not journal and {k:v for k,v in draft.items() if k!='auto'}!={k:v for k,v in before.items() if k!='auto'}:
                        raise PaperBlocked('CHECKPOINT_CANNOT_CHANGE_PAPER_FUNDS')
                    if before.get('auto',{}).get('global_history') or draft.get('auto',{}).get('global_history'):
                        from coincat_global_paper import validate_transition
                        validate_transition(before,draft,payload.get('kind'))
                    self._invariants(draft)
            except (PaperBlocked,ValueError,TypeError,KeyError,ArithmeticError) as exc:
                if not critical and not previous:raise
                issue=str(exc) if isinstance(exc,PaperBlocked) else 'INVALID_SIMULATION_EVENT'
                draft=deepcopy(before);draft.update(mode='RECONCILIATION_REQUIRED',last_issue=issue)
                if order_ref in draft['orders'] and draft['orders'][order_ref]['state'] not in TERMINAL:
                    draft['orders'][order_ref]['state']='UNKNOWN'
                result={'result':'RECONCILIATION_REQUIRED','reason':issue}
                self._invariants(draft)
            raw=_pack(draft)
            db.execute('UPDATE paper_state SET revision=?,payload=?,digest=? WHERE rowid=1',
                       (revision+1,raw,hashlib.sha256(raw.encode()).hexdigest()))
            if previous:
                # Preserve the original idempotency identity; retain the fault separately.
                log_id='#fault_'+str(revision+1)
            else:log_id=event_id
            if journal:
                db.execute('INSERT INTO paper_events VALUES(?,?,?,?,?)',
                           (log_id,fingerprint,str(payload.get('kind','CONTROL')),_pack(payload),str(result)))
        self._state=draft;self._revision=revision+1
        if issue:raise PaperBlocked(issue)
        return result

    def checkpoint_context(self,context):
        """Replace bounded venue/policy cache; no financial event or history deletion.

        Fills and command grants can commit their context in the same transaction.
        Repeated observation-only cache writes do not consume execution-event IDs.
        """
        if context==self._state.get('auto'):return
        return self._apply('context_'+str(self._revision),{'kind':'AUTO_CONTEXT_CHECKPOINT'},
            lambda s:None,context_after=context,journal=False)

    def apply_global(self,event_id,settings,*,at,initial_slice=False):
        from coincat_global_paper import revision,settings_at
        now=_at(at);settings=settings.checked()
        def apply(s):
            if now<s['last_at']:raise PaperBlocked('PAPER_TIME_MOVED_BACKWARDS')
            context=s.get('auto')
            if not isinstance(context,dict) or context.get('schema')!=1:raise PaperBlocked('AUTO_PAPER_CONTEXT_REQUIRED')
            previous=settings_at(s)
            if previous is not None and previous.initial_pct!=settings.initial_pct:
                raise PaperBlocked('INITIAL_ALLOCATION_FROZEN_FOR_SESSION')
            history=context.setdefault('global_history',[])
            if initial_slice:
                if history or s['orders'] or s.get('funding_fraction')!=settings.initial_pct/100:
                    raise PaperBlocked('INITIAL_WORKING_SLICE_NOT_VERIFIED')
                context['global_initial_slice']=True
            else:context.setdefault('global_initial_slice',False)
            history.append(revision(settings,len(history)+1,now))
            context.update(last_review=None,last_reason='GLOBAL_SETTINGS_APPLIED_FUTURE_INTENTS')
            s['last_at']=now
            return dict(result='GLOBAL_SETTINGS_APPLIED',version=len(history))
        return self._apply(event_id,dict(kind='APPLY_GLOBAL_PAPER_SETTINGS',settings=settings.frozen(),
            at=now,initial_slice=initial_slice),apply)

    @staticmethod
    def _held(state,asset):
        # Explicit partial proceeds are booked for reconciliation but cannot fund
        # another intent before the parent order's terminal totals are known.
        return sum((o['reserved'] if o['source']==asset else o['received_target']
                    if o['target']==asset and o['state'] not in TERMINAL else D(0)
                    for o in state['orders'].values()),D(0))

    def available(self,asset):
        if asset not in WATCH_ASSETS:raise PaperBlocked('PAPER_ASSET_OUT_OF_SCOPE')
        if self._stale or self._state['mode']=='RECONCILIATION_REQUIRED':return None
        with localcontext() as ctx:
            ctx.prec=60
            held=self._held(self._state,asset)
            return self._state['wallet'].get(asset,D(0))-held

    def start(self,event_id,*,at):
        now=_at(at)
        def apply(s):
            if s['mode']=='RECONCILIATION_REQUIRED':raise PaperBlocked('PAPER_RECONCILIATION_REQUIRED')
            if now>=s['limits']['expires_at']:raise PaperBlocked('PAPER_SESSION_EXPIRED')
            if now<s['last_at']:raise PaperBlocked('PAPER_TIME_MOVED_BACKWARDS')
            s.update(mode='ACTIVE',last_at=now)
            return {'result':'PAPER_SESSION_ACTIVE'}
        return self._apply(event_id,dict(kind='START',at=now),apply)

    def stop(self,event_id,*,at):
        now=_at(at)
        def apply(s):
            if s['mode']!='RECONCILIATION_REQUIRED':s['mode']='PAUSED'
            s['last_at']=max(now,s['last_at'])
            return {'result':'PAPER_SESSION_PAUSED_RESERVATIONS_RETAINED'}
        return self._apply(event_id,dict(kind='STOP',at=now),apply)

    def place(self,event_id,*,reference,pair,side,source_budget,limit_price,expires_at,frame,context_after=None,
              target_cap_from_receipt=False,global_policy_version=0,usd_reference=None):
        reference=_id(reference);budget=_positive(source_budget);price=_positive(limit_price)
        expiry=_at(expires_at)
        payload=dict(kind='PLACE_INTENT',reference=reference,pair=pair,side=side,
            source_budget=budget,limit_price=price,expires_at=expiry,at=frame.at,
            target_cap_from_receipt=target_cap_from_receipt)
        if global_policy_version:payload.update(global_policy_version=global_policy_version,usd_reference=deepcopy(usd_reference))
        def apply(s):
            if self._stale or s['mode']!='ACTIVE':raise PaperBlocked('PAPER_SESSION_NOT_ACTIVE')
            if frame.at<s['last_at']:raise PaperBlocked('PAPER_TIME_MOVED_BACKWARDS')
            if not frame.at<expiry<=s['limits']['expires_at']:raise PaperBlocked('PAPER_ORDER_OR_SESSION_EXPIRED')
            if pair not in s['limits']['products'] or side not in ('BUY','SELL'):
                raise PaperBlocked('PAPER_PRODUCT_OR_SIDE_NOT_APPROVED')
            base,quote=pair.split('-');src,dst=(quote,base) if side=='BUY' else (base,quote)
            leg=(pair,side,src,dst)
            if not any(a['leg']==leg for a in frame.graph(src)['actions']):
                raise PaperBlocked('PAPER_PRODUCT_INELIGIBLE')
            book=frame.book(pair);rules=frame._rules[pair]
            tick=exact(rules.get('price_increment',rules['quote_increment']))
            if not post_only_eligible(side,price,book,tick):raise PaperBlocked('PAPER_POST_ONLY_WOULD_CROSS_OR_BAD_TICK')
            fee=frame.rates('MAKER')
            if fee>s['limits']['max_fee_fraction']:raise PaperBlocked('PAPER_FEE_LIMIT')
            if src not in s['limits']['source_caps'] or budget>s['limits']['source_caps'][src]:
                raise PaperBlocked('PAPER_NATIVE_CAP_EXCEEDED')
            if reference in s['orders']:raise PaperBlocked('PAPER_CLIENT_REFERENCE_ALREADY_USED')
            if len(s['orders'])>=s['limits']['max_orders']:raise PaperBlocked('PAPER_SESSION_ORDER_LIMIT')
            if sum(o['state'] not in TERMINAL for o in s['orders'].values())>=s['limits']['max_open_orders']:
                raise PaperBlocked('PAPER_OPEN_ORDER_LIMIT')
            held=self._held(s,src)
            if budget>s['wallet'].get(src,D(0))-held:raise PaperBlocked('PAPER_FUNDS_UNAVAILABLE_OR_RESERVED')
            with localcontext() as ctx:
                ctx.prec=60
                receipt=research_order(pair=pair,side=side,available=budget,cap=budget,usd_rate=D(1),
                    book=(price,price,frame.at),product_rules=frame._rules,fee=fee,slip=D(0))
            receipt.pop('approx_usd_notional',None)
            receipt['fee_rate_source']='EXPLICIT_SIMULATION_INPUT_NOT_ACCOUNT_VERIFICATION'
            proof=None
            history=s.get('auto',{}).get('global_history',[])
            if history:
                from coincat_global_paper import settings_at,source_budget as global_budget,initial_campaign,qualification
                if type(global_policy_version) is not int or global_policy_version!=len(history):
                    raise PaperBlocked('STALE_GLOBAL_POLICY_REFRESH_REQUIRED')
                if not s['auto']['config']['directions'][src+'_'+dst]['enabled']:
                    raise PaperBlocked('GLOBAL_DIRECTION_DISABLED')
                if fee!=s['limits']['max_fee_fraction']:
                    raise PaperBlocked('GLOBAL_PLANNING_FEE_CEILING_REQUIRED')
                if not set(frame._quotes)<=set(WATCH_PAIRS) or len(frame._quotes)>6:
                    raise PaperBlocked('GLOBAL_FRAME_SCOPE_INVALID')
                settings=settings_at(s)
                available=s['wallet'].get(src,D(0))-held
                initial=initial_campaign(s) and src=='ETH'
                maximum=global_budget(s,available,dict(source=src),settings,initial=initial)
                if budget>maximum:raise PaperBlocked('GLOBAL_SOURCE_ALLOCATION_EXCEEDED')
                proof=qualification(s,frame,receipt,budget,usd_reference,settings)
                if proof['state']!='CONDITIONAL_QUALIFIED':raise PaperBlocked('GLOBAL_PROFIT_NOT_QUALIFIED')
            elif global_policy_version:raise PaperBlocked('GLOBAL_POLICY_NOT_APPLIED')
            if type(target_cap_from_receipt) is not bool:raise PaperBlocked('INVALID_PAPER_CAP_RULE')
            if target_cap_from_receipt and dst not in s['limits']['source_caps']:
                # The opt-in controller freezes this rule at session creation.
                # A cap is a ceiling, never a credit. The first canonical target
                # quantity is persisted before dispatch and is never increased.
                s['limits']['source_caps'][dst]=receipt['output_quantity']
            s['orders'][reference]=dict(reference=reference,pair=pair,side=side,source=src,target=dst,
                source_budget=budget,reserved=budget,base_size=receipt['gross_base_quantity'],
                limit_price=price,created_at=frame.at,expires_at=expiry,state='PENDING_NEW',
                filled_base=D(0),spent_source=D(0),received_target=D(0),cancel_requested=False,
                venue_order_id=None,base_increment=exact(rules['base_increment']),price_increment=tick,
                plan_receipt=receipt)
            if history:s['orders'][reference].update(global_policy_version=global_policy_version,qualification=proof,
                initial_slice_order=initial)
            s['commands'].append(dict(command_id='place_'+reference,kind='PLACE_POST_ONLY',reference=reference,
                pair=pair,side=side,base_size=receipt['gross_base_quantity'],limit_price=price,
                status='UNSENT',classification='SIMULATED_ASSUMPTION'))
            s['last_at']=frame.at
            return {'result':'PAPER_ORDER_RESERVED','reference':reference}
        return self._apply(event_id,payload,apply,context_after=context_after)

    def pending_commands(self):
        s=self._state
        if self._stale or s['mode']=='RECONCILIATION_REQUIRED':return []
        return deepcopy([c for c in s['commands'] if c['status']=='UNSENT' and
            s['orders'][c['reference']]['state'] not in TERMINAL and
            (s['mode']=='ACTIVE' or c['kind']=='CANCEL_PAPER_ORDER')])

    def mark_dispatched(self,event_id,command_id,*,at,context_after=None):
        now=_at(at)
        def apply(s):
            command=next((c for c in s['commands'] if c['command_id']==command_id),None)
            if command is None:raise PaperBlocked('UNKNOWN_PAPER_COMMAND')
            order=s['orders'][command['reference']]
            if order['state'] in TERMINAL:raise PaperBlocked('PAPER_COMMAND_ALREADY_TERMINAL')
            if s['mode']=='RECONCILIATION_REQUIRED' or (s['mode']!='ACTIVE' and command['kind']=='PLACE_POST_ONLY'):
                raise PaperBlocked('PAPER_SESSION_NOT_ACTIVE')
            if now<s['last_at']:raise PaperBlocked('PAPER_TIME_MOVED_BACKWARDS')
            if command['kind']=='PLACE_POST_ONLY' and now>=min(order['expires_at'],s['limits']['expires_at']):
                raise PaperBlocked('PAPER_ORDER_OR_SESSION_EXPIRED')
            if command['status']!='UNSENT':
                return {'result':'PAPER_COMMAND_ALREADY_DISPATCHED_OR_ACKED','dispatch_permitted':False}
            command['status']='DISPATCHED'
            s['last_at']=now
            return {'result':'PAPER_COMMAND_DISPATCHED_ONCE','dispatch_permitted':True}
        return self._apply(event_id,dict(kind='DISPATCH',command_id=command_id,at=now),apply,context_after=context_after)

    @staticmethod
    def _cancel(s,reference):
        order=s['orders'][reference]
        if order['state'] in TERMINAL:return
        if order['state'] in ('PENDING_NEW','UNKNOWN'):
            order['state']='UNKNOWN';s.update(mode='RECONCILIATION_REQUIRED',last_issue='PAPER_SUBMISSION_OUTCOME_UNKNOWN');return
        order.update(state='PENDING_CANCEL',cancel_requested=True)
        cid='cancel_'+reference
        if not any(c['command_id']==cid for c in s['commands']):
            s['commands'].append(dict(command_id=cid,kind='CANCEL_PAPER_ORDER',reference=reference,
                status='UNSENT',classification='SIMULATED_ASSUMPTION'))

    def request_cancel(self,event_id,reference,*,context_after=None):
        def apply(s):
            if reference not in s['orders']:raise PaperBlocked('UNKNOWN_PAPER_ORDER')
            self._cancel(s,reference)
            return {'result':'PAPER_CANCEL_REQUESTED_NO_RELEASE_UNTIL_ACK'}
        return self._apply(event_id,dict(kind='CANCEL_INTENT',reference=reference),apply,context_after=context_after)

    def tick(self,event_id,*,at):
        now=_at(at)
        def apply(s):
            if now<s['last_at']:raise PaperBlocked('PAPER_TIME_MOVED_BACKWARDS')
            # Quoted prices are deliberately absent: a touch cannot generate a fill.
            for ref,o in s['orders'].items():
                if o['state'] not in TERMINAL and now>=o['expires_at']:self._cancel(s,ref)
            if now>=s['limits']['expires_at'] and s['mode']!='RECONCILIATION_REQUIRED':s['mode']='PAUSED'
            s['last_at']=now
            return {'result':'PAPER_CLOCK_OBSERVED_NO_INFERRED_FILLS'}
        return self._apply(event_id,dict(kind='TICK',at=now),apply)

    @staticmethod
    def _ack_command(s,reference,kind):
        for command in s['commands']:
            if command['reference']==reference and command['kind']==kind:command['status']='ACKED'

    @staticmethod
    def _pending_fees(s,reference):
        return any(f['reference']==reference and not f['settled'] for f in s['fills'].values())

    def _settle(self,s,reference,fill_id,raw):
        order=s['orders'][reference]
        if order['state'] in TERMINAL:raise PaperBlocked('LATE_FILL_CONFLICTS_WITH_TERMINAL_TOTALS')
        venue_id=_id(raw['venue_order_id'])
        if order['venue_order_id'] is None:
            order['venue_order_id']=venue_id
            self._ack_command(s,reference,'PLACE_POST_ONLY')
        elif order['venue_order_id']!=venue_id:raise PaperBlocked('PAPER_ORDER_IDENTITY_CONFLICT')
        if raw['fee_currency']!=order['pair'].split('-')[1] or raw['commission'] is None:
            if len(s['fills'])>=MAX_FILLS:raise PaperBlocked('PAPER_FILL_HISTORY_LIMIT')
            s['fills'][fill_id]=dict(reference=reference,raw=deepcopy(raw),fingerprints=[_digest(raw)],settled=False)
            order['state']='UNKNOWN';s.update(mode='RECONCILIATION_REQUIRED',last_issue='PAPER_FEE_UNITS_OR_AMOUNT_UNKNOWN')
            return
        price=_positive(raw['price']);size=_positive(raw['size']);fee=exact(raw['commission'])
        if fee<0 or type(raw['size_in_quote']) is not bool:raise PaperBlocked('UNSUPPORTED_PAPER_FILL_UNITS_OR_REBATE')
        if raw['liquidity']!='MAKER':raise PaperBlocked('PAPER_POST_ONLY_EXECUTION_CLASS_CONFLICT')
        if price%order['price_increment'] or (order['side']=='BUY' and price>order['limit_price']) or (
                order['side']=='SELL' and price<order['limit_price']):raise PaperBlocked('PAPER_FILL_PRICE_CONFLICT')
        if raw['at']<order['created_at']:raise PaperBlocked('PAPER_FILL_BEFORE_ORDER')
        with localcontext() as ctx:
            ctx.prec=60
            try:n=normalize_fill(dict(price=price,size=size,commission=fee,size_in_quote=raw['size_in_quote']))
            except FillUnitError:raise PaperBlocked('INVALID_PAPER_FILL_UNITS') from None
            qty,gross=n['base_qty'],n['quote_qty']
            if qty%order['base_increment'] or order['filled_base']+qty>order['base_size']:
                raise PaperBlocked('PAPER_OVERFILL_OR_BASE_INCREMENT_CONFLICT')
            if fee>gross*s['limits']['max_fee_fraction']:raise PaperBlocked('PAPER_FILL_FEE_LIMIT')
            debit=gross+fee if order['side']=='BUY' else qty
            credit=qty if order['side']=='BUY' else gross-fee
            if credit<0 or debit>order['reserved'] or debit>s['wallet'].get(order['source'],D(0)):
                raise PaperBlocked('PAPER_FILL_EXCEEDS_RESERVED_SOURCE')
            # Actual explicit simulated debits/credits, not a second order planner.
            s['wallet'][order['source']]-=debit
            s['wallet'][order['target']]=s['wallet'].get(order['target'],D(0))+credit
            order['reserved']-=debit;order['filled_base']+=qty
            order['spent_source']+=debit;order['received_target']+=credit
        original=s['fills'].get(fill_id)
        fingerprints=list(original['fingerprints']) if original else []
        if _digest(raw) not in fingerprints:fingerprints.append(_digest(raw))
        s['fills'][fill_id]=dict(reference=reference,raw=deepcopy(raw),fingerprints=fingerprints,settled=True)
        s['simulated_fills']+=1
        s['fills'][fill_id].update(source=order['source'],target=order['target'],debit=debit,credit=credit,
            settle_index=s['simulated_fills'])
        if order['filled_base']==order['base_size'] and not self._pending_fees(s,reference):
            order.update(state='FILLED',reserved=D(0))
        else:order['state']='PENDING_CANCEL' if order['cancel_requested'] else 'PARTIAL'

    def ingest(self,event,*,context_after=None):
        if not isinstance(event,dict) or set(event)!={'event_id','source','kind','reference','at','data'}:
            raise PaperBlocked('INVALID_SIMULATION_EVENT_SCHEMA')
        event=deepcopy(event);reference=_id(event['reference']);event['at']=_at(event['at'])
        if event['source'] not in SOURCES:raise PaperBlocked('EXPLICIT_SIMULATION_EVENT_SOURCE_REQUIRED')
        schemas={'ACK':{'venue_order_id'},'REJECT':{'cumulative_base','venue_order_id'},
            'CANCEL_ACK':{'cumulative_base','venue_order_id'},
            'FILL':{'fill_id','price','size','size_in_quote','commission','fee_currency','liquidity','venue_order_id'},
            'FEE_RESOLVED':{'fill_id','commission','fee_currency'},'OUTCOME_UNKNOWN':{'reason'}}
        kind=event['kind'];data=event['data']
        if kind not in schemas or not isinstance(data,dict) or set(data)!=schemas[kind]:
            raise PaperBlocked('INVALID_SIMULATION_EVENT_SCHEMA')
        def apply(s):
            if reference not in s['orders']:raise PaperBlocked('UNKNOWN_PAPER_ORDER')
            order=s['orders'][reference]
            if event['at']<order['created_at']:raise PaperBlocked('PAPER_EVENT_BEFORE_ORDER')
            s['last_at']=max(s['last_at'],event['at'])
            if kind=='ACK':
                venue_id=_id(data['venue_order_id'])
                if order['venue_order_id']==venue_id:
                    self._ack_command(s,reference,'PLACE_POST_ONLY')
                    return {'result':'DUPLICATE_ACK_IGNORED'}
                if order['venue_order_id'] is not None:raise PaperBlocked('PAPER_ORDER_IDENTITY_CONFLICT')
                if order['state'] not in ('PENDING_NEW','UNKNOWN') or order['filled_base']:
                    raise PaperBlocked('PAPER_ACK_STATE_CONFLICT')
                if any(o['reference']!=reference and o['venue_order_id']==venue_id for o in s['orders'].values()):
                    raise PaperBlocked('PAPER_VENUE_ID_REUSED')
                order.update(venue_order_id=venue_id,state='OPEN')
                self._ack_command(s,reference,'PLACE_POST_ONLY')
            elif kind=='FILL':
                fill_id=_id(data['fill_id']);raw=dict(data,at=event['at']);raw.pop('fill_id')
                previous=s['fills'].get(fill_id)
                if previous:
                    if previous['reference']!=reference or _digest(raw) not in previous['fingerprints']:
                        raise PaperBlocked('CONFLICTING_PAPER_FILL_ID')
                    return {'result':'DUPLICATE_FILL_IGNORED'}
                if len(s['fills'])>=MAX_FILLS:raise PaperBlocked('PAPER_FILL_HISTORY_LIMIT')
                self._settle(s,reference,fill_id,raw)
            elif kind=='FEE_RESOLVED':
                fill_id=_id(data['fill_id']);previous=s['fills'].get(fill_id)
                if previous is None or previous['reference']!=reference or previous['settled']:
                    raise PaperBlocked('PAPER_FEE_RESOLUTION_CONFLICT')
                raw=dict(previous['raw'],commission=data['commission'],fee_currency=data['fee_currency'])
                if raw['fee_currency']!=order['pair'].split('-')[1] or raw['commission'] is None:
                    raise PaperBlocked('PAPER_FEE_RESOLUTION_UNSUPPORTED')
                self._settle(s,reference,fill_id,raw)
            elif kind=='OUTCOME_UNKNOWN':
                if data['reason'] not in ('SUBMISSION_UNKNOWN','CANCEL_UNKNOWN','TRANSPORT_GAP'):
                    raise PaperBlocked('INVALID_PAPER_UNKNOWN_REASON')
                if order['state'] not in TERMINAL:order['state']='UNKNOWN'
                s.update(mode='RECONCILIATION_REQUIRED',last_issue=data['reason'])
            else:
                venue_id=data['venue_order_id']
                if kind=='CANCEL_ACK' or venue_id is not None:
                    venue_id=_id(venue_id)
                    if order['venue_order_id'] is not None and venue_id!=order['venue_order_id']:
                        raise PaperBlocked('PAPER_ORDER_IDENTITY_CONFLICT')
                    order['venue_order_id']=venue_id
                total=exact(data['cumulative_base'])
                if self._pending_fees(s,reference) or total!=order['filled_base']:
                    raise PaperBlocked('PAPER_TERMINAL_FILL_HISTORY_INCOMPLETE')
                if kind=='REJECT' and total:raise PaperBlocked('PAPER_REJECT_AFTER_EXECUTION')
                state='FILLED' if total==order['base_size'] else 'REJECTED' if kind=='REJECT' else 'CANCELED'
                if order['state'] in TERMINAL and state!=order['state']:
                    raise PaperBlocked('PAPER_TERMINAL_STATE_CONFLICT')
                order.update(state=state,reserved=D(0))
                self._ack_command(s,reference,'PLACE_POST_ONLY');self._ack_command(s,reference,'CANCEL_PAPER_ORDER')
            return {'result':'SIMULATED_EVENT_APPLIED'}
        return self._apply(event['event_id'],event,apply,critical=True,order_ref=reference,context_after=context_after)

    def reconcile(self,event_id,*,wallet,orders,at,source):
        if source not in SOURCES:raise PaperBlocked('EXPLICIT_SIMULATION_EVENT_SOURCE_REQUIRED')
        now=_at(at)
        payload=dict(kind='RECONCILE',wallet=wallet,orders=orders,at=now,source=source)
        def apply(s):
            if any(not f['settled'] for f in s['fills'].values()):raise PaperBlocked('PAPER_FEE_EVIDENCE_STILL_REQUIRED')
            if not isinstance(wallet,dict) or not set(wallet)<=set(WATCH_ASSETS):raise PaperBlocked('PAPER_BALANCE_SNAPSHOT_INVALID')
            observed={a:exact(wallet.get(a,0)) for a in WATCH_ASSETS}
            expected={a:s['wallet'].get(a,D(0)) for a in WATCH_ASSETS}
            if observed!=expected:raise PaperBlocked('PAPER_BALANCE_MISMATCH_NO_INVENTED_FUNDS')
            required={ref for ref,o in s['orders'].items() if o['state'] not in TERMINAL}
            if not isinstance(orders,dict) or set(orders)!=required:raise PaperBlocked('PAPER_OPEN_ORDER_SNAPSHOT_INCOMPLETE')
            for ref,row in orders.items():
                order=s['orders'][ref]
                if not isinstance(row,dict) or set(row)!={'state','filled_base','venue_order_id'}:
                    raise PaperBlocked('PAPER_ORDER_SNAPSHOT_INVALID')
                if exact(row['filled_base'])!=order['filled_base']:raise PaperBlocked('PAPER_MISSING_FILL_HISTORY')
                state=row['state'];filled=order['filled_base']
                valid=(state=='OPEN' and filled==0) or (state=='PARTIAL' and 0<filled<order['base_size']) or (
                    state=='FILLED' and filled==order['base_size']) or (state=='CANCELED' and filled<order['base_size']) or (
                    state=='REJECTED' and filled==0)
                if not valid:raise PaperBlocked('PAPER_ORDER_SNAPSHOT_CONFLICT')
                venue_id=row['venue_order_id']
                if not (state=='REJECTED' and filled==0 and order['venue_order_id'] is None and venue_id is None):
                    venue_id=_id(venue_id)
                if order['venue_order_id'] is not None and venue_id!=order['venue_order_id']:
                    raise PaperBlocked('PAPER_ORDER_IDENTITY_CONFLICT')
                order.update(state=state,venue_order_id=venue_id,cancel_requested=False)
                if state in TERMINAL:order['reserved']=D(0)
                self._ack_command(s,ref,'PLACE_POST_ONLY');self._ack_command(s,ref,'CANCEL_PAPER_ORDER')
            s.update(mode='PAUSED',last_at=max(now,s['last_at']),last_issue=None)
            return {'result':'PAPER_RECONCILED_REQUIRES_EXPLICIT_SESSION_START'}
        return self._apply(event_id,payload,apply,critical=True)

    def status(self):
        s=self._state;counts={state:sum(o['state']==state for o in s['orders'].values()) for state in sorted(ORDER_STATES)}
        return dict(mode='STALE_RELOAD_REQUIRED' if self._stale else s['mode'],classification='SIMULATED_ASSUMPTION',
            orders=len(s['orders']),order_states=counts,simulated_fills=s['simulated_fills'],
            unsettled_fills=sum(not f['settled'] for f in s['fills'].values()),
            last_issue=s['last_issue'],verified_exchange_fills=0,real_orders=0,
            actual_profit_eth=None,live_permission=False,strategy_edge='NO_DEMONSTRATED_EDGE')


class ReplayDriver:
    """Automate an explicitly approved scripted paper sequence, not a predictor.

    Each step may use settled available source units within session caps. No next
    order is requested while its predecessor is partial/canceling/unknown. The
    driver consumes explicit external events; it never invents an execution.
    """
    def __init__(self,engine,steps,*,order_lifetime_s):
        if not isinstance(steps,tuple) or not 1<=len(steps)<=64:
            raise PaperBlocked('EXPLICIT_PAPER_SCRIPT_REQUIRED')
        self.engine=engine;self.steps=tuple(dict(x) for x in steps);self.lifetime=_positive(order_lifetime_s)
        references=set()
        for step in self.steps:
            if set(step)!={'reference','pair','side'}:raise PaperBlocked('INVALID_PAPER_SCRIPT')
            ref=_id(step['reference'])
            if (ref in references or step['pair'] not in engine.private_state()['limits']['products'] or
                    step['side'] not in ('BUY','SELL')):raise PaperBlocked('INVALID_PAPER_SCRIPT')
            references.add(ref)
        self.last_decision={'decision':'HOLD','reason':'NO_FRAME'}

    def advance(self,frame):
        state=self.engine.private_state()
        for step in self.steps:
            previous=state['orders'].get(step['reference'])
            if previous is not None:
                if previous['state']=='FILLED':continue
                self.last_decision={'decision':'HOLD','reason':'PREVIOUS_PAPER_ORDER_NOT_FILLED'};return self.last_decision
            if state['mode']!='ACTIVE':
                self.last_decision={'decision':'HOLD','reason':'PAPER_SESSION_NOT_ACTIVE'};return self.last_decision
            try:
                base,quote=step['pair'].split('-');src=quote if step['side']=='BUY' else base
                available=self.engine.available(src)
                if available is None:raise PaperBlocked('PAPER_FUNDING_UNRECONCILED')
                cap=state['limits']['source_caps'].get(src,D(0));budget=min(available,cap)
                book=frame.book(step['pair']);price=book[0] if step['side']=='BUY' else book[1]
                expiry=min(frame.at+float(self.lifetime),state['limits']['expires_at'])
                intent_id='intent_'+hashlib.sha256(step['reference'].encode()).hexdigest()[:32]
                self.engine.place(intent_id,reference=step['reference'],pair=step['pair'],side=step['side'],
                    source_budget=budget,limit_price=price,expires_at=expiry,frame=frame)
                self.last_decision={'decision':'PAPER_ORDER_REQUESTED','classification':'SIMULATED_ASSUMPTION'}
            except (PaperBlocked,ValueError,TypeError,KeyError,ArithmeticError):
                self.last_decision={'decision':'HOLD','reason':'PAPER_QUALIFICATION_OR_FUNDING_BLOCKED'}
            return self.last_decision
        self.last_decision={'decision':'HOLD','reason':'APPROVED_PAPER_SCRIPT_COMPLETE'}
        return self.last_decision
