"""Shared pure strategy decisions. No broker, SDK, account key or live authority."""
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
import math
from v106.fee_check import exact
from coincat_execution_limits import native_math
from v106.preregistered import SOURCE_FRACTION, MAX_SPREAD


def snap(value, tick, up=False):
    return (value/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick


def spread(frame):
    return (frame['ask']-frame['bid'])/((frame['ask']+frame['bid'])/2)


@native_math
def eth_btc_weight(wallet, frame):
    """Total owned quantities, including reservations; never available-only funds."""
    eth_btc=wallet['ETH']*(frame['bid']+frame['ask'])/2
    total=eth_btc+wallet['BTC']
    return eth_btc/total if total else None


@native_math
def side_for(name, params, wallet, frame, trail):
    if name=='ROUNDTRIP':
        weight=eth_btc_weight(wallet,frame)
        if weight is None or spread(frame)>MAX_SPREAD:return None
        return 'BUY' if weight<=D('.5') else 'SELL'
    eth_value=wallet['ETH']*frame['eth_usd']; value=eth_value+wallet['BTC']*frame['btc_usd']
    weight=eth_value/value
    if name=='HOLD50': return None
    if name=='BAND':
        return ('SELL' if weight>D('.5') else 'BUY') if abs(weight-D('.5'))>params['band'] else None
    if name!='RATIO': raise ValueError('Unknown strategy')
    if len(trail)<288: return None
    prices=list(trail)[-288:]; logs=[math.log(float(p)) for p in prices]
    mean=sum(logs)/len(logs); variance=sum((x-mean)**2 for x in logs)/(len(logs)-1)
    if variance<=0: return None
    z=(logs[-1]-mean)/math.sqrt(variance)
    move=abs(D(str(math.exp(mean)))/frame['close']-1)
    if abs(z)<=float(params['k']) or move<=4*frame['fee_rate']: return None
    return 'BUY' if z<0 else 'SELL'


@native_math
def quantity_for(name, side, wallet, frame, price, fee, rules, fraction=SOURCE_FRACTION):
    if not 0<fraction<=D('.5'): raise ValueError('Source fraction must be <=50%')
    if side=='BUY': maximum=wallet['BTC']*fraction/(price*(1+fee))
    else: maximum=wallet['ETH']*fraction
    desired=maximum
    if name=='BAND':
        eth_value=wallet['ETH']*frame['eth_usd']; total=eth_value+wallet['BTC']*frame['btc_usd']
        numerator=(total/2-eth_value) if side=='BUY' else (eth_value-total/2)
        denominator=(frame['eth_usd']+price*(1+fee if side=='BUY' else 1-fee)*frame['btc_usd'])/2
        desired=min(maximum,max(D(0),numerator/denominator))
    if rules.get('base_max_size'):desired=min(desired,exact(rules['base_max_size']))
    if rules.get('quote_max_size'):desired=min(desired,exact(rules['quote_max_size'])/price)
    return snap(desired,exact(rules['base_increment']))


def valid_size(q, price, rules):
    return (q>0 and q%exact(rules['base_increment'])==0 and q>=exact(rules['base_min_size']) and
        q*price>=exact(rules['quote_min_size']) and
        (not rules.get('base_max_size') or q<=exact(rules['base_max_size'])) and
        (not rules.get('quote_max_size') or q*price<=exact(rules['quote_max_size'])))


@native_math
def exit_price(side, entry_price, entry_fee, exit_fee, margin, tick):
    """Quote-coin fee model: entry BUY->exit SELL; entry SELL->exit BUY."""
    if side=='BUY':
        breakeven=entry_price*(1+entry_fee)/(1-exit_fee)
        return snap(breakeven+entry_price*margin,tick,up=True)
    breakeven=entry_price*(1-entry_fee)/(1+exit_fee)
    return snap(breakeven-entry_price*margin,tick)
