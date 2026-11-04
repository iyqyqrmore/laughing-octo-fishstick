"""View-only historical observations. No live/paper/financial settlement authority."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal as D,localcontext
from pathlib import Path
import time
import uuid
import re

from coinbase_account import as_dict
from coincat_beta_store import BetaStore,BetaBlocked,digest
from coincat_fill_units import summarize_fills,verify_order_totals
from coincat_order_book import utc_stamp
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

APP_ID=0x43434D52
MAX_ORDERS=128
MAX_FILLS=512
MAX_CALLS=96


def identity(raw):
    try:return str(uuid.UUID(raw))
    except (ValueError,TypeError,AttributeError):raise BetaBlocked('READ_IDENTITY_UNREPORTED_OR_INVALID') from None


def fill_identity(raw):
    # Exchange trade IDs may be numeric strings, unlike order/portfolio UUIDs.
    if not isinstance(raw,str) or re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',raw) is None:
        raise BetaBlocked('READ_FILL_IDENTITY_UNREPORTED_OR_INVALID')
    return raw


def explicit_size_flag(value):
    if type(value) is bool:return value
    if type(value) is int and value in (0,1):return bool(value)
    if type(value) is str and value in ('false','False','true','True'):return value.lower()=='true'
    raise BetaBlocked('FILL_SIZE_DENOMINATION_UNKNOWN')


def fill_count(value):
    if type(value) is int:
        number=value
    elif type(value) is str and value.isascii() and value.isdigit() and len(value)<=4:
        number=int(value)
    else:raise BetaBlocked('FILL_COUNT_UNREPORTED_OR_INVALID')
    if not 0<=number<=MAX_FILLS:raise BetaBlocked('HISTORICAL_FILL_BOUND')
    return number


def explicit_fee_currency(fill):
    values=[]
    for obj,keys in ((fill,('fee_currency','commission_currency')),
            (fill.get('commission_detail_total') or {},('fee_currency','commission_currency','currency'))):
        if not isinstance(obj,dict):raise BetaBlocked('FEE_DETAIL_UNRECOGNIZED')
        for key in keys:
            if obj.get(key) is not None:
                if obj[key] not in WATCH_ASSETS:raise BetaBlocked('FEE_ASSET_UNSUPPORTED')
                values.append(obj[key])
    if len(set(values))>1:raise BetaBlocked('FEE_CURRENCY_FIELDS_CONFLICT')
    return values[0] if values else None


def order_report(order,fills,*,portfolio,complete=True,source='VERIFIED_EXCHANGE_HISTORICAL_READ'):
    """Independent evidence dimensions; real fills need not have known economics."""
    scope=identity(portfolio);oid=identity(order.get('order_id'));pair=order.get('product_id');side=order.get('side')
    if identity(order.get('retail_portfolio_id'))!=scope or pair not in WATCH_PAIRS or side not in ('BUY','SELL'):
        raise BetaBlocked('READ_ORDER_SCOPE_MISMATCH')
    report=dict(order_id=oid,portfolio=scope,pair=pair,side=side,source=source,
        original_status=order.get('status'),state='HISTORY_INCOMPLETE',coverage='INCOMPLETE',
        native_settlement='UNKNOWN',base_qty=None,gross_quote=None,fee_amount=None,fee_currencies=[],
        base_change=None,quote_change=None,post_only=None,liquidity='UNKNOWN',
        manual_origin='OWNER_ATTESTATION_REQUIRED',reported_placement_source=order.get('order_placement_source'),
        created_at=None,first_fill_at=None,last_fill_at=None,creation_to_first_fill_s=None,
        accepted_resting_duration='UNKNOWN',balance_reconciliation='UNKNOWN_NO_HISTORICAL_SNAPSHOTS',
        bbo_context='NOT_CAPTURED_UNLESS_EXISTING_RESEARCH_HISTORY',profit='NOT_ASSESSED',reason='HISTORY_INCOMPLETE')
    config=order.get('order_configuration') or {}
    for kind in ('limit_limit_gtc','limit_limit_gtd'):
        value=config.get(kind,{})
        if type(value.get('post_only')) is bool:report['post_only']=value['post_only']
    try:
        report['created_at']=utc_stamp(order.get('created_time'))
        expected=order.get('number_of_fills')
        if fill_count(expected)!=len(fills):
            raise BetaBlocked('FILL_COUNT_INCOMPLETE')
        times=[];currencies=[];liquidity=[]
        with localcontext() as ctx:
            ctx.prec=80
            for raw in fills:
                if (identity(raw.get('order_id'))!=oid or identity(raw.get('retail_portfolio_id'))!=scope or
                        raw.get('product_id')!=pair or raw.get('side')!=side):raise BetaBlocked('READ_FILL_SCOPE_MISMATCH')
                fill_identity(raw.get('trade_id'));explicit_size_flag(raw.get('size_in_quote'))
                for key in ('price','size','commission'):
                    if exact(raw.get(key))<0:raise BetaBlocked('INVALID_FILL_AMOUNT')
                at=utc_stamp(raw.get('trade_time'))
                if at<report['created_at']:raise BetaBlocked('FILL_PRECEDES_ORDER')
                times.append(at);currencies.append(explicit_fee_currency(raw));liquidity.append(raw.get('liquidity_indicator'))
            totals=summarize_fills(fills,order_id=oid,pair=pair,side=side) if fills else dict(base_qty=D(0),quote_qty=D(0),fees=D(0))
            if fills:verify_order_totals(order,totals)
            for field,key in (('filled_size','base_qty'),('filled_value','quote_qty'),('total_fees','fees')):
                if exact(order.get(field))!=totals[key]:raise BetaBlocked('EXACT_ORDER_FILL_TOTALS_CONFLICT')
            report.update(base_qty=totals['base_qty'],gross_quote=totals['quote_qty'],fee_amount=totals['fees'],
                fee_currencies=currencies,coverage='COMPLETE_AS_REPORTED' if complete else 'INCOMPLETE',
                first_fill_at=min(times) if times else None,last_fill_at=max(times) if times else None)
            if times:report['creation_to_first_fill_s']=min(times)-report['created_at']
            report['liquidity']='MAKER_REPORTED' if liquidity and all(v in ('M','MAKER') for v in liquidity) else 'TAKER_REPORTED' if liquidity and all(v in ('T','TAKER') for v in liquidity) else 'UNKNOWN'
            original=order.get('status');quantity=totals['base_qty']
            if original in ('FILLED','COMPLETED') and quantity<=0:raise BetaBlocked('FILLED_WITHOUT_FILL_EVIDENCE')
            state=('FILLED' if original in ('FILLED','COMPLETED') else
                'CANCELED_PARTIAL' if quantity else 'CANCELED_UNFILLED') if original in ('FILLED','COMPLETED','CANCELED','CANCELLED','EXPIRED') else (
                'REJECTED' if original in ('FAILED','REJECTED') else 'PARTIAL' if quantity else 'OPEN' if original in ('OPEN','PENDING','ACTIVE') else 'UNKNOWN')
            report.update(state=state if complete else 'HISTORY_INCOMPLETE',reason='OBSERVED_NATIVE_FILLS_NOT_BOT_EXECUTION')
            quote=pair.split('-')[1]
            if complete and (not fills or all(v==quote for v in currencies)):
                gross,fee=totals['quote_qty'],totals['fees']
                if side=='SELL' and fee>gross:raise BetaBlocked('FEE_EXCEEDS_PROCEEDS')
                report.update(native_settlement='KNOWN_FILL_FLOW_NOT_ACCOUNT_RECONCILIATION',
                    base_change=quantity if side=='BUY' else -quantity,
                    quote_change=-(gross+fee) if side=='BUY' else gross-fee)
            elif any(v is None for v in currencies):report['reason']='FEE_CURRENCY_UNREPORTED'
            else:report['reason']='FEE_ASSET_NOT_SUPPORTED_FOR_EXACT_FLOW'
    except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError):
        report.update(state='HISTORY_INCOMPLETE',native_settlement='UNKNOWN',reason='MISSING_OR_CONFLICTING_NATIVE_EVIDENCE')
    return report


class ReadOnlyAPI:
    """Expose references to GET methods only, never a broker/write interface."""
    __slots__=('_methods',)
    NAMES=('get_api_key_permissions','list_orders','get_order','get_fills','get_accounts')
    def __init__(self,client):self._methods={name:getattr(client,name) for name in self.NAMES}
    def call(self,name,**kwargs):
        if name not in self._methods:raise BetaBlocked('NON_READ_METHOD_BLOCKED')
        return as_dict(self._methods[name](**kwargs))


class HistoryReader:
    def __init__(self,api,*,cancel=None,clock=time.time,monotonic=time.monotonic):
        if not isinstance(api,ReadOnlyAPI):raise BetaBlocked('VIEW_ONLY_INTERFACE_REQUIRED')
        self.api=api;self.cancel=cancel;self.clock=clock;self.monotonic=monotonic
        self.calls=0;self.started=monotonic();self.portfolio=None

    def read(self,name,**kwargs):
        if self.cancel is not None and self.cancel.is_set():raise BetaBlocked('READ_IMPORT_CANCELED')
        if self.calls>=MAX_CALLS or self.monotonic()-self.started>120:raise BetaBlocked('READ_IMPORT_BUDGET_EXHAUSTED')
        self.calls+=1
        try:return self.api.call(name,**kwargs)
        except Exception:raise BetaBlocked('HISTORY_READ_UNAVAILABLE_WITH_CURRENT_ACCESS') from None

    def scope(self):
        permissions=self.read('get_api_key_permissions')
        if permissions.get('can_view') is not True:raise BetaBlocked('NOT_ACCESSIBLE_WITH_CURRENT_PORTFOLIO_OR_PERMISSIONS')
        self.portfolio=identity(permissions.get('portfolio_uuid'));return self.portfolio

    def one(self,oid):
        oid=identity(oid)
        if self.portfolio is None:self.scope()
        before=self.read('get_order',order_id=oid).get('order')
        if not isinstance(before,dict) or before.get('order_id')!=oid or before.get('retail_portfolio_id')!=self.portfolio or before.get('product_id') not in WATCH_PAIRS:
            raise BetaBlocked('HISTORICAL_ORDER_SCOPE_MISMATCH')
        expected=fill_count(before.get('number_of_fills'))
        fills={};cursor=None;seen=set();complete=False
        # Explicit order IDs, not the creation-window filter: late fills remain.
        for _ in range(16):
            args=dict(order_ids=[oid],retail_portfolio_id=self.portfolio,limit=100)
            if cursor:args['cursor']=cursor
            page=self.read('get_fills',**args);items=page.get('fills')
            if not isinstance(items,list) or len(items)>MAX_FILLS:raise BetaBlocked('HISTORICAL_FILL_PAGE_INVALID')
            for raw in items:
                if raw.get('order_id')!=oid or raw.get('retail_portfolio_id')!=self.portfolio or raw.get('product_id')!=before['product_id']:
                    raise BetaBlocked('HISTORICAL_FILL_SCOPE_MISMATCH')
                tid=fill_identity(raw.get('trade_id'))
                if tid in fills and digest(fills[tid])!=digest(raw):raise BetaBlocked('HISTORICAL_FILL_CONFLICT')
                fills[tid]=deepcopy(raw)
            if len(fills)>expected:raise BetaBlocked('HISTORICAL_FILL_TOTAL_CONFLICT')
            next_cursor=page.get('cursor')
            if page.get('has_next') is False or (page.get('has_next') is None and not next_cursor):
                complete=len(fills)==expected;break
            cursor=next_cursor
            if not isinstance(cursor,str) or not cursor or cursor in seen:break
            seen.add(cursor)
        after=self.read('get_order',order_id=oid).get('order')
        stable=('order_id','retail_portfolio_id','product_id','side','status','filled_size','filled_value','total_fees','number_of_fills')
        complete=complete and isinstance(after,dict) and all(before.get(k)==after.get(k) for k in stable)
        if not isinstance(after,dict):raise BetaBlocked('HISTORICAL_ORDER_DETAIL_MISSING')
        rows=list(fills.values());report=order_report(after,rows,portfolio=self.portfolio,complete=complete)
        return dict(order=deepcopy(after),fills=rows,report=report,received_at=self.clock(),complete=complete,
            source='VERIFIED_EXCHANGE_HISTORICAL_READ')

    def window(self,start,end):
        if self.portfolio is None:self.scope()
        if not 0<end-start<=7*86400 or end>self.clock()+5:raise BetaBlocked('NARROW_UTC_IMPORT_WINDOW_REQUIRED')
        def iso(stamp):return datetime.fromtimestamp(stamp,timezone.utc).isoformat()
        orders={};cursor=None;seen=set();complete=False
        for _ in range(16):
            args=dict(product_ids=list(WATCH_PAIRS),product_type='SPOT',retail_portfolio_id=self.portfolio,
                start_date=iso(start),end_date=iso(end),limit=50)
            if cursor:args['cursor']=cursor
            page=self.read('list_orders',**args)
            if not isinstance(page.get('orders'),list):raise BetaBlocked('HISTORICAL_ORDER_PAGE_INVALID')
            for order in page['orders']:
                if order.get('retail_portfolio_id')!=self.portfolio or order.get('product_id') not in WATCH_PAIRS:
                    raise BetaBlocked('HISTORICAL_ORDER_SCOPE_MISMATCH')
                if not start<=utc_stamp(order.get('created_time'))<=end:raise BetaBlocked('HISTORICAL_TIME_FILTER_CONFLICT')
                orders[identity(order.get('order_id'))]=order
                if len(orders)>MAX_ORDERS:raise BetaBlocked('HISTORICAL_ORDER_BOUND')
            if page.get('has_next') is False:complete=True;break
            cursor=page.get('cursor')
            if page.get('has_next') is not True or not isinstance(cursor,str) or not cursor or cursor in seen:break
            seen.add(cursor)
        records=[];reason='COMPLETE' if complete else 'ORDER_PAGINATION_INCOMPLETE'
        for oid in orders:
            try:records.append(self.one(oid))
            except BetaBlocked:
                complete=False;reason='IMPORT_INTERRUPTED_OR_RECORD_INCOMPLETE';break
        return dict(records=records,complete=complete,reason=reason,portfolio=self.portfolio,at=self.clock())

    def account_snapshot(self):
        if self.portfolio is None:self.scope()
        available={};holds={};cursor=None;seen=set();accounts=set()
        for _ in range(16):
            args=dict(retail_portfolio_id=self.portfolio,limit=250)
            if cursor:args['cursor']=cursor
            page=self.read('get_accounts',**args)
            if not isinstance(page.get('accounts'),list):raise BetaBlocked('LIVE_BALANCE_PAGE_INVALID')
            for raw in page['accounts']:
                if raw.get('retail_portfolio_id')!=self.portfolio:raise BetaBlocked('LIVE_BALANCE_PORTFOLIO_UNVERIFIED')
                aid=identity(raw.get('uuid'))
                if aid in accounts:raise BetaBlocked('DUPLICATE_ACCOUNT_SNAPSHOT')
                accounts.add(aid);asset=raw.get('currency')
                if asset not in WATCH_ASSETS:continue
                amount=exact((raw.get('available_balance') or {}).get('value'));held=exact((raw.get('hold') or {}).get('value'))
                if amount<0 or held<0:raise BetaBlocked('LIVE_ACCOUNT_AMOUNT_INVALID')
                available[asset]=available.get(asset,D(0))+amount;holds[asset]=holds.get(asset,D(0))+held
            if page.get('has_next') is False:return dict(at=self.clock(),portfolio=self.portfolio,available=available,holds=holds,
                mapping='AVAILABLE_ALREADY_EXCLUDES_VENUE_HOLDS_DO_NOT_SUBTRACT_TWICE')
            cursor=page.get('cursor')
            if page.get('has_next') is not True or not cursor or cursor in seen:break
            seen.add(cursor)
        raise BetaBlocked('LIVE_BALANCE_PAGINATION_INCOMPLETE')


class ManualTradeStore:
    def __init__(self,path):
        self.path=Path(path);self.store=None;self.problem=None
        if self.path.exists():
            try:self.store=BetaStore(path,APP_ID,validate=self.validate)
            except (ValueError,OSError,TypeError):self.problem='MANUAL_STORE_REVIEW_REQUIRED'

    @staticmethod
    def validate(state):
        if state.get('schema')!=1 or len(state.get('orders',{}))>MAX_ORDERS or len(state.get('fills',{}))>MAX_FILLS or len(state.get('runs',[]))>128:
            raise BetaBlocked('MANUAL_OBSERVATION_STORE_BOUND')

    def append(self,run):
        if self.problem:raise BetaBlocked(self.problem)
        if self.store is None:self.store=BetaStore(self.path,APP_ID,initial=dict(schema=1,orders={},fills={},runs=[]),validate=self.validate)
        def save(s):
            for record in run['records']:
                order=record['order'];key=identity(run['portfolio'])+'_'+identity(order['order_id'])
                history=s['orders'].setdefault(key,[])
                immutable=('order_id','retail_portfolio_id','product_id','side','created_time')
                if history and any(history[-1]['order'].get(k)!=order.get(k) for k in immutable):
                    record=deepcopy(record);record['report'].update(state='HISTORY_INCOMPLETE',reason='IMMUTABLE_ORDER_IDENTITY_CONFLICT')
                if (not history or digest(history[-1]['order'])!=digest(order) or digest(history[-1]['fills'])!=digest(record['fills']) or
                        digest(history[-1]['report'])!=digest(record['report']) or history[-1]['complete']!=record['complete']):
                    if len(history)>=32:raise BetaBlocked('MANUAL_ORDER_REVISION_BOUND')
                    history.append(deepcopy(record))
                for fill in record['fills']:
                    tid=key+'_'+fill_identity(fill['trade_id']);previous=s['fills'].get(tid)
                    if previous is not None and digest(previous)!=digest(fill):
                        history[-1]['report'].update(state='HISTORY_INCOMPLETE',reason='FILL_CORRECTION_REQUIRES_RECONCILIATION',native_settlement='UNKNOWN')
                    elif previous is None:s['fills'][tid]=deepcopy(fill)
            s['runs'].append(dict(at=run['at'],complete=run['complete'],reason=run['reason'],records=len(run['records'])))
        self.store.change('IMPORT_HISTORY',uuid.uuid4().hex,run,save)

    def records(self):
        return [] if self.store is None else [deepcopy(history[-1]) for history in self.store.state()['orders'].values()]

    def public(self):
        records=self.records();reports=[r['report'] for r in records]
        return dict(state='UNAVAILABLE' if self.problem else 'OBSERVED' if reports else 'UNOBSERVED',
            orders=len(reports),filled=sum(r['state']=='FILLED' for r in reports),
            partials=sum(r['state'] in ('PARTIAL','CANCELED_PARTIAL') for r in reports),
            canceled_unfilled=sum(r['state']=='CANCELED_UNFILLED' for r in reports),
            known_native_flow=sum(r['native_settlement']=='KNOWN_FILL_FLOW_NOT_ACCOUNT_RECONCILIATION' for r in reports),
            unknown=sum(r['state']=='HISTORY_INCOMPLETE' or r['native_settlement']=='UNKNOWN' for r in reports),
            account_reconciliation='UNKNOWN',execution_authority=False,sample_warning='SMALL_SELECTED_SAMPLE_NO_DEMONSTRATED_EDGE')
