"""Native order, inventory and evidence services, independent of strategy.

Only per-click manual grants can create actual orders. Shadow authorization is
an explicit different type and is rejected by the authenticated write adapter.
No automatic-live grant is implemented in this patch.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal as D,localcontext
import math

from coinbase_account import as_dict
from coincat_beta_store import BetaBlocked,digest
from coincat_manual_trade import HistoryReader,ReadOnlyAPI,identity,explicit_size_flag,explicit_fee_currency
from coincat_fill_units import normalize_fill
from coincat_execution_limits import native_math
from coincat_spot_market import limit_rules
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

@dataclass(frozen=True)
class ShadowAuthorization:
    classification:str='READ_ONLY_SHADOW_NO_LIVE_AUTHORITY'

@dataclass(frozen=True)
class ManualAuthorization:
    reference:str
    nonce:object

class PortfolioInventory:
    """Available already excludes venue holds. Local reserves are separate."""
    def __init__(self,snapshot):
        self.snapshot=deepcopy(snapshot);identity(snapshot['portfolio'])
        if not math.isfinite(float(snapshot['at'])):raise BetaBlocked('INVALID_INVENTORY_TIME')
        for field in ('available','holds'):
            values=snapshot.get(field)
            if not isinstance(values,dict) or not set(values)<=set(WATCH_ASSETS):raise BetaBlocked('INVALID_INVENTORY_ASSETS')
            if any(exact(v)<0 for v in values.values()):raise BetaBlocked('INVALID_INVENTORY_QUANTITY')
    def available(self,asset,reserved=D(0)):
        if asset not in WATCH_ASSETS:raise BetaBlocked('INVENTORY_ASSET_OUTSIDE_SCOPE')
        reserve=exact(reserved);available=exact(self.snapshot['available'].get(asset,D(0)))
        if not 0<=reserve<=available:raise BetaBlocked('LOCAL_RESERVATION_EXCEEDS_AVAILABLE')
        return available-reserve

@native_math
def native_fill_changes(raw):
    """Actual supplied commissions once, in reported native units. No estimates."""
    explicit_size_flag(raw.get('size_in_quote'));value=normalize_fill(raw)
    currency=explicit_fee_currency(raw)
    if currency is None:raise BetaBlocked('COMMISSION_CURRENCY_UNKNOWN')
    pair=raw.get('product_id');side=raw.get('side')
    if pair not in WATCH_PAIRS or side not in ('BUY','SELL'):raise BetaBlocked('SETTLEMENT_NATIVE_SCOPE_INVALID')
    base,quote=pair.split('-');changes={a:D(0) for a in WATCH_ASSETS}
    changes[base]+=value['base_qty'] if side=='BUY' else -value['base_qty']
    changes[quote]+=-value['quote_qty'] if side=='BUY' else value['quote_qty']
    changes[currency]-=value['commission']
    return dict(changes=changes,base_qty=value['base_qty'],gross_quote=value['quote_qty'],
        commission=value['commission'],fee_currency=currency)

def ticket_values(ticket,rules,book):
    pair=ticket.get('pair');side=ticket.get('side');post=ticket.get('post_only')
    if pair not in WATCH_PAIRS or side not in ('BUY','SELL') or type(post) is not bool:raise BetaBlocked('INVALID_MANUAL_TICKET')
    size,price=exact(ticket.get('size')),exact(ticket.get('price'))
    (inc,minimum,min_quote,maximum,max_quote),tick=limit_rules(pair,rules)
    with localcontext() as context:
        context.prec=80
        if size<=0 or price<=0 or size%inc or price%tick:raise BetaBlocked('USE_EXACT_NATIVE_SIZE_AND_PRICE_INCREMENTS')
        value=size*price
        if size<minimum or (maximum is not None and size>maximum) or value<min_quote or (max_quote is not None and value>max_quote):
            raise BetaBlocked('ORDER_OUTSIDE_EXCHANGE_NATIVE_MINIMUM_OR_MAXIMUM')
    if rules.get('post_only') is True and not post:raise BetaBlocked('EXCHANGE_REQUIRES_POST_ONLY')
    if post and (price>=book['ask'] if side=='BUY' else price<=book['bid']):
        raise BetaBlocked('POST_ONLY_PRICE_WOULD_TAKE_USE_BID_FOR_BUY_OR_ASK_FOR_SELL')
    return dict(pair=pair,side=side,size=size,price=price,post_only=post)

def bind_owned_order(order,raw,portfolio):
    config=(raw.get('order_configuration') or {}).get('limit_limit_gtc') or {}
    if (raw.get('client_order_id')!=order['cid'] or raw.get('retail_portfolio_id')!=portfolio or
            raw.get('product_id')!=order['pair'] or raw.get('side')!=order['side'] or
            exact(config.get('base_size'))!=order['size'] or exact(config.get('limit_price'))!=order['price'] or
            config.get('post_only') is not order['post_only']):raise BetaBlocked('OWNED_ORDER_IMMUTABLE_FIELDS_CONFLICT')

class LimitOrderServices:
    def __init__(self,reader_provider,*,manual_guard,owned_guard,clock):
        self._reader_provider=reader_provider;self._manual_guard=manual_guard;self._owned_guard=owned_guard
        self.clock=clock;self._grants={}
    def _reader(self):return self._reader_provider()
    def check_no_retries(self):
        session=getattr(self._reader().client,'session',None)
        if session is not None and session.get_adapter('https://api.coinbase.com').max_retries.total not in (0,False):
            raise BetaBlocked('AUTOMATIC_TRANSPORT_RETRIES_NOT_ALLOWED')
    @staticmethod
    def _args(ticket,portfolio):
        if ticket['pair'] not in WATCH_PAIRS or ticket['side'] not in ('BUY','SELL') or type(ticket['post_only']) is not bool:
            raise BetaBlocked('INVALID_NATIVE_LIMIT_COMMAND')
        return dict(product_id=ticket['pair'],base_size=format(exact(ticket['size']),'f'),
            limit_price=format(exact(ticket['price']),'f'),post_only=ticket['post_only'],retail_portfolio_id=identity(portfolio))
    def preview(self,ticket,portfolio):
        self.check_no_retries()
        return as_dict(getattr(self._reader().client,'preview_limit_order_gtc_'+ticket['side'].lower())(**self._args(ticket,portfolio)))
    def manual_grant(self,cid,ticket,portfolio):
        cid=identity(cid)
        if not self._manual_guard(cid):raise BetaBlocked('NO_EXPLICIT_MANUAL_DISPATCH_GRANT')
        if cid in self._grants:raise BetaBlocked('MANUAL_GRANT_ALREADY_ISSUED')
        nonce=object();self._grants[cid]=(nonce,digest(dict(ticket=ticket,portfolio=portfolio)))
        return ManualAuthorization(cid,nonce)
    def create(self,ticket,portfolio,authorization):
        if type(authorization) is not ManualAuthorization:raise BetaBlocked('AUTOMATIC_LIVE_PILOT_NOT_IMPLEMENTED')
        cid=identity(authorization.reference);grant=self._grants.get(cid)
        if (grant is None or grant[0] is not authorization.nonce or
                grant[1]!=digest(dict(ticket=ticket,portfolio=portfolio)) or not self._manual_guard(cid)):
            raise BetaBlocked('MANUAL_DISPATCH_GRANT_INVALID_OR_CONSUMED')
        self.check_no_retries();del self._grants[cid]
        return as_dict(getattr(self._reader().client,'limit_order_gtc_'+ticket['side'].lower())(
            client_order_id=cid,**self._args(ticket,portfolio)))
    def cancel_owned(self,order):
        if not self._owned_guard(order['cid'],order['order_id']):raise BetaBlocked('CANCEL_REQUIRES_OWNED_ORDER_IDENTITY')
        return as_dict(self._reader().client.cancel_orders(order_ids=[identity(order['order_id'])]))
    def history(self,oid,portfolio):
        r=self._reader();reader=HistoryReader(ReadOnlyAPI(r.client),clock=self.clock,monotonic=r.monotonic)
        reader.portfolio=identity(portfolio);reader.read=lambda name,**kwargs:r.call(name,**kwargs)
        return reader.one(identity(oid))
