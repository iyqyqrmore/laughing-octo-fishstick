"""Fixed direct short-horizon labels; no return extrapolation or parameter search."""
from copy import deepcopy
from decimal import Decimal as D
import math,sqlite3,hashlib
from coincat_beta_store import BetaBlocked,pack
from coincat_execution_limits import native_math
from coincat_forecast_24h import covariance
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_ASSETS
from coincat_candle_cache import REFERENCES

HORIZONS={'IMMEDIATE':0,'M5':300,'M15':900,'M30':1800,'H2':7200,'H24':86400}
SHORT={'M5':('ONE_MINUTE',60,4320,5,(5,30,60)),
    'M15':('ONE_MINUTE',60,4320,15,(5,30,60)),
    'M30':('FIVE_MINUTE',300,2880,6,(6,24,72)),
    'H2':('FIVE_MINUTE',300,2880,24,(6,24,72))}
MODEL='DIRECT_SHORT_ANALOG_V1'
PARAMETERS=dict(minimum_train=64,neighbors=12,maximum_train=256,validation=16,holdout=16,minimum_known_per_fold=12,
    feature_deviations=8,error_variance_floor='0.00000001')

def history_digest(rows):
    # Histories are not ledger records. Hash each bounded canonical row without
    # weakening the protected financial journal's one-megabyte payload limit.
    value=hashlib.sha256()
    for row in rows:
        raw=pack(row).encode();value.update(len(raw).to_bytes(8,'big'));value.update(raw)
    return value.hexdigest()

def checked_rows(observations,at,seconds,required,age):
    if type(at) not in (int,float) or not math.isfinite(at):raise BetaBlocked('HORIZON_TIME_INVALID')
    rows=[deepcopy(r) for r in observations if type(r.get('at')) in (int,float) and r['at']<=at][-required:]
    if len(rows)<required:raise BetaBlocked('HORIZON_HISTORY_INSUFFICIENT')
    for i,r in enumerate(rows):
        if r['at']%seconds or set(r['marks'])!=set(WATCH_ASSETS) or any(exact(x)<=0 for x in r['marks'].values()):raise BetaBlocked('HORIZON_HISTORY_INVALID')
        if i and r['at']-rows[i-1]['at']!=seconds:raise BetaBlocked('HORIZON_HISTORY_GAP')
    if not 0<=at-rows[-1]['at']<=age:raise BetaBlocked('HORIZON_HISTORY_STALE')
    return rows

def _features(rows,index,lookbacks):
    a,b,window=lookbacks;out=[]
    for asset in WATCH_ASSETS:
        p=float(rows[index]['marks'][asset]);returns=[float(rows[j]['marks'][asset]/rows[j-1]['marks'][asset]-1) for j in range(index-window+1,index+1)]
        if any(not math.isfinite(x) or abs(x)>.2 for x in returns):raise BetaBlocked('HORIZON_RETURN_OUTLIER')
        out.extend((p/float(rows[index-a]['marks'][asset])-1,p/float(rows[index-b]['marks'][asset])-1,math.sqrt(sum(x*x for x in returns)/window)))
    return tuple(out)

def _predict(train,x):
    train=train[-PARAMETERS['maximum_train']:]
    if len(train)<PARAMETERS['minimum_train']:raise BetaBlocked('HORIZON_TRAINING_INSUFFICIENT')
    dim=len(x);center=[sum(r['x'][j] for r in train)/len(train) for j in range(dim)]
    scales=[max(1e-6,math.sqrt(sum((r['x'][j]-center[j])**2 for r in train)/(len(train)-1))) for j in range(dim)]
    if any(abs(x[j]-center[j])>PARAMETERS['feature_deviations']*scales[j] for j in range(dim)):raise BetaBlocked('HORIZON_FEATURE_OUT_OF_DISTRIBUTION')
    candidates=sorted(train,key=lambda r:(sum(((r['x'][j]-x[j])/scales[j])**2 for j in range(dim)),-r['at']))[:PARAMETERS['neighbors']]
    mean={a:sum((r['y'][a] for r in candidates),D(0))/len(candidates) for a in WATCH_ASSETS}
    return mean,covariance([r['y'] for r in candidates]),[r['at'] for r in candidates]

def _scores(part):
    valid=[r for r in part if r['state']=='EVALUATED'];n=len(valid);result=dict(count=n,unavailable=len(part)-n)
    for policy in ('prediction','naive','hold'):
        result[policy+'_mae']=None if not n else sum((abs(r['actual'][a]-(D(0) if policy=='hold' else r[policy][a])) for r in valid for a in WATCH_ASSETS),D(0))/(n*5)
    return result

@native_math
def short_forecast(observations,at,horizon):
    granularity,seconds,required,bars,lookbacks=SHORT[horizon];rows=checked_rows(observations,at,seconds,required,2*seconds+30)
    samples=[]
    for i in range(max(lookbacks),len(rows)-bars):
        if rows[i]['at']%HORIZONS[horizon]:continue
        y={a:exact(rows[i+bars]['marks'][a])/exact(rows[i]['marks'][a])-1 for a in WATCH_ASSETS}
        if any(abs(v)>D('.8') for v in y.values()):raise BetaBlocked('HORIZON_RETURN_OUTLIER')
        samples.append(dict(at=rows[i]['at'],end=rows[i+bars]['at'],x=_features(rows,i,lookbacks),y=y,
            naive={a:exact(rows[i]['marks'][a])/exact(rows[i-bars]['marks'][a])-1 for a in WATCH_ASSETS}))
    if len(samples)<PARAMETERS['minimum_train']+32:raise BetaBlocked('HORIZON_TRAINING_INSUFFICIENT')
    evaluations=[]
    for sample in samples[-32:]:
        train=[r for r in samples if r['end']<=sample['at']]
        try:prediction,_,_=_predict(train,sample['x'])
        except BetaBlocked as exc:
            if str(exc)!='HORIZON_FEATURE_OUT_OF_DISTRIBUTION':raise
            evaluations.append(dict(at=sample['at'],end=sample['end'],state='OUT_OF_DISTRIBUTION',actual=sample['y'],naive=sample['naive']));continue
        evaluations.append(dict(at=sample['at'],end=sample['end'],state='EVALUATED',prediction=prediction,actual=sample['y'],naive=sample['naive'],
            max_training_end=max(r['end'] for r in train)))
    known=[r for r in evaluations if r['state']=='EVALUATED'];validation=_scores(evaluations[:16]);holdout=_scores(evaluations[16:])
    provenance=dict(model=MODEL,parameters=dict(**PARAMETERS,horizon=horizon,granularity=granularity,lookbacks=lookbacks),
        first_at=rows[0]['at'],last_at=rows[-1]['at'],observations=len(rows),history_digest=history_digest(rows),history_digest_format='LENGTH_PREFIXED_CANONICAL_ROWS_V1',
        data_source='AUTHENTICATED_COINBASE_CLOSED_REFERENCE_CANDLES',validation=validation,holdout=holdout,
        evaluation_origins=[{k:r.get(k) for k in ('at','end','state','max_training_end')} for r in evaluations])
    if min(validation['count'],holdout['count'])<PARAMETERS['minimum_known_per_fold']:
        return dict(state='HOLD',reason='HORIZON_VALIDATION_INSUFFICIENT',horizon_s=HORIZONS[horizon],provenance=provenance)
    errors=[{a:r['actual'][a]-r['prediction'][a] for a in WATCH_ASSETS} for r in known];error_cov=covariance(errors)
    bias={a:sum((e[a] for e in errors),D(0))/len(errors) for a in WATCH_ASSETS}
    uncertainty={a:{b:error_cov[a][b]+bias[a]*bias[b]+(D(PARAMETERS['error_variance_floor']) if a==b else D(0)) for b in WATCH_ASSETS} for a in WATCH_ASSETS}
    train=[r for r in samples if r['end']<=at];mean,cov,analogs=_predict(train,_features(rows,len(rows)-1,lookbacks))
    provenance.update(training_labels=len(train),maximum_training_end=max(r['end'] for r in train),analog_origins=analogs)
    result=dict(state='READY',model=MODEL,horizon_s=HORIZONS[horizon],decision_at=at,forecast_end_at=at+HORIZONS[horizon],feature_at=rows[-1]['at'],
        feature_marks=deepcopy(rows[-1]['marks']),periods_per_horizon=bars,mean=mean,return_covariance=cov,error_covariance=uncertainty,
        provenance=provenance,forecast_validation='UNVALIDATED_RESEARCH_ESTIMATE',execution_calibration='CONDITIONAL_NOT_CALIBRATED')
    naive_rows=[dict(r,state='EVALUATED',prediction=r['naive']) for r in evaluations]
    naive_errors=[{a:r['actual'][a]-r['prediction'][a] for a in WATCH_ASSETS} for r in naive_rows];naive_cov=covariance(naive_errors)
    naive_bias={a:sum((r[a] for r in naive_errors),D(0))/len(naive_errors) for a in WATCH_ASSETS}
    naive=deepcopy(result);naive.update(model='NAIVE_DIRECT_MOMENTUM_V1',mean={a:rows[-1]['marks'][a]/rows[-1-bars]['marks'][a]-1 for a in WATCH_ASSETS},
        return_covariance=covariance([r['y'] for r in train[-PARAMETERS['maximum_train']:]]),
        error_covariance={a:{b:naive_cov[a][b]+naive_bias[a]*naive_bias[b]+(D(PARAMETERS['error_variance_floor']) if a==b else D(0)) for b in WATCH_ASSETS} for a in WATCH_ASSETS})
    naive['provenance'].update(model='NAIVE_DIRECT_MOMENTUM_V1',parameters=dict(horizon=horizon,rule='LAST_OBSERVED_SAME_HORIZON_RETURN',uncertainty='CHRONOLOGICAL_NAIVE_RESIDUALS'),
        validation=_scores(naive_rows[:16]),holdout=_scores(naive_rows[16:]))
    result['naive_reference']=naive;return result

@native_math
def immediate_inputs(observations,at):
    rows=checked_rows(observations,at,60,61,150)
    returns=[{a:exact(b['marks'][a])/exact(p['marks'][a])-1 for a in WATCH_ASSETS} for p,b in zip(rows,rows[1:])]
    if any(abs(v)>D('.2') for row in returns for v in row.values()):raise BetaBlocked('HORIZON_RETURN_OUTLIER')
    cov=covariance(returns);mu={a:sum((r[a] for r in returns),D(0))/len(returns) for a in WATCH_ASSETS}
    cov={a:{b:2*(v+mu[a]*mu[b]) for b,v in row.items()} for a,row in cov.items()}
    provenance=dict(model='SYNCHRONIZED_IMMEDIATE_MARK_V1',parameters=dict(risk_observations=61,rest_risk_s=120),
        first_at=rows[0]['at'],last_at=rows[-1]['at'],observations=61,history_digest=history_digest(rows),history_digest_format='LENGTH_PREFIXED_CANONICAL_ROWS_V1',maximum_training_end=rows[-1]['at'],
        validation=dict(count=0,unavailable=0),holdout=dict(count=0,unavailable=0))
    return dict(state='READY',model='SYNCHRONIZED_IMMEDIATE_MARK_V1',horizon_s=0,decision_at=at,forecast_end_at=at,
        feature_at=rows[-1]['at'],feature_marks=deepcopy(rows[-1]['marks']),periods_per_horizon=2,mean=dict.fromkeys(WATCH_ASSETS,D(0)),
        return_covariance=cov,error_covariance={a:dict.fromkeys(WATCH_ASSETS,D(0)) for a in WATCH_ASSETS},provenance=provenance,
        forecast_validation='CURRENT_MARK_CALCULATION_NOT_RETURN_FORECAST',execution_calibration='CONDITIONAL_NOT_CALIBRATED')

class ForecastBundle:
    def __init__(self,hourly,minute,backfill):self.hourly=hourly;self.minute=minute;self.backfill=backfill;self.cache={};self.panel_cache={}
    def panels(self,at):
        result={}
        for g,seconds,required in (('ONE_MINUTE',60,4320),('FIVE_MINUTE',300,2880),('ONE_HOUR',3600,25)):
            revision=self.hourly.revision if g=='ONE_HOUR' else self.minute.revisions[g];key=(revision,int(at)//seconds)
            try:
                if g not in self.panel_cache or self.panel_cache[g][0]!=key:
                    rows=self.hourly.panel(at,limit=25,record_status=False) if g=='ONE_HOUR' else self.minute.panel(g,at,required)
                    self.panel_cache[g]=(key,rows)
                result[g]=self.panel_cache[g][1]
            except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError):
                self.backfill.review.update((g,p) for p in REFERENCES);result[g]=[]
        for left,right in (('ONE_MINUTE','FIVE_MINUTE'),('ONE_MINUTE','ONE_HOUR'),('FIVE_MINUTE','ONE_HOUR')):
            a={r['at']:r['marks'] for r in result[left]};b={r['at']:r['marks'] for r in result[right]}
            common=sorted(a.keys()&b.keys())[-72:]
            if any(abs(a[t][asset]/b[t][asset]-1)>D('.002') for t in common for asset in WATCH_ASSETS):
                for g in (left,right):self.backfill.review.update((g,p) for p in REFERENCES)
        return result
    def estimate(self,at,baseline=None):
        result={};panels=self.panels(at)
        for name in HORIZONS:
            g='ONE_HOUR' if name=='H24' else 'ONE_MINUTE' if name in ('IMMEDIATE','M5','M15') else 'FIVE_MINUTE'
            try:
                if self.backfill.reviewed(g):raise BetaBlocked('HORIZON_HISTORY_REVIEW_REQUIRED')
                if name=='H24':result[name]=deepcopy(baseline if baseline is not None else self.hourly.estimate(at));continue
                seconds=60 if g=='ONE_MINUTE' else 300;required=4320 if g=='ONE_MINUTE' else 2880
                if g not in panels:panels[g]=self.minute.panel(g,at,required)
                key=(self.minute.revisions[g],int(at)//seconds)
                if name not in self.cache or self.cache[name][0]!=key:
                    try:f=immediate_inputs(panels[g],at) if name=='IMMEDIATE' else short_forecast(panels[g],at,name)
                    except BetaBlocked as exc:f=dict(state='HOLD',reason=str(exc),horizon_s=HORIZONS[name])
                    self.cache[name]=(key,f)
                f=deepcopy(self.cache[name][1]);f.update(decision_at=at,forecast_end_at=at+HORIZONS[name]);result[name]=f
            except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError) as exc:
                code=str(exc) if isinstance(exc,BetaBlocked) else 'HORIZON_DATA_UNAVAILABLE'
                if code.startswith('HISTORY_CACHE') or isinstance(exc,(OSError,sqlite3.Error)):
                    code='HORIZON_HISTORY_REVIEW_REQUIRED';self.backfill.review.update((g,p) for p in REFERENCES)
                result[name]=dict(state='HOLD',reason=code,horizon_s=HORIZONS[name])
        return result
