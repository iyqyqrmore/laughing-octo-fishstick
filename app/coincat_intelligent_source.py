"""Bounded native books and maker fee, plus a separate hourly forecast cache."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_beta_store import BetaBlocked
from coincat_forecast_24h import ForecastConfig
from coincat_opportunity_venue import parse_trades
from coincat_intelligent_market import REFERENCES
from coincat_spot_market import native_book
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS

class IntelligentSource:
    def __init__(self,reader,history):
        self.reader=reader;self.history=history;self.checked={};self.product_rules={};self.maker_tier=None;self.fee_retry=0;self.forecast_bundle=None
    def collect(self,pair=None,model=None,*,include_multi=False):
        r=self.reader;r.begin();r.deadline=min(r.deadline,r.started+6);scope=r.scope();now=r.clock()
        prime=any(p not in self.checked or not 0<=now-self.checked[p]<300 for p in WATCH_PAIRS)
        errors=[];rules={}
        for product in WATCH_PAIRS:
            if prime:
                try:self.product_rules[product]=r.call('get_product',product_id=product,get_tradability_status=True)
                except (ValueError,TypeError,KeyError,ArithmeticError):self.product_rules.pop(product,None);errors.append('PRODUCT_RULES_UNAVAILABLE')
                self.checked[product]=r.clock()
            if product in self.product_rules:rules[product]=deepcopy(self.product_rules[product])
        tier=self.maker_tier
        if (tier is None or not 0<=now-tier['at']<3600) and now>=self.fee_retry:
            try:
                raw=r.call('get_transaction_summary',product_type='SPOT').get('fee_tier') or {};maker=exact(raw.get('maker_fee_rate'))
                if not 0<=maker<D('.05'):raise BetaBlocked('FRESH_AUTHENTICATED_MAKER_FEE_REQUIRED')
                tier=dict(at=r.clock(),maker=maker,source='AUTHENTICATED_ACCOUNT_TIER');self.maker_tier=tier;self.fee_retry=0
            except (ValueError,TypeError,KeyError,ArithmeticError):tier=None;self.fee_retry=now+600
        if prime:return dict(state='PRIMING',portfolio=scope,account=deepcopy(r.account),errors=errors,at=r.clock())
        account=r.account
        if r.calls<16 and (account is None or now-account['at']>=30 or account['portfolio']!=scope):
            try:account=r.balances(scope)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('ACCOUNT_SNAPSHOT_UNAVAILABLE')
        books={};references={}
        for product in WATCH_PAIRS:
            try:books[product]=r.book(product)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('NATIVE_BOOK_UNAVAILABLE')
        for product in REFERENCES:
            try:references[product]=native_book(product,r.call('get_product_book',product_id=product,limit=20),r.clock())
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('VALUATION_REFERENCE_UNAVAILABLE')
        trades=None;trade_status='NO_ACTIVE_ORDER'
        if pair is not None:
            if pair not in WATCH_PAIRS:raise BetaBlocked('INTELLIGENT_TRADE_SCOPE_INVALID')
            try:
                trades=parse_trades(r.call('get_market_trades',product_id=pair,limit=100),pair,r.clock());trade_status='OBSERVED_PUBLIC_TRADES'
            except (ValueError,TypeError,KeyError,ArithmeticError):trade_status='PUBLIC_TRADE_EVIDENCE_UNAVAILABLE'
        at=r.clock();estimate=self.history.estimate(at,ForecastConfig(**(model or {})))
        if self.forecast_bundle is not None and self.forecast_bundle.backfill.reviewed('ONE_HOUR'):estimate=dict(state='HOLD',reason='FORECAST_HISTORY_REVIEW_REQUIRED')
        result=dict(state='OBSERVED',at=at,portfolio=scope,account=deepcopy(account),rules=rules,books=books,reference_books=references,tier=deepcopy(tier),
            market_trades=trades,trade_status=trade_status,forecast=estimate,errors=errors,
            provider='COINBASE_AUTHENTICATED_GET_ONLY',native_book_count=len(set(books)&set(WATCH_PAIRS)))
        if include_multi and self.forecast_bundle is not None:
            result['horizon_forecasts']=self.forecast_bundle.estimate(at,estimate)
            if self.forecast_bundle.backfill.reviewed('ONE_HOUR'):result['forecast']=dict(state='HOLD',reason='FORECAST_HISTORY_REVIEW_REQUIRED')
        return result
