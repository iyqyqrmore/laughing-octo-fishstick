"""Bounded GET-only seven-book observations; never an exchange write adapter."""
from copy import deepcopy
from coincat_beta_store import BetaBlocked
from coincat_spot_market import limit_rules
from coincat_portfolio_policy import valid_book,usd_marks
from coincat_watchlist import WATCH_PAIRS
from coincat_v80_immediate import exact

def frame_quality(frame):
    coverage=0;stamps=[]
    for pair in WATCH_PAIRS:
        try:
            b=valid_book(frame,pair,admission=False);stamps.append(b['at']);coverage+=1
            limit_rules(pair,frame['rules'][pair])
        except (ValueError,TypeError,KeyError,ArithmeticError):continue
    try:
        if coverage!=7 or frame.get('state')!='OBSERVED':return False,coverage
        for pair in WATCH_PAIRS:limit_rules(pair,frame['rules'][pair])
        usd_marks(frame);stamps.append(frame['books']['ETH-USD']['at'])
        tier=frame['tier'];maker=exact(tier['maker'])
        valid=(max(stamps)-min(stamps)<=12 and 0<=frame['at']-tier['at']<=3600 and
            tier.get('source')=='AUTHENTICATED_ACCOUNT_TIER' and 0<=maker<exact('.05'))
        return valid,coverage
    except (ValueError,TypeError,KeyError,ArithmeticError):return False,coverage

class ShadowMarketSource:
    def __init__(self,reader):self._reader=reader;self.checked={};self.fee_retry=0
    def starting_inventory(self):
        r=self._reader;r.begin();scope=r.scope();return r.balances(scope)
    def collect(self):
        r=self._reader;r.begin();r.deadline=min(r.deadline,r.started+6);scope=r.scope();now=r.clock();account=r.account
        if account is not None and account['portfolio']!=scope:raise BetaBlocked('SHADOW_PORTFOLIO_SCOPE_CHANGED')
        prime=any(p not in self.checked or not 0<=now-self.checked[p]<300 for p in WATCH_PAIRS)
        errors=[];rules={}
        for pair in WATCH_PAIRS:
            if not prime and (pair not in r.products or not 0<=now-r.products[pair]['at']<300):
                errors.append(pair);continue
            try:rules[pair]=r.product(pair,force=prime)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append(pair)
            if prime:self.checked[pair]=r.clock()
        tier=r.tier
        if (tier is None or not 0<=now-tier['at']<3600) and now>=self.fee_retry:
            try:tier=r.fees();self.fee_retry=0
            except (ValueError,TypeError,KeyError,ArithmeticError):tier=None;self.fee_retry=now+600
        if prime:return dict(state='PRIMING',portfolio=scope,account=deepcopy(account),errors=errors,at=r.clock())
        books={}
        # All seven books are collected in this wave. A deferred/cached eighth
        # reference or missing cross-pair cannot masquerade as full coverage.
        for pair in WATCH_PAIRS+('ETH-USD',):
            try:books[pair]=r.book(pair)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append(pair)
        # Account snapshots only classify external actual changes; outages here
        # do not erase an already validated hypothetical baseline.
        if r.calls<16 and (account is None or now-account['at']>=60):
            try:account=r.balances(scope)
            except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('ACCOUNT_OBSERVATION_UNAVAILABLE')
        return dict(state='OBSERVED',at=r.clock(),portfolio=scope,account=deepcopy(account),rules=rules,
            books=books,tier=deepcopy(tier),errors=errors,selected=WATCH_PAIRS,
            provider='COINBASE_REST_GET_ONLY',native_book_count=len(books.keys()&set(WATCH_PAIRS)))
