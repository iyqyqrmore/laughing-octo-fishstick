"""Prospective portfolio-value hypotheses. Pure; no order or live authority."""
from copy import deepcopy
from dataclasses import dataclass,asdict,field
from decimal import Decimal as D

from coincat_assumed_math import plan,fee_rate,initial_state
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_multicurrency import research_order
from coincat_order_services import native_fill_changes,ticket_values
from coincat_portfolio_policy import DIRECTIONS,usd_marks,portfolio_value,risk_estimate,utility,variance,valid_book,liquidity_screen
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

POLICY='OPPORTUNITY_PORTFOLIO_SHADOW_V1'

@dataclass(frozen=True)
class OpportunityConfig:
    min_observations:int=20
    horizon_steps:int=20
    risk_aversion:D=D(1)
    uncertainty_z:D=D('2.58')
    model_buffer_bps:D=D(5)
    improvement_ticks:int=0
    review_s:int=30
    reconsider_s:int=120
    order_lifetime_s:int=600
    campaign_lifetime_s:int=1800
    retry_budget:int=3
    queue_multiple:D=D(2)
    participation:D=D('.1')
    partial_fraction:D=D('.25')
    minimum_rest_s:int=30
    provider:str='TRADE_THROUGH_QUEUE_V1'
    size_percent:dict=field(default_factory=lambda:{p:D(0) for p in WATCH_PAIRS})

    def checked(self):
        values=asdict(self)
        for key in ('risk_aversion','uncertainty_z','model_buffer_bps','queue_multiple','participation','partial_fraction'):
            values[key]=exact(values[key])
        for key,low,high in (('min_observations',20,200),('horizon_steps',1,120),('improvement_ticks',0,100),
                ('order_lifetime_s',120,3600),('campaign_lifetime_s',120,14400),('retry_budget',0,10),('minimum_rest_s',30,300)):
            if type(values[key]) is not int or not low<=values[key]<=high:raise BetaBlocked('INVALID_OPPORTUNITY_INTEGER_SETTING')
        if values['review_s']!=30 or values['reconsider_s']!=120 or values['campaign_lifetime_s']<values['order_lifetime_s']:
            raise BetaBlocked('INVALID_OPPORTUNITY_REVIEW_OR_LIFETIME')
        if (not 0<=values['risk_aversion']<=100 or not 1<=values['uncertainty_z']<=10 or not 0<=values['model_buffer_bps']<=1000 or
                not 1<=values['queue_multiple']<=20 or not 0<values['participation']<=D('.25') or not 0<values['partial_fraction']<=D('.5')):
            raise BetaBlocked('INVALID_OPPORTUNITY_MODEL_SETTING')
        if values['provider'] not in ('TRADE_THROUGH_QUEUE_V1','NO_FILL_OBSERVATION_V1'):raise BetaBlocked('INVALID_OPPORTUNITY_PROVIDER')
        if set(values['size_percent'])!=set(WATCH_PAIRS):raise BetaBlocked('OPPORTUNITY_REQUIRES_SEVEN_SIZING_SETTINGS')
        values['size_percent']={p:exact(v) for p,v in values['size_percent'].items()}
        if any(not 0<=v<=100 for v in values['size_percent'].values()):raise BetaBlocked('INVALID_OPPORTUNITY_SIZE_PERCENT')
        return OpportunityConfig(**values)

def seed(frame,now):return initial_state(frame,now,'BID')

@native_math
def exit_mark_cost(pair,original_side,quantity,frame,marks,taker):
    """Sized reverse-conversion benchmark, never an instruction or booked fee."""
    if quantity==0:return D(0)
    base,quote=pair.split('-');source,target=(base,quote) if original_side=='BUY' else (quote,base)
    side='SELL' if original_side=='BUY' else 'BUY';book=valid_book(frame,pair)
    receipt=research_order(pair=pair,side=side,available=quantity,cap=quantity*marks[source],usd_rate=marks[source],
        book=(book['bid'],book['ask'],book['at']),product_rules=frame['rules'],fee=taker,slip=D(0),
        levels=[dict(price=p,size=q) for p,q in book['bids' if side=='SELL' else 'asks']])
    residue=quantity-receipt['input_quantity']
    return max(D(0),quantity*marks[source]-receipt['output_quantity']*marks[target]-residue*marks[source])

@native_math
def assess(frame,wallet,original,observations,config,ticket,*,resting=False):
    """Lower-bound advantage under a declared, unvalidated forecasting model."""
    config=config.checked();marks,stamps=usd_marks(frame);model=risk_estimate(observations,config)
    maker,taker=fee_rate(frame,'MAKER'),fee_rate(frame,'TAKER')
    pair,side=ticket['pair'],ticket['side'];base,quote=pair.split('-');book=valid_book(frame,pair)
    if max(stamps+(book['at'],))-min(stamps+(book['at'],))>12:raise BetaBlocked('OPPORTUNITY_DECISION_SPAN_EXCEEDS_12_SECONDS')
    if abs((book['bid']+book['ask'])/2*marks[quote]/marks[base]-1)>D('.01'):raise BetaBlocked('NATIVE_BOOK_USD_REFERENCE_CONFLICT')
    size,price=exact(ticket['size']),exact(ticket['price'])
    if size<=0 or price<=0:raise BetaBlocked('OPPORTUNITY_REMAINING_SIZE_INVALID')
    if not resting:ticket_values(dict(pair=pair,side=side,size=size,price=price,post_only=True),frame['rules'][pair],book)
    source,target=(quote,base) if side=='BUY' else (base,quote)
    commission=size*price*maker
    flow=native_fill_changes(dict(product_id=pair,side=side,size=size,price=price,commission=commission,fee_currency=quote,size_in_quote=False))
    after={a:exact(wallet[a])+flow['changes'][a] for a in WATCH_ASSETS}
    if any(v<0 for v in after.values()):raise BetaBlocked('NO_FUNDED_UNRESERVED_OPPORTUNITY_SOURCE')
    liquidity_screen(book,side,size)
    try:
        before_exit=exit_mark_cost(pair,side,exact(wallet[target]),frame,marks,taker)
        after_exit=exit_mark_cost(pair,side,after[target],frame,marks,taker)
        exit_cost=max(D(0),after_exit-before_exit)
    except (ValueError,TypeError,KeyError,ArithmeticError):raise BetaBlocked('SIZED_FUTURE_EXIT_COST_UNKNOWN') from None
    held=utility(wallet,marks,model,config);projected=utility(after,marks,model,config)
    delta={a:projected['exposures'][a]-held['exposures'][a] for a in WATCH_ASSETS}
    sample_uncertainty=config.uncertainty_z*(variance(delta,model)/model['count']).sqrt()*config.horizon_steps
    notional=size*price*marks[quote]
    execution_uncertainty=(book['ask']-book['bid'])/book['ask']*notional/2
    model_uncertainty=notional*config.model_buffer_bps/D(10000)
    expected=projected['utility_usd']-held['utility_usd']
    advantage=expected-exit_cost-sample_uncertainty-execution_uncertainty-model_uncertainty
    return dict(pair=pair,side=side,source=source,target=target,size=size,price=price,post_only=True,
        state='QUALIFIED' if advantage>0 else 'HOLD',reason='POSITIVE_MODEL_LOWER_BOUND' if advantage>0 else 'NO_COST_RISK_JUSTIFIED_ADVANTAGE',
        projected_advantage_usd=advantage,expected_utility_change_usd=expected,estimated_future_exit_cost_usd=exit_cost,
        forecast_uncertainty_usd=sample_uncertainty+model_uncertainty,execution_uncertainty_usd=execution_uncertainty,
        projected_entry_fee_native=commission,fee_currency=quote,maker_rate=maker,
        projected_entry_fee_usd=commission*marks[quote],projected_wallet=after,
        projected_marked_change_usd=portfolio_value(after,marks)-portfolio_value(wallet,marks),
        projected_portfolio_vs_original_hold_usd=projected['utility_usd']-utility(original,marks,model,config)['utility_usd'],
        reserve=size*price*(1+maker) if side=='BUY' else size,
        model='UNVALIDATED_TRAILING_RETURN_LOWER_BOUND',fill_feasibility='UNKNOWN_UNCALIBRATED_MAKER_QUEUE',
        fee_units='DECLARED_QUOTE_MODEL_NOT_API_COMMISSION_PRECISION')

@native_math
def evaluate(frame,wallet,available,original,observations,config):
    rows=[];config=config.checked()
    for direction in DIRECTIONS:
        row=dict(**direction,state='HOLD',reason='UNVERIFIED_OPPORTUNITY_INPUTS')
        try:
            ticket=plan(direction['pair'],direction['side'],frame,'BID',wallet=available,percent=config.size_percent[direction['pair']])
            if config.improvement_ticks:
                from coincat_portfolio_policy import maker_price
                ticket['price']=maker_price(frame,direction['pair'],direction['side'],config.improvement_ticks)
            row.update(assess(frame,wallet,original,observations,config,ticket))
            if row['reserve']>available[row['source']]:raise BetaBlocked('NO_FUNDED_UNRESERVED_OPPORTUNITY_SOURCE')
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            row.update(state='HOLD',reason=str(exc) if isinstance(exc,BetaBlocked) else 'UNVERIFIED_OPPORTUNITY_INPUTS')
        rows.append(row)
    qualified=[r for r in rows if r['state']=='QUALIFIED']
    return rows,max(qualified,key=lambda r:(r['projected_advantage_usd'],r['id'])) if qualified else None

@native_math
def performance(frame,wallet,original,initial_usd):
    marks,_=usd_marks(frame);value=portfolio_value(wallet,marks);hold=portfolio_value(original,marks)
    return dict(at=frame['at'],portfolio_usd=value,hold_usd=hold,advantage_usd=value-hold,
        change_usd=value-initial_usd,initial_usd=initial_usd,valuation='MIDPOINT_AFTER_FILLED_LEG_FEES_BEFORE_UNEXECUTED_EXITS',
        actual_profit='NOT_ESTABLISHED',fill_model='CONDITIONAL_NOT_CALIBRATED')
