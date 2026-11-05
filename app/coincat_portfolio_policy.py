"""Cost/risk-aware shadow portfolio decisions. No client or order authority.

USD marks value inventory; valuation routes never mandate asset conversions.
Trailing returns/covariance are an unvalidated prospective hypothesis, not an
established predictive edge or authority to trade an account.
"""
from copy import deepcopy
from dataclasses import dataclass,asdict
from decimal import Decimal as D,ROUND_FLOOR,ROUND_CEILING

from coincat_beta_store import BetaBlocked
from coincat_execution_limits import native_math
from coincat_multicurrency import research_order
from coincat_spot_market import limit_rules
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

POLICY='RISK_ADJUSTED_USD_PORTFOLIO_SHADOW_V1'
DIRECTIONS=tuple(dict(id=pair+'_'+side,pair=pair,side=side,
    source=pair.split('-')[1] if side=='BUY' else pair.split('-')[0],
    target=pair.split('-')[0] if side=='BUY' else pair.split('-')[1])
    for pair in WATCH_PAIRS for side in ('BUY','SELL'))

@dataclass(frozen=True)
class PortfolioConfig:
    max_turnover_usd:D=D(10)
    max_order_usd:D=D(5)
    max_orders:int=4
    duration_s:int=2592000
    source_fraction:D=D('.5')
    fee_ceiling:D=D('.02')
    improvement_ticks:int=0
    risk_aversion:D=D(1)
    uncertainty_z:D=D('1.96')
    min_observations:int=20
    horizon_steps:int=20
    review_s:int=30
    reconsider_s:int=120

    def checked(self):
        data=asdict(self)
        for k in ('max_turnover_usd','max_order_usd','source_fraction','fee_ceiling','risk_aversion','uncertainty_z'):data[k]=exact(data[k])
        if not 0<data['max_order_usd']<=data['max_turnover_usd']<=1000:raise BetaBlocked('INVALID_SHADOW_USD_LIMITS')
        if not 0<data['source_fraction']<=D('.5') or not 0<data['fee_ceiling']<D('.05'):raise BetaBlocked('INVALID_SHADOW_SOURCE_OR_FEE_LIMIT')
        if not 0<=data['risk_aversion']<=100 or not 0<data['uncertainty_z']<=10:raise BetaBlocked('INVALID_SHADOW_RISK_SETTINGS')
        for k,lo,hi in (('max_orders',1,16),('duration_s',120,2592000),('improvement_ticks',0,100),('min_observations',20,200),('horizon_steps',1,120)):
            if type(data[k]) is not int or not lo<=data[k]<=hi:raise BetaBlocked('INVALID_SHADOW_INTEGER_SETTING')
        if data['review_s']!=30 or data['reconsider_s']!=120:raise BetaBlocked('SHADOW_REVIEW_TIMING_REQUIRES_30_AND_120')
        return PortfolioConfig(**data)


def valid_book(frame,pair,*,admission=True):
    book=frame['books'].get(pair)
    if not isinstance(book,dict) or book.get('pair')!=pair or not 0<=frame['at']-book['at']<=30:raise BetaBlocked('SHADOW_BOOK_MISSING_OR_STALE')
    bid,ask=exact(book['bid']),exact(book['ask'])
    if not 0<bid<ask or admission and (ask-bid)/ask>D('.0025'):raise BetaBlocked('SHADOW_BOOK_CROSSED_OR_WIDE')
    return book


@native_math
def usd_marks(frame):
    """Consistent native-market USD marks, for current and HOLD quantities."""
    ref=valid_book(frame,'ETH-USD',admission=False);cross=valid_book(frame,'ETH-BTC',admission=False)
    stamps=[ref['at'],cross['at']];eth=(ref['bid']+ref['ask'])/2
    marks={'ETH':eth,'BTC':eth/((cross['bid']+cross['ask'])/2)}
    for asset in ('ADA','LINK','SOL'):
        b=valid_book(frame,asset+'-ETH',admission=False);stamps.append(b['at']);marks[asset]=(b['bid']+b['ask'])/2*eth
    if max(stamps)-min(stamps)>12:raise BetaBlocked('SHADOW_VALUATION_DECISION_SPAN_EXCEEDS_12S')
    return marks,tuple(stamps)


@native_math
def portfolio_value(wallet,marks):
    if not set(wallet)<=set(WATCH_ASSETS) or any(exact(q)<0 for q in wallet.values()):raise BetaBlocked('INVALID_PORTFOLIO_INVENTORY')
    return sum((exact(wallet.get(a,D(0)))*exact(marks[a]) for a in WATCH_ASSETS),D(0))


@native_math
def risk_estimate(observations,config):
    """Sample covariance is PSD by construction; gaps invalidate the window."""
    n=config.min_observations
    if len(observations)<n+1:raise BetaBlocked('WARMING_RISK_OBSERVATIONS_HOLD')
    rows=observations[-min(len(observations),201):]
    for i in range(len(rows)-1,0,-1):
        if not 0<rows[i]['at']-rows[i-1]['at']<=90:
            rows=rows[i:];break
    if len(rows)<n+1:raise BetaBlocked('WARMING_AFTER_RISK_OBSERVATION_GAP_HOLD')
    returns=[]
    for old,new in zip(rows,rows[1:]):
        if not 0<new['at']-old['at']<=90:raise BetaBlocked('RISK_OBSERVATION_GAP_HOLD')
        r={a:exact(new['marks'][a])/exact(old['marks'][a])-1 for a in WATCH_ASSETS}
        if any(abs(x)>D('.2') for x in r.values()):raise BetaBlocked('RISK_RETURN_OUTLIER_REVIEW_REQUIRED')
        returns.append(r)
    count=len(returns);mean={a:sum((r[a] for r in returns),D(0))/count for a in WATCH_ASSETS}
    covariance={a:{b:sum(((r[a]-mean[a])*(r[b]-mean[b]) for r in returns),D(0))/(count-1)
        for b in WATCH_ASSETS} for a in WATCH_ASSETS}
    return dict(mean=mean,covariance=covariance,count=count,source='UNVALIDATED_TRAILING_RETURN_HYPOTHESIS',validated_edge=False)


@native_math
def variance(exposures,model):
    value=sum((exposures[a]*exposures[b]*model['covariance'][a][b] for a in WATCH_ASSETS for b in WATCH_ASSETS),D(0))
    if value<D('-1e-30'):raise BetaBlocked('RISK_COVARIANCE_NOT_POSITIVE_SEMIDEFINITE')
    return max(D(0),value)


@native_math
def utility(wallet,marks,model,config):
    x={a:exact(wallet.get(a,D(0)))*marks[a] for a in WATCH_ASSETS}
    forecast=sum((x[a]*(1+model['mean'][a]*config.horizon_steps) for a in WATCH_ASSETS),D(0))
    sigma=(variance(x,model)*config.horizon_steps).sqrt()
    return dict(expected_usd=forecast,risk_usd=sigma,utility_usd=forecast-config.risk_aversion*sigma,exposures=x)


@native_math
def maker_price(frame,pair,side,improvement_ticks):
    rules=frame['rules'][pair];_,tick=limit_rules(pair,rules);book=valid_book(frame,pair)
    if side=='BUY':price=min(book['bid']+improvement_ticks*tick,book['ask']-tick)
    elif side=='SELL':price=max(book['ask']-improvement_ticks*tick,book['bid']+tick)
    else:raise BetaBlocked('SHADOW_INVALID_SIDE')
    price=(price/tick).to_integral_value(rounding=ROUND_FLOOR if side=='BUY' else ROUND_CEILING)*tick
    if price<=0 or (price>=book['ask'] if side=='BUY' else price<=book['bid']):raise BetaBlocked('NO_NONCROSSING_MAKER_PRICE')
    return price

def liquidity_screen(book,side,size):
    """Sized opposite depth is a stress screen, never maker queue/fill proof."""
    levels=book.get('asks' if side=='BUY' else 'bids')
    if not isinstance(levels,(list,tuple)) or not levels:raise BetaBlocked('SIZED_NATIVE_DEPTH_UNAVAILABLE')
    capacity=sum((exact(q) for p,q in levels),D(0))
    if capacity<size:raise BetaBlocked('SIZED_NATIVE_DEPTH_INSUFFICIENT')
    return capacity


@native_math
def select_candidates(frame,wallet,available,original,observations,config,*,remaining_capital=None):
    config=config.checked();rows=[]
    wallet={a:exact(wallet.get(a,D(0))) for a in WATCH_ASSETS}
    try:
        marks,stamps=usd_marks(frame);model=risk_estimate(observations,config);held=utility(wallet,marks,model,config)
        tier=frame['tier'];fee=exact(tier['maker'])
        if not 0<=frame['at']-tier['at']<=3600 or not 0<=fee<=config.fee_ceiling:raise BetaBlocked('FRESH_AUTHENTICATED_MAKER_FEE_REQUIRED')
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
        reason=str(exc) if isinstance(exc,BetaBlocked) else 'SHADOW_INPUTS_UNVERIFIED'
        return [dict(**v,state='HOLD',reason=reason) for v in DIRECTIONS],None
    remaining=config.max_turnover_usd if remaining_capital is None else exact(remaining_capital)
    for view in DIRECTIONS:
        row=dict(**view,state='HOLD',reason='NO_COST_RISK_JUSTIFIED_EDGE')
        try:
            pair,side,source,target=(view[k] for k in ('pair','side','source','target'))
            price=maker_price(frame,pair,side,config.improvement_ticks);book=valid_book(frame,pair)
            base,quote=pair.split('-')
            if abs((book['bid']+book['ask'])/2*marks[quote]/marks[base]-1)>D('.01'):
                raise BetaBlocked('NATIVE_BOOK_USD_MARK_REFERENCE_CONFLICT')
            if max(stamps+(book['at'],))-min(stamps+(book['at'],))>12:raise BetaBlocked('SHADOW_TRADE_DECISION_SPAN_EXCEEDS_12S')
            free=exact(available.get(source,D(0)))
            if free<=0:raise BetaBlocked('NO_FUNDED_UNRESERVED_SOURCE')
            cap=min(config.max_order_usd,remaining)
            if cap<=0:raise BetaBlocked('SHADOW_CAPITAL_LIMIT_REACHED')
            # Explicit quote-fee projection. The source buffer is a reserve,
            # never a second fee or an invented account commission currency.
            budget=min(free*config.source_fraction,cap/marks[source])/(1+config.fee_ceiling)
            receipt=research_order(pair=pair,side=side,available=budget,cap=cap,usd_rate=marks[source],
                book=(price,price,frame['at']),product_rules=frame['rules'],fee=fee,slip=D(0))
            size=receipt['gross_base_quantity'];reserve=size*(price if side=='BUY' else 1)*(1+config.fee_ceiling)
            capacity=liquidity_screen(book,side,size)
            if reserve>free or reserve*marks[source]>cap:raise BetaBlocked('SHADOW_SOURCE_BUFFER_EXCEEDS_CAP')
            after=deepcopy(wallet);after[source]-=receipt['input_quantity'];after[target]+=receipt['output_quantity']
            projected=utility(after,marks,model,config);delta={a:projected['exposures'][a]-held['exposures'][a] for a in WATCH_ASSETS}
            forecast_uncertainty=config.uncertainty_z*(variance(delta,model)/model['count']).sqrt()*config.horizon_steps
            execution_uncertainty=(book['ask']-book['bid'])/book['ask']*reserve*marks[source]/2
            edge=projected['utility_usd']-held['utility_usd']-forecast_uncertainty-execution_uncertainty
            row.update(price=price,size=size,reserve=reserve,reserve_usd=reserve*marks[source],maker_fee=fee,
                projected_fee_usd=receipt['fee_amount_estimate']*marks[quote],
                receipt=receipt,projected_wallet=after,projected_usd=portfolio_value(after,marks),
                hold_original_usd=portfolio_value(original,marks),expected_risk_adjusted_edge_usd=edge,
                trading_cost_mark_usd=portfolio_value(wallet,marks)-portfolio_value(after,marks),
                uncertainty_usd=forecast_uncertainty+execution_uncertainty,model=model['source'],
                observed_opposite_depth=capacity,queue_ahead='UNKNOWN_NOT_CALIBRATED',
                fee_units='QUOTE_FEE_MODEL_NOT_API_DENOMINATION',classification='CONDITIONAL_SHADOW_FULL_FILL_NOT_PROFIT')
            if edge>0:row.update(state='SHADOW_CANDIDATE',reason='COST_UNCERTAINTY_AND_RISK_JUSTIFIED_HYPOTHESIS')
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            row['reason']=str(exc) if isinstance(exc,BetaBlocked) else 'NATIVE_RULE_OR_SIZE_UNVERIFIED'
        rows.append(row)
    qualified=[r for r in rows if r['state']=='SHADOW_CANDIDATE']
    selected=max(qualified,key=lambda r:(r['expected_risk_adjusted_edge_usd'],r['id'])) if qualified else None
    return rows,selected


@native_math
def performance(frame,wallet,original,observations,config,*,accounting_complete=True,initial_usd=None,fills=None):
    if not accounting_complete:return dict(state='UNKNOWN_ACCOUNTING',real_profit='NOT_ASSESSED',outperformance_usd=None)
    try:
        marks,_=usd_marks(frame);value=portfolio_value(wallet,marks);hold=portfolio_value(original,marks)
        result=dict(state='SHADOW_MARK_TO_MARKET',portfolio_usd=value,hold_original_usd=hold,
            outperformance_usd=value-hold,open_inventory={a:q for a,q in wallet.items() if q},
            starting_usd=initial_usd,change_usd=None if initial_usd is None else value-initial_usd,
            change_percent=None if not initial_usd else (value/initial_usd-1)*100,
            outperformance_percent=None if not hold else (value/hold-1)*100,
            exposure_usd={a:wallet[a]*marks[a] for a in WATCH_ASSETS},
            unrealized_inventory_mark_usd=value,
            unrealized_pnl_usd=value-initial_usd if initial_usd is not None and not fills else None,
            unrealized_pnl_status='UNTRADED_SHADOW_GAIN_SINCE_TRIAL_INCEPTION' if initial_usd is not None and not fills else 'LOT_BASIS_NOT_ESTABLISHED_FOR_ALL_OPEN_SHADOW_INVENTORY',
            liquidation_usd=None,liquidation_status='UNKNOWN_NATIVE_USD_EXIT_RULES_DEPTH_AND_FEE_UNITS',
            unvalued_inventory=[],hypothetical_fees_native={},actual_imported_fees='SEPARATE_PRIVATE_HISTORY',
            real_profit='NOT_ASSESSED',baseline='ORIGINAL_NATIVE_QUANTITIES_SAME_CURRENT_MARKS',risk_adjusted_usd=None)
        for fill in (fills or {}).values():
            if fill['settled']:
                flow=fill['flow'];asset=flow['fee_currency']
                result['hypothetical_fees_native'][asset]=result['hypothetical_fees_native'].get(asset,D(0))+flow['commission']
        try:
            model=risk_estimate(observations,config);result['risk_adjusted_usd']=utility(wallet,marks,model,config)['utility_usd']
            result['risk_adjusted_hold_usd']=utility(original,marks,model,config)['utility_usd']
        except BetaBlocked:pass
        return result
    except (ValueError,TypeError,KeyError,ArithmeticError):
        return dict(state='UNKNOWN_VALUATION',real_profit='NOT_ASSESSED',outperformance_usd=None)

@native_math
def assess_ticket(frame,wallet,original,observations,config,ticket):
    """Recompute the exact remaining native size; never reuse a larger forecast."""
    marks,_=usd_marks(frame);model=risk_estimate(observations,config);held=utility(wallet,marks,model,config)
    row=deepcopy(ticket);pair=row['pair'];side=row['side'];source=row['source'];target=row['target']
    size=row['size'];price=row['price'];fee=exact(frame['tier']['maker']);book=valid_book(frame,pair)
    amount=size*price*(1+fee) if side=='BUY' else size
    receipt=research_order(pair=pair,side=side,available=amount,cap=amount*marks[source],usd_rate=marks[source],
        book=(price,price,frame['at']),product_rules=frame['rules'],fee=fee,slip=D(0))
    if receipt['gross_base_quantity']!=size:raise BetaBlocked('REMAINING_RECEIPT_SIZE_CONFLICT')
    after=deepcopy(wallet);after[source]-=receipt['input_quantity'];after[target]+=receipt['output_quantity']
    proposed=utility(after,marks,model,config);delta={a:proposed['exposures'][a]-held['exposures'][a] for a in WATCH_ASSETS}
    uncertainty=config.uncertainty_z*(variance(delta,model)/model['count']).sqrt()*config.horizon_steps
    reserve=size*(price if side=='BUY' else 1)*(1+config.fee_ceiling)
    capacity=liquidity_screen(book,side,size)
    uncertainty+=(book['ask']-book['bid'])/book['ask']*reserve*marks[source]/2
    edge=proposed['utility_usd']-held['utility_usd']-uncertainty
    row.update(size=size,reserve=reserve,reserve_usd=reserve*marks[source],receipt=receipt,projected_wallet=after,
        projected_fee_usd=receipt['fee_amount_estimate']*marks[pair.split('-')[1]],
        projected_usd=portfolio_value(after,marks),hold_original_usd=portfolio_value(original,marks),
        expected_risk_adjusted_edge_usd=edge,uncertainty_usd=uncertainty,
        trading_cost_mark_usd=portfolio_value(wallet,marks)-portfolio_value(after,marks),
        observed_opposite_depth=capacity,queue_ahead='UNKNOWN_NOT_CALIBRATED',
        state='SHADOW_CANDIDATE' if edge>0 else 'HOLD')
    return row
