"""Selected-market REST data for the manual client. No order authority."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal as D,localcontext
import time

from coinbase_account import as_dict
from coincat_beta_store import BetaBlocked
from coincat_manual_trade import HistoryReader,ReadOnlyAPI,identity
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS
from coincat_multicurrency import _rule
from coincat_v701_transport import BUDGET

GRANULARITIES={'1m':('ONE_MINUTE',60),'5m':('FIVE_MINUTE',300),'15m':('FIFTEEN_MINUTE',900),'1h':('ONE_HOUR',3600)}


def limit_rules(pair,raw):
    if (pair not in WATCH_PAIRS or raw.get('product_id')!=pair or raw.get('product_type')!='SPOT' or
            str(raw.get('status','')).lower()!='online' or raw.get('view_only') is not False):
        raise BetaBlocked('PRODUCT_NOT_TRADABLE_WITH_THIS_ACCOUNT')
    if any(raw.get(k) is True for k in ('trading_disabled','is_disabled','cancel_only','auction_mode')):
        raise BetaBlocked('PRODUCT_NOT_ACCEPTING_ORDERS')
    base,quote=pair.split('-')
    if raw.get('base_currency_id',base)!=base or raw.get('quote_currency_id',quote)!=quote:
        raise BetaBlocked('PRODUCT_CURRENCY_CONFLICT')
    rules=_rule({pair:raw},pair)
    if rules is None:raise BetaBlocked('PRODUCT_SIZE_RULES_UNAVAILABLE')
    tick=exact(raw.get('price_increment',raw.get('quote_increment')))
    if tick<=0:raise BetaBlocked('PRODUCT_PRICE_TICK_UNAVAILABLE')
    return rules,tick


def native_book(pair,response,at):
    raw=response.get('pricebook')
    if not isinstance(raw,dict) or raw.get('product_id')!=pair:raise BetaBlocked('BOOK_PRODUCT_UNVERIFIED')
    exchange_at=None
    if raw.get('time') is not None:
        try:
            stamp=datetime.fromisoformat(raw['time'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            exchange_at=stamp.timestamp()
            if not 0<=at-exchange_at<=30:raise ValueError()
        except (ValueError,TypeError,AttributeError,OverflowError):raise BetaBlocked('BOOK_EXCHANGE_TIMESTAMP_STALE_OR_INVALID') from None
    sides={}
    for side,reverse in (('bids',True),('asks',False)):
        levels=raw.get(side)
        if not isinstance(levels,list) or not 1<=len(levels)<=128:raise BetaBlocked('BOOK_LEVELS_UNAVAILABLE')
        result={}
        for row in levels:
            price,size=exact(row.get('price')),exact(row.get('size'))
            if not 0<price<=D('1e12') or not 0<size<=D('1e18') or price in result:
                raise BetaBlocked('BOOK_NATIVE_VALUES_INVALID')
            result[price]=size
        sides[side]=tuple(sorted(result.items(),reverse=reverse))
    bid,ask=sides['bids'][0][0],sides['asks'][0][0]
    if bid>=ask:raise BetaBlocked('BOOK_CROSSED_OR_LOCKED')
    return dict(pair=pair,at=at,exchange_at=exchange_at,bid=bid,ask=ask,**sides,source='COINBASE_REST_PRICEBOOK')


class SpotReader:
    """Bounded, paced reads on the app's one worker. No quote-touch fills."""
    def __init__(self,client,*,clock=time.time,monotonic=time.monotonic,budget=BUDGET):
        self.client=client;self.clock=clock;self.monotonic=monotonic;self.budget=budget
        self.begin();self.products={};self.books={};self.tier=None;self.account=None;self.permissions=None

    def begin(self):self.calls=0;self.started=self.monotonic();self.deadline=self.started+25

    def call(self,name,**kwargs):
        allowed={'get_api_key_permissions','get_product','get_product_book','get_accounts',
            'get_transaction_summary','get_public_candles','list_orders','get_order','get_fills','get_portfolio_breakdown'}
        if name not in allowed:raise BetaBlocked('READ_METHOD_NOT_ALLOWED')
        if self.calls>=16 or self.monotonic()>=self.deadline:raise BetaBlocked('READ_BUDGET_EXHAUSTED')
        self.calls+=1
        if self.budget is not None:self.budget.acquire(self.deadline)
        try:return as_dict(getattr(self.client,name)(**kwargs))
        except BetaBlocked:raise
        except Exception:raise BetaBlocked('COINBASE_READ_UNAVAILABLE') from None

    def scope(self,*,trading=False):
        p=self.call('get_api_key_permissions')
        if p.get('can_view') is not True:raise BetaBlocked('ACCOUNT_VIEW_PERMISSION_REQUIRED')
        portfolio=identity(p.get('portfolio_uuid'))
        if trading and (p.get('can_trade') is not True or p.get('can_transfer') is not False):
            raise BetaBlocked('TRADING_KEY_REQUIRES_TRADE_AND_TRANSFERS_DISABLED')
        self.permissions=dict(p,portfolio_uuid=portfolio,at=self.clock())
        return portfolio

    def balances(self,portfolio):
        # The existing bounded account reader retains exact portfolio, pagination
        # and native available/hold semantics. Available already excludes holds.
        api=ReadOnlyAPI(self.client);reader=HistoryReader(api,clock=self.clock,monotonic=self.monotonic)
        reader.portfolio=portfolio
        reader.read=lambda name,**kwargs:self.call(name,**kwargs)
        self.account=reader.account_snapshot();return deepcopy(self.account)

    def product(self,pair,*,force=False):
        if pair not in WATCH_PAIRS:raise BetaBlocked('MARKET_OUTSIDE_APPROVED_SEVEN')
        cached=self.products.get(pair)
        if not force and cached and 0<=self.clock()-cached['at']<300:return deepcopy(cached['rules'])
        rules=self.call('get_product',product_id=pair,get_tradability_status=True)
        limit_rules(pair,rules);self.products[pair]=dict(at=self.clock(),rules=deepcopy(rules))
        return rules

    def book(self,pair):
        if pair not in WATCH_PAIRS and pair!='ETH-USD':raise BetaBlocked('MARKET_OUTSIDE_APPROVED_SEVEN')
        value=native_book(pair,self.call('get_product_book',product_id=pair,limit=20),self.clock())
        self.books[pair]=deepcopy(value);return value

    def fees(self,*,force=False):
        if not force and self.tier and 0<=self.clock()-self.tier['at']<3600:return deepcopy(self.tier)
        raw=self.call('get_transaction_summary',product_type='SPOT').get('fee_tier') or {}
        maker,taker=exact(raw.get('maker_fee_rate')),exact(raw.get('taker_fee_rate'))
        if not 0<=maker<D('.05') or not 0<=taker<D('.05'):raise BetaBlocked('ACCOUNT_FEE_RATE_UNAVAILABLE')
        self.tier=dict(at=self.clock(),maker=maker,taker=taker,source='AUTHENTICATED_ACCOUNT_TIER')
        return deepcopy(self.tier)

    def fx(self,quote):
        # ETH-USD values a risk cap only; it never becomes an executable market.
        usd=self.book('ETH-USD')
        with localcontext() as context:
            context.prec=80
            if quote=='ETH':return dict(quote='ETH',usd_upper=usd['ask'],eth_upper=D(1),at=usd['at'])
            if quote!='BTC':raise BetaBlocked('UNSUPPORTED_NATIVE_QUOTE')
            cross=self.book('ETH-BTC')
            return dict(quote='BTC',usd_upper=usd['ask']/cross['bid'],eth_upper=1/cross['bid'],at=min(usd['at'],cross['at']))

    def candles(self,pair,interval='5m'):
        if pair not in WATCH_PAIRS or interval not in GRANULARITIES:raise BetaBlocked('CANDLE_SCOPE_INVALID')
        name,seconds=GRANULARITIES[interval];end=int(self.clock());start=end-seconds*120
        raw=self.call('get_public_candles',product_id=pair,start=str(start),end=str(end),granularity=name,limit=150)
        rows=raw.get('candles')
        if not isinstance(rows,list) or len(rows)>150:raise BetaBlocked('CANDLES_UNAVAILABLE')
        result={}
        for row in rows:
            at=int(row['start']);o,h,l,c,v=(exact(row[k]) for k in ('open','high','low','close','volume'))
            if not start-seconds<=at<=end or not 0<l<=min(o,c)<=max(o,c)<=h or v<0 or at in result:
                raise BetaBlocked('CANDLE_NATIVE_VALUES_INVALID')
            result[at]=dict(at=at,open=o,high=h,low=l,close=c,volume=v)
        return dict(pair=pair,interval=interval,seconds=seconds,candles=[result[k] for k in sorted(result)],
            source='COINBASE_PUBLIC_TRADE_CANDLES',at=self.clock())

    def recent_orders(self,portfolio):
        raw=self.call('list_orders',product_ids=list(WATCH_PAIRS),product_type='SPOT',
            retail_portfolio_id=portfolio,limit=50)
        rows=raw.get('orders')
        if not isinstance(rows,list) or len(rows)>50:raise BetaBlocked('ORDER_HISTORY_UNAVAILABLE')
        result=[]
        for row in rows:
            if row.get('retail_portfolio_id')!=portfolio or row.get('product_id') not in WATCH_PAIRS:
                raise BetaBlocked('ORDER_HISTORY_SCOPE_UNVERIFIED')
            identity(row.get('order_id'));result.append(deepcopy(row))
        return dict(orders=result,more=raw.get('has_next') is not False,at=self.clock())

    def snapshot(self,pair,*,account=False,candles=False,interval='5m',history=False):
        self.begin();portfolio=self.scope()
        if account or self.account is None or not 0<=self.clock()-self.account['at']<30:self.balances(portfolio)
        rules=self.product(pair);book=self.book(pair)
        errors=[]
        try:tier=self.fees()
        except (ValueError,TypeError,KeyError,ArithmeticError):tier=None;errors.append('ACCOUNT_FEE_RATE_UNAVAILABLE')
        chart=None
        if candles:
            try:chart=self.candles(pair,interval)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('CANDLES_UNAVAILABLE')
        orders=None
        if history:
            try:orders=self.recent_orders(portfolio)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('ORDER_HISTORY_UNAVAILABLE')
        return dict(pair=pair,at=self.clock(),rules=rules,book=book,tier=tier,account=deepcopy(self.account),
            permissions=deepcopy(self.permissions),chart=chart,history=orders,errors=errors)
