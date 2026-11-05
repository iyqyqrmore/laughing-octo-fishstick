"""Shared pure execution bounds; no strategy, SDK or controller wiring."""
from dataclasses import dataclass
from decimal import Decimal as D,localcontext
from functools import wraps
from coincat_beta_store import BetaBlocked
from coincat_v80_immediate import exact

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
