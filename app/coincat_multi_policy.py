"""Independent one-leg horizons, comparable after-cost risk scores and no live grant."""
from copy import deepcopy
from dataclasses import asdict,dataclass,field,fields,replace
from decimal import Decimal as D
from statistics import NormalDist
from coincat_assumed_math import rounded,fee_rate
from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_horizon_forecast import HORIZONS,SHORT,MODEL
from coincat_intelligent_market import marks as usd_marks
from coincat_intelligent_policy import IntelligentConfig,project_forecast,seed,performance,checked_forecast
from coincat_order_services import ticket_values
from coincat_portfolio_policy import DIRECTIONS,maker_price,variance
from coincat_spot_market import limit_rules
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS

POLICY='MULTI_HORIZON_ONE_LEG_V1'

@dataclass(frozen=True)
class MultiConfig(IntelligentConfig):
    policy_version:str=POLICY
    horizons:list=field(default_factory=lambda:list(HORIZONS))
    selection_tests:int=672 # 14 directions x 6 horizons x at most 8 native sizes.
    family_alpha:D=D('.01')
    def checked(self):
        if self.policy_version!=POLICY or self.horizons!=list(HORIZONS) or type(self.selection_tests) is not int or self.selection_tests!=672 or exact(self.family_alpha)!=D('.01'):
            raise BetaBlocked('MULTI_FROZEN_SELECTION_PARAMETERS_REQUIRED')
        base=IntelligentConfig(**{f.name:getattr(self,f.name) for f in fields(IntelligentConfig)}).checked()
        return MultiConfig(**asdict(base),policy_version=POLICY,horizons=list(HORIZONS),selection_tests=672,family_alpha=D('.01'))

def corrected_core(config):
    checked=config.checked();z=D(str(NormalDist().inv_cdf(1-float(checked.family_alpha)/(2*checked.selection_tests))))
    base=IntelligentConfig(**{f.name:getattr(checked,f.name) for f in fields(IntelligentConfig)}).checked()
    return replace(base,uncertainty_z=max(base.uncertainty_z,z)),z

def forecast_for(frame,name):
    f=(frame.get('horizon_forecasts') or {}).get(name,{})
    if f.get('state')!='READY':raise BetaBlocked(f.get('reason','HORIZON_HISTORY_INSUFFICIENT'))
    if name=='H24':checked_forecast(dict(frame,forecast=f));return f
    expected='SYNCHRONIZED_IMMEDIATE_MARK_V1' if name=='IMMEDIATE' else MODEL
    seconds=60 if name in ('IMMEDIATE','M5','M15') else 300
    if (f.get('model')!=expected or f.get('horizon_s')!=HORIZONS[name] or
            f['forecast_end_at']-f['decision_at']!=HORIZONS[name] or not 0<=frame['at']-f['decision_at']<=30 or
            not 0<=frame['at']-f['feature_at']<=2*seconds+30 or set(f['mean'])!=set(WATCH_ASSETS) or
            any(not D('-.8')<=exact(v)<=D('.8') for v in f['mean'].values())):raise BetaBlocked('HORIZON_FORECAST_INVALID_OR_STALE')
    return f

@native_math
def assess_horizon(frame,wallet,original,config,ticket,name,*,resting=False):
    f=forecast_for(frame,name);core,z=corrected_core(config)
    row=project_forecast(frame,wallet,original,core,ticket,f,resting=resting)
    row['expected_incremental_usd']=row.pop('expected_24h_incremental_usd');row.update(selected_horizon=name,selection_z=z,
        selection_tests=config.selection_tests,selection_calibration='EXPLORATORY_MULTIPLICITY_ALLOWANCE_NOT_CALIBRATED')
    if name=='IMMEDIATE':
        marks,_=usd_marks(frame);changes={a:row['projected_wallet'][a]-exact(wallet[a]) for a in WATCH_ASSETS}
        lower=sum((q*frame['reference_books'][a+'-USD']['bid' if q>=0 else 'ask'] for a,q in changes.items()),D(0))
        marked=sum((q*marks[a] for a,q in changes.items()),D(0));allowance=max(D(0),marked-lower)*core.uncertainty_z
        row['projected_advantage_usd']-=allowance;row['forecast_uncertainty_usd']+=allowance
        row.update(conservative_immediate_mark_usd=lower,reference_interval_allowance_usd=allowance)
        if lower<=0:
            cause='ENTRY_FEE_REMOVES_ADVANTAGE' if marked<=0 and marked+row['projected_entry_fee_usd']>0 else 'IMMEDIATE_AFTER_FEE_MARK_NOT_POSITIVE' if marked<=0 else 'FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE'
            row.update(state='HOLD',reason=cause)
        elif row['projected_advantage_usd']<=0:row.update(state='HOLD',reason='FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE')
    row['reason']=row['reason'].replace('24H','HORIZON')
    if row['state']=='QUALIFIED':row['reason']='POSITIVE_SUPPORTED_HORIZON_ADVANTAGE'
    return row

@native_math
def assess(frame,wallet,original,observations,config,ticket,*,resting=False):
    rows=[];failures=[]
    for name in HORIZONS:
        try:rows.append(assess_horizon(frame,wallet,original,config,ticket,name,resting=resting))
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:failures.append(str(exc) if isinstance(exc,BetaBlocked) else 'HORIZON_INPUTS_UNVERIFIED')
    if not rows:raise BetaBlocked(failures[0] if failures else 'NO_SUPPORTED_HORIZON')
    return max(rows,key=lambda r:(r['state']=='QUALIFIED',r['projected_advantage_usd'],r['horizon_s']))

@native_math
def native_sizes(frame,direction,funds,forecast,config):
    pair,side,source,target=(direction[k] for k in ('pair','side','source','target'));price=maker_price(frame,pair,side,config.improvement_ticks)
    rules,tick=limit_rules(pair,frame['rules'][pair]);inc,minbase,minquote,maxbase,maxquote=rules;rate=fee_rate(frame,'MAKER')
    relative={a:D(1) if a==target else D(-1) if a==source else D(0) for a in WATCH_ASSETS}
    vol=variance(relative,dict(covariance=forecast['return_covariance'])).sqrt()+variance(relative,dict(covariance=forecast['error_covariance'])).sqrt()
    strength=max(D(0),forecast['mean'][target]-forecast['mean'][source])
    fraction=min(config.max_source_fraction,max(D('.01'),D('.1')*strength/max(D('.000001'),vol+rate)))
    maximum=funds*fraction/(price*(1+rate)) if side=='BUY' else funds*fraction
    if maxbase is not None:maximum=min(maximum,maxbase)
    if maxquote is not None:maximum=min(maximum,maxquote/price)
    maximum=rounded(maximum,inc);minimum=rounded(max(minbase,minquote/price),inc,up=True)
    if minimum>maximum or minimum<=0:raise BetaBlocked('INTELLIGENT_MINIMUM_EXCEEDS_JUSTIFIED_FUNDS')
    sizes={minimum,maximum}
    for part in (D('.01'),D('.02'),D('.05'),D('.1'),D('.2'),D('.35')):
        budget=funds*min(fraction,part);size=rounded(budget/(price*(1+rate)) if side=='BUY' else budget,inc)
        if minimum<=size<=maximum:sizes.add(size)
    return price,sorted(sizes)

@native_math
def evaluate(frame,wallet,available,original,observations,config):
    config=config.checked();rows=[]
    for direction in DIRECTIONS:
        horizon_rows={}
        for name in HORIZONS:
            row=dict(state='HOLD',reason='HORIZON_INPUTS_UNVERIFIED',selected_horizon=name,horizon_s=HORIZONS[name])
            try:
                f=forecast_for(frame,name);price,sizes=native_sizes(frame,direction,exact(available[direction['source']]),f,config);candidates=[];blocked=[]
                for size in sizes:
                    try:
                        candidate=assess_horizon(frame,wallet,original,config,dict(pair=direction['pair'],side=direction['side'],price=price,size=size),name)
                        if candidate['reserve']>available[direction['source']]:raise BetaBlocked('INTELLIGENT_SOURCE_FUNDS_OR_FRACTION')
                        candidates.append(candidate)
                    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:blocked.append(str(exc) if isinstance(exc,BetaBlocked) else 'HORIZON_INPUTS_UNVERIFIED')
                if not candidates:raise BetaBlocked(blocked[0] if blocked else 'HORIZON_INPUTS_UNVERIFIED')
                row.update(max(candidates,key=lambda r:(r['projected_advantage_usd'],-r['size'])));row['evaluated_sizes']=len(sizes)
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:row['reason']=str(exc) if isinstance(exc,BetaBlocked) else 'HORIZON_INPUTS_UNVERIFIED'
            horizon_rows[name]=row
        selected=max(horizon_rows.values(),key=lambda r:(r['state']=='QUALIFIED',r.get('projected_advantage_usd',D('-Infinity')),r['horizon_s']))
        rows.append({**direction,**selected,'horizons':horizon_rows})
    candidates=[r for r in rows if r['state']=='QUALIFIED']
    return rows,max(candidates,key=lambda r:(r['projected_advantage_usd'],r['id'])) if candidates else None
