"""Explicit assumed-fill arithmetic. No client, grants or exchange fill claims."""
from copy import deepcopy
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import math
import uuid

from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_order_services import native_fill_changes,ticket_values
from coincat_portfolio_policy import valid_book,usd_marks,portfolio_value
from coincat_spot_market import limit_rules
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

CLASSIFICATION='ASSUMED_FILLS_NOT_EXECUTION_EVIDENCE'
FEE_MODEL='QUOTE_COMMISSION_EXACT_RATE_ASSUMPTION'
SEED_USD=D(100)

def rounded(value,increment,*,up=False):
    return (value/increment).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*increment

def observation_time(frame,now):
    at=frame.get('at')
    if type(at) not in (int,float) or not math.isfinite(at) or not 0<=now-at<=30:
        raise BetaBlocked('FRESH_LIVE_OBSERVATION_REQUIRED')
    if frame.get('state')!='OBSERVED':raise BetaBlocked('WAIT_FOR_NATIVE_MARKET_PRIMING')
    return at

@native_math
def initial_state(frame,now,buy_price='ASK'):
    if buy_price not in ('ASK','BID'):raise BetaBlocked('ASSUMED_BUY_PRICE_MUST_BE_ASK_OR_BID')
    at=observation_time(frame,now);marks,stamps=usd_marks(frame)
    if any(not 0<=now-at<=30 for at in stamps):raise BetaBlocked('FRESH_SEED_USD_REFERENCES_REQUIRED')
    # Fixed fictional funding, never account balances or a repeatedly minted seed.
    wallet={a:(SEED_USD/marks[a]).quantize(D('1e-18'),rounding=ROUND_FLOOR) for a in WATCH_ASSETS}
    if any(q<=0 for q in wallet.values()):raise BetaBlocked('SEED_VALUATION_OUTSIDE_NATIVE_RANGE')
    return dict(schema=1,classification=CLASSIFICATION,fee_model=FEE_MODEL,
        sandbox_id=uuid.uuid4().hex,started_at=now,seed_at=at,seed_usd_per_coin=SEED_USD,buy_price=buy_price,
        seed_marks=marks,original=deepcopy(wallet),wallet=wallet,fees_native={a:D(0) for a in WATCH_ASSETS},
        pairs={p:dict(next_side='BUY',last=None) for p in WATCH_PAIRS},
        sizing={p:D(0) for p in WATCH_PAIRS},settings_version=1,
        waves=0,orders=0,buys=0,sells=0,maker_orders=0,taker_orders=0,last_at=None)

def fee_rate(frame,kind):
    try:
        tier=frame.get('tier') or {};rate=exact(tier.get(kind.lower()))
        if (tier.get('source')!='AUTHENTICATED_ACCOUNT_TIER' or not 0<=frame['at']-tier['at']<=3600 or not 0<=rate<D('.05')):raise ValueError()
        return rate
    except (ValueError,TypeError,KeyError,ArithmeticError):raise BetaBlocked('FRESH_AUTHENTICATED_'+kind+'_FEE_REQUIRED') from None

@native_math
def plan(pair,side,frame,buy_price='ASK',*,wallet=None,percent=D(0),settings_version=1):
    """One minimum-size native leg, one applicable fee, no slippage surcharge."""
    if pair not in WATCH_PAIRS or side not in ('BUY','SELL'):raise BetaBlocked('ASSUMED_NATIVE_MARKET_OR_SIDE_INVALID')
    if buy_price not in ('ASK','BID'):raise BetaBlocked('ASSUMED_BUY_PRICE_MUST_BE_ASK_OR_BID')
    if pair not in frame.get('rules',{}):raise BetaBlocked('NATIVE_PRODUCT_RULES_UNAVAILABLE')
    raw=frame['rules'][pair];(inc,min_base,min_quote,max_base,max_quote),tick=limit_rules(pair,raw)
    b=valid_book(frame,pair,admission=False)
    price=exact(b['bid'] if side=='BUY' and buy_price=='BID' else b['ask'])
    kind='TAKER' if side=='BUY' and price>=exact(b['ask']) else 'MAKER'
    rate=fee_rate(frame,kind)
    # Base minimum, quote minimum and base increment all apply. Fees change
    # cost/proceeds, not this selected native book price or the base quantity.
    percent=exact(percent)
    if not 0<=percent<=100:raise BetaBlocked('NATIVE_SIZE_SLIDER_REQUIRES_ZERO_TO_100')
    minimum=rounded(max(min_base,min_quote/price),inc,up=True);maximum=None;size=minimum
    if wallet is not None:
        base,quote=pair.split('-');free=exact(wallet[quote if side=='BUY' else base])
        maximum=free/(price*(1+rate)) if side=='BUY' else free
        if max_base is not None:maximum=min(maximum,max_base)
        if max_quote is not None:maximum=min(maximum,max_quote/price)
        maximum=rounded(maximum,inc)
        if maximum<minimum:raise BetaBlocked('INSUFFICIENT_SIMULATED_SOURCE_INCLUDING_NATIVE_FEE')
        size=minimum+rounded((maximum-minimum)*percent/100,inc)
    elif percent:raise BetaBlocked('SIMULATED_INVENTORY_REQUIRED_FOR_SIZE_SLIDER')
    ticket=ticket_values(dict(pair=pair,side=side,post_only=kind=='MAKER',size=size,price=price),raw,b)
    # Product quote increments are NOT authenticated commission precision.
    # Keep the exact proportional estimate; do not invent a minimum/rounded fee.
    commission=size*price*rate
    if side=='SELL' and commission>=size*price:raise BetaBlocked('NATIVE_FEE_ROUNDING_EXCEEDS_PROCEEDS')
    quote=pair.split('-')[1]
    return dict(**ticket,commission=commission,fee_currency=quote,fee_rate=rate,fee_at=frame['tier']['at'],
        quote_total=size*price+(commission if side=='BUY' else -commission),
        fee_model=FEE_MODEL,fee_kind=kind,fee_precision='UNVERIFIED_EXACT_RATE_MODEL',slippage_fraction=D(0),bid=b['bid'],ask=b['ask'],
        min_size=minimum,max_affordable_size=maximum,allocation_percent=percent,settings_version=settings_version,
        book_at=b['at'],at=frame['at'],
        rules=deepcopy(raw),classification=CLASSIFICATION)

def fill_record(ticket,wave):
    return dict(ticket,order_id='SIM-'+uuid.uuid4().hex,trade_id='SIM-FILL-'+uuid.uuid4().hex,
        state='ASSUMED_FILLED',size_in_quote=False,product_id=ticket['pair'],wave=wave)

@native_math
def apply_record(state,record):
    """Feed only explicit synthetic commissions into canonical native settlement."""
    if (record.get('classification')!=CLASSIFICATION or record.get('fee_model')!=FEE_MODEL or
            record.get('state')!='ASSUMED_FILLED' or record.get('pair') not in WATCH_PAIRS or
            record.get('side') not in ('BUY','SELL') or record.get('size_in_quote') is not False or
            record.get('product_id')!=record['pair'] or record.get('fee_kind') not in ('MAKER','TAKER') or
            record.get('post_only') is not (record.get('fee_kind')=='MAKER') or record.get('slippage_fraction')!=0 or
            not isinstance(record.get('order_id'),str) or not record['order_id'].startswith('SIM-') or
            not isinstance(record.get('trade_id'),str) or not record['trade_id'].startswith('SIM-FILL-')):
        raise BetaBlocked('ASSUMED_RECEIPT_CLASSIFICATION_INVALID')
    size,price,rate,fee=(exact(record[k]) for k in ('size','price','fee_rate','commission'))
    if size<=0 or price<=0 or not 0<=rate<D('.05') or fee!=size*price*rate or record.get('fee_precision')!='UNVERIFIED_EXACT_RATE_MODEL':
        raise BetaBlocked('ASSUMED_NATIVE_FEE_INVALID')
    if record.get('quote_total')!=size*price+(fee if record['side']=='BUY' else -fee):raise BetaBlocked('ASSUMED_ONE_LEG_TOTAL_CONFLICT')
    pair=record['pair'];quote=pair.split('-')[1]
    if record['fee_currency']!=quote:raise BetaBlocked('ASSUMED_NATIVE_FEE_CURRENCY_CONFLICT')
    if record.get('settings_version')!=state['settings_version'] or record.get('allocation_percent')!=state['sizing'][pair]:
        raise BetaBlocked('ASSUMED_FUTURE_SIZING_VERSION_CONFLICT')
    if state['pairs'][pair]['next_side']!=record['side']:raise BetaBlocked('ASSUMED_DIRECTION_SEQUENCE_CONFLICT')
    expected_kind='TAKER' if record['side']=='BUY' and price>=record['ask'] else 'MAKER'
    expected_price=record['bid'] if record['side']=='BUY' and state['buy_price']=='BID' else record['ask']
    if record['fee_kind']!=expected_kind or price!=expected_price:raise BetaBlocked('ASSUMED_BOOK_PRICE_OR_FEE_KIND_CONFLICT')
    ticket_values(record,record['rules'],dict(bid=record['bid'],ask=record['ask']))
    model=dict(at=record['at'],rules={pair:record['rules']},books={pair:dict(pair=pair,at=record['book_at'],bid=record['bid'],ask=record['ask'])},
        tier=dict(at=record['fee_at'],source='AUTHENTICATED_ACCOUNT_TIER',**{record['fee_kind'].lower():rate}))
    chosen=plan(pair,record['side'],model,state['buy_price'],wallet=state['wallet'],percent=state['sizing'][pair],settings_version=state['settings_version'])
    if chosen['size']!=size:raise BetaBlocked('ASSUMED_MINIMUM_OR_APPLIED_SLIDER_SIZE_CONFLICT')
    flow=native_fill_changes(record)
    after={a:state['wallet'][a]+flow['changes'][a] for a in WATCH_ASSETS}
    if any(q<0 for q in after.values()):raise BetaBlocked('INSUFFICIENT_SIMULATED_SOURCE_INCLUDING_NATIVE_FEE')
    state['wallet']=after;state['fees_native'][quote]+=fee;state['orders']+=1
    state['buys' if record['side']=='BUY' else 'sells']+=1
    state['maker_orders' if record['fee_kind']=='MAKER' else 'taker_orders']+=1
    state['pairs'][pair]=dict(next_side='SELL' if record['side']=='BUY' else 'BUY',last=deepcopy(record))

@native_math
def marked_performance(state,frame,now):
    try:
        observation_time(frame,now);marks,stamps=usd_marks(frame)
        if any(not 0<=now-at<=30 for at in stamps):raise BetaBlocked('FRESH_USD_MARK_REFERENCES_REQUIRED')
        value=portfolio_value(state['wallet'],marks);hold=portfolio_value(state['original'],marks)
        return dict(at=frame['at'],portfolio_usd=value,hold_usd=hold,difference_usd=value-hold,
            initial_usd=portfolio_value(state['original'],state['seed_marks']),
            classification=CLASSIFICATION,valuation='MIDPOINT_BEFORE_EXIT_COSTS')
    except (ValueError,TypeError,KeyError,ArithmeticError):return None
