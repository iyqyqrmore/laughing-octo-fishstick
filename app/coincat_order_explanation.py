"""Private ticket construction and four separate answers; no execution adapter."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_assumed_math import fee_rate,rounded
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_multi_policy import MultiConfig,assess_horizon
from coincat_horizon_forecast import HORIZONS
from coincat_order_services import ticket_values,native_fill_changes
from coincat_portfolio_policy import maker_price
from coincat_spot_market import limit_rules
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

@native_math
def minimum_budget(frame,pair,side):
    price=maker_price(frame,pair,side,0);rules,_=limit_rules(pair,frame['rules'][pair]);inc,minbase,minquote,_,_=rules
    quantity=rounded(max(minbase,minquote/price),inc,up=True);rate=fee_rate(frame,'MAKER')
    return quantity*price*(1+rate) if side=='BUY' else quantity

@native_math
def construct(frame,available,pair,side,budget,*,price=None):
    if pair not in WATCH_PAIRS or side not in ('BUY','SELL'):raise BetaBlocked('CONSTRUCTION_MARKET_OR_SIDE_INVALID')
    rate=fee_rate(frame,'MAKER');p=maker_price(frame,pair,side,0) if price is None else exact(price);source=pair.split('-')[1] if side=='BUY' else pair.split('-')[0]
    amount=exact(budget)
    if amount<=0 or p<=0:raise BetaBlocked('CONSTRUCTION_POSITIVE_NATIVE_BUDGET_REQUIRED')
    rules,tick=limit_rules(pair,frame['rules'][pair]);inc=rules[0]
    quantity=rounded(amount/(p*(1+rate)) if side=='BUY' else amount,inc)
    ticket=dict(pair=pair,side=side,size=quantity,price=p,post_only=True)
    ticket_values(ticket,frame['rules'][pair],frame['books'][pair])
    flow=native_fill_changes(dict(product_id=pair,side=side,size=quantity,price=p,size_in_quote=False,
        commission=quantity*p*rate,fee_currency=pair.split('-')[1]))
    debit=-flow['changes'][source]
    if debit>amount or debit>exact(available.get(source,0)):raise BetaBlocked('CONSTRUCTION_SOURCE_FUNDS_INSUFFICIENT')
    target=pair.split('-')[0] if side=='BUY' else pair.split('-')[1]
    return dict(ticket=ticket,source=source,target=target,source_budget=amount,source_debit=debit,unused_budget=amount-debit,
        base_quantity=quantity,estimated_destination=flow['changes'][target],estimated_commission=flow['commission'],fee_currency=flow['fee_currency'],
        fee_evidence='AUTHENTICATED_RATE_WITH_DECLARED_QUOTE_CURRENCY_MODEL',base_increment=inc,price_increment=tick,
        base_minimum=rules[1],quote_minimum=rules[2],available_source=exact(available.get(source,0)))

def explain(frame,wallet,available,original,pair,side,budget,*,price=None,config=None):
    result=dict(validity=dict(state='UNKNOWN',reason='FRESH_NATIVE_INPUTS_REQUIRED'),economics=dict(state='UNKNOWN',reason='NO_SUPPORTED_HORIZON'),
        execution=dict(state='UNKNOWN',reason='MAKER_FILL_PROBABILITY_NOT_CALIBRATED'),
        authorization=dict(state='SHADOW_ONLY',automatic_live_authority=False,manual_click='SEPARATE_EXISTING_MANUAL_ROUTE'),construction=None,horizons={})
    try:result['construction']=construct(frame,available,pair,side,budget,price=price)
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
        result['validity']=dict(state='BLOCKED',reason=str(exc) if isinstance(exc,BetaBlocked) else 'NATIVE_INPUTS_UNAVAILABLE');return result
    result['validity']=dict(state='NATIVE_RULES_AND_FUNDS_PASS',reason='NOT_AN_EXCHANGE_ACCEPTANCE_OR_PERMISSION_RECEIPT')
    config=config or MultiConfig();ticket=result['construction']['ticket'];supported=[]
    for name in HORIZONS:
        try:row=assess_horizon(frame,wallet,original,config,ticket,name);supported.append(row)
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:row=dict(state='HOLD',reason=str(exc) if isinstance(exc,BetaBlocked) else 'HORIZON_INPUTS_UNVERIFIED',selected_horizon=name)
        result['horizons'][name]=row
    qualifying=[r for r in supported if r['state']=='QUALIFIED']
    result['economics']=dict(state='QUALIFIED' if qualifying else 'HOLD',reason='POSITIVE_SUPPORTED_HORIZON_ADVANTAGE' if qualifying else 'NO_SUPPORTED_POSITIVE_HORIZON',
        best=None if not qualifying else deepcopy(max(qualifying,key=lambda r:r['projected_advantage_usd'])))
    tape=frame.get('market_trades') or {}
    if tape.get('pair')==pair and 0<=frame['at']-tape.get('at',0)<=30:
        result['execution']=dict(state='CONDITIONAL_PUBLIC_EVIDENCE_ONLY',reason='PUBLIC_TRADES_AND_VALID_TICKET_DO_NOT_PROVE_OUR_QUEUE_OR_FILL')
    return result

@native_math
def reported_manual_example():
    quantity=D('.00496514');price=D('.028457');gross=quantity*price;estimate=gross*D('.005')
    return dict(evidence='USER_REPORTED_MANUAL_EXERCISE_NOT_API_SETTLEMENT',pair='ETH-BTC',side='BUY',source='BTC',target='ETH',
        quantity=quantity,limit_price=price,computed_gross_btc=gross,reported_maker_estimate=D('.005'),modeled_fee_btc=estimate,
        modeled_all_in_btc=gross+estimate,actual_unrounded_commission=None,actual_settlement='UNKNOWN',
        validity='REPORTED_ACCEPTED_AND_FILLED_NOT_INDEPENDENTLY_VERIFIED',
        economics='UNKNOWN_ORIGINAL_QUOTES_RULES_AVAILABLE_FUNDS_AND_FORECAST_INPUTS_NOT_CAPTURED',
        execution='ONE_REPORTED_FILL_IN_ABOUT_65_SECONDS_NOT_A_FILL_PROBABILITY',
        authorization='EXTERNAL_MANUAL_ORDER_NO_AUTOMATIC_AUTHORITY',original_screen_timezone='UNKNOWN')
