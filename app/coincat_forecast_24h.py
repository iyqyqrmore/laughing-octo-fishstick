"""Direct 24-hour analog outcomes, with purged chronological evaluation.

No short-horizon extrapolation, future row selection or parameter optimization.
These empirical research estimates never establish a profitable live strategy.
"""
from dataclasses import dataclass,asdict
from decimal import Decimal as D
from copy import deepcopy
import math

from coincat_beta_store import BetaBlocked,digest
from coincat_execution_limits import native_math
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS

MODEL='DIRECT_24H_ANALOG_V1'
HOUR=3600
HORIZON=24*HOUR
FEATURE_HOURS=72

@dataclass(frozen=True)
class ForecastConfig:
    history_hours:int=2400
    minimum_train:int=40
    neighbors:int=12
    validation_days:int=14
    holdout_days:int=14
    max_feature_age_s:int=HOUR+120
    def checked(self):
        if any(type(v) is not int for v in asdict(self).values()):raise BetaBlocked('FORECAST_CONFIG_INVALID')
        if (self.history_hours!=2400 or self.minimum_train!=40 or self.neighbors!=12 or
                self.validation_days!=14 or self.holdout_days!=14 or self.max_feature_age_s!=HOUR+120):
            raise BetaBlocked('FORECAST_V1_PARAMETERS_FIXED')
        return self

def features(rows,index):
    current=rows[index]['marks'];values=[]
    for asset in WATCH_ASSETS:
        p=exact(current[asset]);day=exact(rows[index-24]['marks'][asset]);three=exact(rows[index-72]['marks'][asset])
        hourly=[exact(rows[j]['marks'][asset])/exact(rows[j-1]['marks'][asset])-1 for j in range(index-23,index+1)]
        if any(abs(x)>D('.2') for x in hourly):raise BetaBlocked('FORECAST_RETURN_OUTLIER')
        values.extend((p/day-1,p/three-1,(sum((x*x for x in hourly),D(0))/24).sqrt()))
    return tuple(values)

def means(rows,key):return {a:sum((r[key][a] for r in rows),D(0))/len(rows) for a in WATCH_ASSETS}

def covariance(vectors):
    n=len(vectors)
    if n<2:raise BetaBlocked('FORECAST_SAMPLE_INSUFFICIENT')
    mu={a:sum((r[a] for r in vectors),D(0))/n for a in WATCH_ASSETS}
    return {a:{b:sum(((r[a]-mu[a])*(r[b]-mu[b]) for r in vectors),D(0))/(n-1)
        for b in WATCH_ASSETS} for a in WATCH_ASSETS}

def predict(train,x,config):
    if len(train)<config.minimum_train:raise BetaBlocked('FORECAST_TRAINING_INSUFFICIENT')
    dim=len(x);center=[sum((r['x'][j] for r in train),D(0))/len(train) for j in range(dim)]
    scale=[max(D('.000001'),(sum(((r['x'][j]-center[j])**2 for r in train),D(0))/(len(train)-1)).sqrt()) for j in range(dim)]
    if any(abs(x[j]-center[j])>8*scale[j] for j in range(dim)):raise BetaBlocked('FORECAST_FEATURE_OUT_OF_DISTRIBUTION')
    ranked=sorted(train,key=lambda r:(sum((((r['x'][j]-x[j])/scale[j])**2 for j in range(dim)),D(0)),-r['at']))
    selected=ranked[:config.neighbors]
    return means(selected,'y'),covariance([r['y'] for r in selected]),[r['at'] for r in selected]

@native_math
def forecast(observations,at,config=None):
    """All training labels and evaluation outcomes end no later than decision at."""
    config=(config or ForecastConfig()).checked()
    if type(at) not in (int,float) or not math.isfinite(at):raise BetaBlocked('FORECAST_TIME_INVALID')
    rows=[deepcopy(r) for r in observations if type(r.get('at')) in (int,float) and r['at']<=at]
    rows=rows[-config.history_hours:]
    if len(rows)<config.history_hours:raise BetaBlocked('FORECAST_HISTORY_INSUFFICIENT')
    for i,row in enumerate(rows):
        if (row['at']%HOUR or set(row['marks'])!=set(WATCH_ASSETS) or
                any(exact(v)<=0 for v in row['marks'].values())):raise BetaBlocked('FORECAST_HISTORY_INVALID')
        if i and row['at']-rows[i-1]['at']!=HOUR:raise BetaBlocked('FORECAST_HISTORY_GAP')
    if not 0<=at-rows[-1]['at']<=config.max_feature_age_s:raise BetaBlocked('FORECAST_HISTORY_STALE')
    # One fixed daily origin per UTC day reduces overlapping labels. Each y is
    # the observed 24-hour return, never an hourly slope multiplied by 24.
    samples=[]
    for i in range(FEATURE_HOURS,len(rows)-24):
        if rows[i]['at']%HORIZON:continue
        y={a:exact(rows[i+24]['marks'][a])/exact(rows[i]['marks'][a])-1 for a in WATCH_ASSETS}
        if any(abs(v)>D('.8') for v in y.values()):raise BetaBlocked('FORECAST_RETURN_OUTLIER')
        samples.append(dict(at=rows[i]['at'],end=rows[i+24]['at'],x=features(rows,i),y=y))
    required=config.minimum_train+config.validation_days+config.holdout_days
    if len(samples)<required:raise BetaBlocked('FORECAST_TRAINING_INSUFFICIENT')
    evaluations=[]
    for sample in samples[-(config.validation_days+config.holdout_days):]:
        # Purge any label that has not ended at this historical origin.
        train=[r for r in samples if r['end']<=sample['at']]
        try:prediction,_,_=predict(train,sample['x'],config)
        except BetaBlocked as exc:
            if str(exc)!='FORECAST_FEATURE_OUT_OF_DISTRIBUTION':raise
            evaluations.append(dict(at=sample['at'],end=sample['end'],state='OUT_OF_DISTRIBUTION',actual=sample['y']));continue
        evaluations.append(dict(at=sample['at'],end=sample['end'],state='EVALUATED',prediction=prediction,actual=sample['y'],
            naive={a:sample['x'][3*j] for j,a in enumerate(WATCH_ASSETS)},max_training_end=max(r['end'] for r in train)))
    known=[r for r in evaluations if r['state']=='EVALUATED']
    if (sum(r['state']=='EVALUATED' for r in evaluations[:config.validation_days])<10 or
            sum(r['state']=='EVALUATED' for r in evaluations[config.validation_days:])<10):raise BetaBlocked('FORECAST_VALIDATION_INSUFFICIENT')
    errors=[{a:r['actual'][a]-r['prediction'][a] for a in WATCH_ASSETS} for r in known]
    error_cov=covariance(errors)
    # Keep bias in prediction uncertainty; centering errors alone hides it.
    bias={a:sum((e[a] for e in errors),D(0))/len(errors) for a in WATCH_ASSETS}
    error_second={a:{b:error_cov[a][b]+bias[a]*bias[b] for b in WATCH_ASSETS} for a in WATCH_ASSETS}
    train=[r for r in samples if r['end']<=at]
    mean,cov,analogs=predict(train,features(rows,len(rows)-1),config)
    def scores(part):
        valid=[r for r in part if r['state']=='EVALUATED'];n=len(valid)
        result=dict(count=n,unavailable=len(part)-n)
        for policy in ('prediction','naive','hold'):
            result[policy+'_mae']=None if not n else sum((abs(r['actual'][a]-(D(0) if policy=='hold' else r[policy][a]))
                for r in valid for a in WATCH_ASSETS),D(0))/(n*len(WATCH_ASSETS))
        return result
    provenance=dict(model=MODEL,parameters=asdict(config),data_source='AUTHENTICATED_COINBASE_CLOSED_HOURLY_USD_REFERENCES',
        first_at=rows[0]['at'],last_at=rows[-1]['at'],observations=len(rows),training_labels=len(train),
        maximum_training_end=max(r['end'] for r in train),history_digest=digest(rows),analog_origins=analogs,
        validation=scores(evaluations[:config.validation_days]),holdout=scores(evaluations[config.validation_days:]),
        evaluation_origins=[dict(at=r['at'],end=r['end'],state=r['state'],max_training_end=r.get('max_training_end')) for r in evaluations])
    return dict(state='READY',model=MODEL,horizon_s=HORIZON,decision_at=at,forecast_end_at=at+HORIZON,
        feature_at=rows[-1]['at'],feature_marks=deepcopy(rows[-1]['marks']),mean=mean,return_covariance=cov,error_covariance=error_second,
        provenance=provenance,forecast_validation='UNVALIDATED_RESEARCH_ESTIMATE',
        execution_calibration='CONDITIONAL_NOT_CALIBRATED')
