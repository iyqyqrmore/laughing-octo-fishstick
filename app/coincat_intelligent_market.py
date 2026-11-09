"""Current USD valuation references are distinct from native order products."""
from decimal import Decimal as D
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_assumed_math import fee_rate
from coincat_portfolio_policy import valid_book
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

REFERENCES=tuple(a+'-USD' for a in WATCH_ASSETS)

@native_math
def marks(frame,*,admission=False):
    refs=frame.get('reference_books',{});result={};stamps=[]
    for asset in WATCH_ASSETS:
        pair=asset+'-USD';book=valid_book(dict(books=refs,at=frame['at']),pair,admission=admission)
        result[asset]=(book['bid']+book['ask'])/2;stamps.append(book['at'])
    if max(stamps)-min(stamps)>12:raise BetaBlocked('INTELLIGENT_REFERENCES_ASYNCHRONOUS')
    return result,tuple(stamps)

def can_decide(frame,valid=False):
    try:fee_rate(frame,'MAKER');marks(frame,admission=True);return True
    except (ValueError,TypeError,KeyError,ArithmeticError):return False

def quality(frame):
    coverage=0;stamps=[]
    for pair in WATCH_PAIRS:
        try:book=valid_book(frame,pair,admission=False);coverage+=1;stamps.append(book['at'])
        except (ValueError,TypeError,KeyError,ArithmeticError):pass
    try:
        _,refstamps=marks(frame);fee_rate(frame,'MAKER')
        return bool(coverage==7 and max(tuple(stamps)+refstamps)-min(tuple(stamps)+refstamps)<=12),coverage
    except (ValueError,TypeError,KeyError,ArithmeticError):return False,coverage

def coverage(frame,now=None):
    if not frame:return 0,0
    if now is not None:frame=dict(frame,at=now)
    native=quality(frame)[1];references=0
    for pair in REFERENCES:
        try:valid_book(dict(books=frame.get('reference_books',{}),at=frame['at']),pair,admission=False);references+=1
        except (ValueError,TypeError,KeyError,ArithmeticError):pass
    return native,references

def decision_fresh(frame,now):
    try:return all(0<=now-at<=30 for at in marks(frame)[1])
    except (ValueError,TypeError,KeyError,ArithmeticError):return False
