"""v1.05 direct 24-hour, one-leg portfolio decisions. Pure shadow hypotheses."""
from dataclasses import dataclass,asdict,field
from decimal import Decimal as D
from copy import deepcopy

from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_assumed_math import rounded,fee_rate
from coincat_order_services import native_fill_changes,ticket_values
from coincat_spot_market import limit_rules
from coincat_portfolio_policy import DIRECTIONS,portfolio_value,variance,valid_book,liquidity_screen,maker_price
from coincat_intelligent_market import marks as usd_marks
from coincat_forecast_24h import MODEL,HORIZON,ForecastConfig
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS

POLICY='INTELLIGENT_ONE_LEG_24H_V1'

@dataclass(frozen=True)
class IntelligentConfig:
    funding_mode:str='ACCOUNT_AVAILABLE'
    model:dict=field(default_factory=lambda:asdict(ForecastConfig()))
    max_source_fraction:D=D('.5')
    max_asset_weight:D=D('.6')
    risk_aversion:D=D(1)
    uncertainty_z:D=D('2.58')
    concentration_penalty:D=D('.02')
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
    def checked(self):
        values=asdict(self);ForecastConfig(**values['model']).checked()
        for key in ('max_source_fraction','max_asset_weight','risk_aversion','uncertainty_z','concentration_penalty','queue_multiple','participation','partial_fraction'):
            values[key]=exact(values[key])
        if self.funding_mode not in ('ACCOUNT_AVAILABLE','FICTIONAL_100_EACH'):raise BetaBlocked('INTELLIGENT_FUNDING_MODE_INVALID')
        if (not 0<values['max_source_fraction']<=D('.5') or not D('.2')<=values['max_asset_weight']<=1 or
                not 0<=values['risk_aversion']<=10 or not 1<=values['uncertainty_z']<=5 or
                not 0<=values['concentration_penalty']<=D('.1')):raise BetaBlocked('INTELLIGENT_RISK_CONFIG_INVALID')
        for key,lo,hi in (('improvement_ticks',0,100),('order_lifetime_s',120,3600),('campaign_lifetime_s',120,14400),('retry_budget',0,10),('minimum_rest_s',30,300)):
            if type(values[key]) is not int or not lo<=values[key]<=hi:raise BetaBlocked('INTELLIGENT_LIFECYCLE_CONFIG_INVALID')
        if (values['review_s']!=30 or values['reconsider_s']!=120 or values['campaign_lifetime_s']<values['order_lifetime_s'] or
                not 1<=values['queue_multiple']<=20 or not 0<values['participation']<=D('.25') or
                not 0<values['partial_fraction']<=D('.5') or values['provider'] not in ('TRADE_THROUGH_QUEUE_V1','NO_FILL_OBSERVATION_V1')):
            raise BetaBlocked('INTELLIGENT_LIFECYCLE_CONFIG_INVALID')
        return IntelligentConfig(**values)

@native_math
def seed(frame,now,config):
    marks,stamps=usd_marks(frame)
    if any(not 0<=now-t<=30 for t in stamps):raise BetaBlocked('FRESH_SEED_REFERENCES_REQUIRED')
    if config.funding_mode=='FICTIONAL_100_EACH':wallet={a:(D(100)/marks[a]).quantize(D('1e-18')) for a in WATCH_ASSETS}
    else:
        account=frame.get('account')
        if (not isinstance(account,dict) or account.get('portfolio')!=frame.get('portfolio') or
                not 0<=now-account.get('at',0)<=30):raise BetaBlocked('FRESH_AVAILABLE_ACCOUNT_SNAPSHOT_REQUIRED')
        wallet={a:exact(account.get('available',{}).get(a,D(0))) for a in WATCH_ASSETS}
    if any(q<0 for q in wallet.values()) or portfolio_value(wallet,marks)<=0:raise BetaBlocked('NO_SHADOW_SOURCE_FUNDS')
    return dict(original=deepcopy(wallet),wallet=wallet,seed_marks=marks)

def checked_forecast(frame):
    f=frame.get('forecast') or {}
    if f.get('state')!='READY':raise BetaBlocked(f.get('reason','FORECAST_HISTORY_INSUFFICIENT'))
    if (f.get('model')!=MODEL or f.get('horizon_s')!=HORIZON or not 0<=frame['at']-f['decision_at']<=30 or
            f['forecast_end_at']-f['decision_at']!=HORIZON or not 0<=frame['at']-f['feature_at']<=3720):
        raise BetaBlocked('FORECAST_HORIZON_OR_FRESHNESS_INVALID')
    if set(f.get('mean',{}))!=set(WATCH_ASSETS) or any(not D('-.8')<=exact(x)<=D('.8') for x in f['mean'].values()):
        raise BetaBlocked('FORECAST_ESTIMATE_UNVERIFIED')
    return f

def concentration(exposures):
    total=sum(exposures.values(),D(0))
    if total<=0:raise BetaBlocked('NO_SHADOW_SOURCE_FUNDS')
    weights={a:q/total for a,q in exposures.items()}
    return max(weights.values()),sum((x*x for x in weights.values()),D(0))

@native_math
def assess(frame,wallet,original,observations,config,ticket,*,resting=False):
    config=config.checked();f=checked_forecast(frame);marks,stamps=usd_marks(frame);maker=fee_rate(frame,'MAKER')
    for asset in WATCH_ASSETS:
        vol=(f['return_covariance'][asset][asset]+f['error_covariance'][asset][asset]).sqrt()
        if abs(marks[asset]/exact(f['feature_marks'][asset])-1)>max(D('.01'),3*vol/D(24).sqrt()):
            raise BetaBlocked('FORECAST_CURRENT_PRICE_SHOCK')
    pair,side=ticket['pair'],ticket['side'];base,quote=pair.split('-');source,target=(quote,base) if side=='BUY' else (base,quote)
    book=valid_book(frame,pair)
    if max(stamps+(book['at'],))-min(stamps+(book['at'],))>12:raise BetaBlocked('INTELLIGENT_REFERENCES_ASYNCHRONOUS')
    if abs((book['bid']+book['ask'])/2*marks[quote]/marks[base]-1)>D('.01'):raise BetaBlocked('INTELLIGENT_NATIVE_REFERENCE_CONFLICT')
    size,price=exact(ticket['size']),exact(ticket['price'])
    if size<=0 or price<=0:raise BetaBlocked('INTELLIGENT_NATIVE_SIZE_INVALID')
    if not resting:ticket_values(dict(pair=pair,side=side,size=size,price=price,post_only=True),frame['rules'][pair],book)
    liquidity_screen(book,side,size)
    commission=size*price*maker
    flow=native_fill_changes(dict(product_id=pair,side=side,size=size,price=price,commission=commission,fee_currency=quote,size_in_quote=False))
    after={a:exact(wallet[a])+flow['changes'][a] for a in WATCH_ASSETS}
    reserve=-flow['changes'][source]
    if any(q<0 for q in after.values()) or reserve>exact(wallet[source])*config.max_source_fraction:raise BetaBlocked('INTELLIGENT_SOURCE_FUNDS_OR_FRACTION')
    old_exposure={a:exact(wallet[a])*marks[a] for a in WATCH_ASSETS};new_exposure={a:after[a]*marks[a] for a in WATCH_ASSETS}
    before_weight,before_hhi=concentration(old_exposure);after_weight,after_hhi=concentration(new_exposure)
    if after_weight>config.max_asset_weight and after_weight>=before_weight:raise BetaBlocked('INTELLIGENT_CONCENTRATION_LIMIT')
    future={a:marks[a]*(1+f['mean'][a]) for a in WATCH_ASSETS}
    before_expected=portfolio_value(wallet,future);after_expected=portfolio_value(after,future);expected=after_expected-before_expected
    risk_delta=config.risk_aversion*(variance(new_exposure,dict(covariance=f['return_covariance'])).sqrt()-variance(old_exposure,dict(covariance=f['return_covariance'])).sqrt())
    concentration_delta=sum(old_exposure.values(),D(0))*config.concentration_penalty*(after_hhi-before_hhi)
    delta={a:new_exposure[a]-old_exposure[a] for a in WATCH_ASSETS}
    uncertainty=config.uncertainty_z*variance(delta,dict(covariance=f['error_covariance'])).sqrt()
    # Entry price/spread and the entry fee are already in after. This separate
    # allowance models adverse selection while resting, never a paid surcharge.
    relative={a:D(1) if a==target else D(-1) if a==source else D(0) for a in WATCH_ASSETS}
    relative_vol=variance(relative,dict(covariance=f['return_covariance'])).sqrt()
    execution=size*price*marks[quote]*relative_vol*(D(config.reconsider_s)/HORIZON).sqrt()
    risk_adjusted=expected-risk_delta-concentration_delta;edge=risk_adjusted-uncertainty-execution
    reason='POSITIVE_24H_PORTFOLIO_ADVANTAGE'
    if edge<=0:
        if expected<=0:reason='ENTRY_FEE_REMOVES_ADVANTAGE' if expected+commission*future[quote]>0 else 'INSUFFICIENT_24H_EXPECTED_ADVANTAGE'
        elif risk_adjusted<=0:reason='PORTFOLIO_RISK_REMOVES_ADVANTAGE'
        else:reason='FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE'
    return dict(pair=pair,side=side,source=source,target=target,size=size,price=price,post_only=True,
        state='QUALIFIED' if edge>0 else 'HOLD',reason=reason,projected_advantage_usd=edge,
        expected_utility_change_usd=risk_adjusted,expected_24h_incremental_usd=expected,forecast_uncertainty_usd=uncertainty,
        execution_uncertainty_usd=execution,risk_adjustment_usd=risk_delta+concentration_delta,
        projected_entry_fee_native=commission,fee_currency=quote,projected_entry_fee_usd=commission*marks[quote],maker_rate=maker,
        reserve=reserve,source_quantity=reserve,destination_quantity=flow['changes'][target],projected_wallet=after,
        available_source=exact(wallet[source]),after_source=after[source],horizon_s=HORIZON,forecast_end_at=f['forecast_end_at'],
        projected_marked_change_usd=portfolio_value(after,marks)-portfolio_value(wallet,marks),
        projected_portfolio_vs_original_hold_usd=after_expected-portfolio_value(original,future),
        forecast_validation=f['forecast_validation'],fee_units='DECLARED_QUOTE_MODEL_NOT_EXCHANGE_COMMISSION_PRECISION',
        forecast_provenance={k:deepcopy(f['provenance'][k]) for k in ('model','parameters','history_digest','first_at','last_at','maximum_training_end','validation','holdout')},
        fill_feasibility='CONDITIONAL_NOT_CALIBRATED',model=MODEL,
        explanation='Exchange '+format(reserve,'.10g')+' '+source+' for approximately '+format(flow['changes'][target],'.10g')+' '+target+
            '. '+side+' '+pair+'; the projected entry commission is included once.')

@native_math
def evaluate(frame,wallet,available,original,observations,config):
    config=config.checked();rows=[]
    for direction in DIRECTIONS:
        row=dict(**direction,state='HOLD',reason='INTELLIGENT_INPUTS_UNVERIFIED')
        try:
            f=checked_forecast(frame);pair,side,source,target=(direction[k] for k in ('pair','side','source','target'))
            price=maker_price(frame,pair,side,config.improvement_ticks);rules,tick=limit_rules(pair,frame['rules'][pair]);inc,minbase,minquote,maxbase,maxquote=rules
            maker=fee_rate(frame,'MAKER');funds=exact(available[source]);relative={a:D(1) if a==target else D(-1) if a==source else D(0) for a in WATCH_ASSETS}
            vol=variance(relative,dict(covariance=f['return_covariance'])).sqrt()+variance(relative,dict(covariance=f['error_covariance'])).sqrt()
            strength=max(D(0),f['mean'][target]-f['mean'][source])
            # Weak signals get a smaller search region. Diversification may
            # justify a minimum-size candidate even with neutral relative mean.
            fraction=min(config.max_source_fraction,max(D('.01'),D('.1')*strength/max(D('.000001'),vol+maker)))
            maximum=funds*fraction/(price*(1+maker)) if side=='BUY' else funds*fraction
            if maxbase is not None:maximum=min(maximum,maxbase)
            if maxquote is not None:maximum=min(maximum,maxquote/price)
            maximum=rounded(maximum,inc);minimum=rounded(max(minbase,minquote/price),inc,up=True)
            if minimum>maximum or minimum<=0:raise BetaBlocked('INTELLIGENT_MINIMUM_EXCEEDS_JUSTIFIED_FUNDS')
            sizes={minimum,maximum}
            for part in (D('.01'),D('.02'),D('.05'),D('.1'),D('.2'),D('.35')):
                budget=funds*min(fraction,part);q=rounded(budget/(price*(1+maker)) if side=='BUY' else budget,inc)
                if minimum<=q<=maximum:sizes.add(q)
            candidates=[];blocked=[]
            for size in sorted(sizes):
                try:
                    candidate=assess(frame,wallet,original,observations,config,dict(pair=pair,side=side,size=size,price=price))
                    if candidate['reserve']>funds:raise BetaBlocked('INTELLIGENT_SOURCE_FUNDS_OR_FRACTION')
                    candidates.append(candidate)
                except (ValueError,TypeError,KeyError,ArithmeticError) as exc:blocked.append(str(exc) if isinstance(exc,BetaBlocked) else 'INTELLIGENT_INPUTS_UNVERIFIED')
            if not candidates:raise BetaBlocked(blocked[0] if blocked else 'INTELLIGENT_INPUTS_UNVERIFIED')
            best=max(candidates,key=lambda r:(r['projected_advantage_usd'],-r['size']));row.update(best);row['evaluated_sizes']=len(sizes)
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:row.update(state='HOLD',reason=str(exc) if isinstance(exc,BetaBlocked) else 'INTELLIGENT_INPUTS_UNVERIFIED')
        rows.append(row)
    qualified=[r for r in rows if r['state']=='QUALIFIED']
    return rows,max(qualified,key=lambda r:(r['projected_advantage_usd'],r['id'])) if qualified else None

@native_math
def performance(frame,wallet,original,initial_usd):
    marks,_=usd_marks(frame);value=portfolio_value(wallet,marks);hold=portfolio_value(original,marks)
    return dict(at=frame['at'],portfolio_usd=value,hold_usd=hold,advantage_usd=value-hold,
        advantage_percent=None if hold==0 else (value/hold-1)*100,change_usd=value-initial_usd,initial_usd=initial_usd,
        valuation='MIDPOINT_AFTER_PAID_MODELED_FEES_BEFORE_ANY_UNEXECUTED_CONVERSION',actual_profit='NOT_ESTABLISHED',
        forecast_advantage=None,fill_model='CONDITIONAL_NOT_CALIBRATED')
