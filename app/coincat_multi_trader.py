"""Separate multi-horizon identity over the unchanged local maker lifecycle."""
from copy import deepcopy
import base64,hashlib,zlib
from coincat_beta_store import BetaBlocked,pack,unpack,MAX_PAYLOAD
from coincat_horizon_forecast import HORIZONS
from coincat_intelligent_trader import IntelligentPolicy
from coincat_intelligent_market import marks,coverage
from coincat_multi_policy import MultiConfig,POLICY,evaluate,assess,forecast_for
from coincat_multi_rejections import record,validate_detail,summary,empty,REASONS
from coincat_multi_public import project
from coincat_maker_shadow import MakerShadowTrader,active,COUNTERS
from coincat_portfolio_policy import DIRECTIONS

def prediction_counts():return dict(registered=0,known=0,unknown=0,direction_checks=0,direction_matches=0)

def encode_observation(value):
    """Lossless new-policy research evidence, never settlement or old records."""
    raw=pack(value).encode()
    return dict(format='ZLIB_BASE64_CANONICAL_JSON_V1',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
        data=base64.b64encode(zlib.compress(raw,9)).decode('ascii'))

def decode_observation(value):
    if (not isinstance(value,dict) or set(value)!={'format','bytes','sha256','data'} or
            value['format']!='ZLIB_BASE64_CANONICAL_JSON_V1' or type(value['bytes']) is not int or
            not 0<value['bytes']<=MAX_PAYLOAD or not isinstance(value['sha256'],str) or
            not isinstance(value['data'],str) or len(value['data'])>MAX_PAYLOAD):raise BetaBlocked('MULTI_OBSERVATION_ENVELOPE_INVALID')
    try:
        decoder=zlib.decompressobj();raw=decoder.decompress(base64.b64decode(value['data'],validate=True),MAX_PAYLOAD+1)
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or len(raw)!=value['bytes'] or
                hashlib.sha256(raw).hexdigest()!=value['sha256']):raise ValueError()
        return unpack(raw.decode())
    except (ValueError,TypeError,zlib.error):raise BetaBlocked('MULTI_OBSERVATION_DIGEST_OR_ENCODING_INVALID') from None

class MultiPolicy(IntelligentPolicy):
    name=POLICY;provider='MULTI_HORIZON_SHADOW_NO_LIVE_AUTHORITY';report_prefix='multi-horizon-'
    view_keys=IntelligentPolicy.view_keys+('horizon_prediction_counts',)
    def config(self,values=None):return MultiConfig(**(values or {})).checked()
    evaluate=staticmethod(evaluate);assess=staticmethod(assess)
    record_rejections=staticmethod(record);validate_rejections=staticmethod(validate_detail);rejection_summary=staticmethod(summary)
    def initialize(self,s,frame,config):
        super().initialize(s,frame,config);s['reason']='WAIT_FOR_SUPPORTED_HORIZON_OR_HOLD'
        s['forecast_evidence']={};s['horizon_prediction_counts']={n:prediction_counts() for n in HORIZONS}
        s['metrics'].update(selected_by_horizon=dict.fromkeys(HORIZONS,0),order_active_reviews=0)
    def validate_extra(self,s):
        super().validate_extra(s)
        if set(s['horizon_prediction_counts'])!=set(HORIZONS) or set(s['metrics']['selected_by_horizon'])!=set(HORIZONS):raise BetaBlocked('MULTI_CHECKPOINT_HORIZONS')
        if sum(s['metrics']['selected_by_horizon'].values())!=s['metrics']['orders']:raise BetaBlocked('MULTI_SELECTED_ORDER_COUNTS')
        for pc in s['horizon_prediction_counts'].values():
            if set(pc)!=set(prediction_counts()) or any(type(v) is not int or v<0 for v in pc.values()) or pc['known']+pc['unknown']>pc['registered'] or pc['direction_matches']>pc['direction_checks']:
                raise BetaBlocked('MULTI_FORWARD_COUNTS')
    def compact(self,s):
        # Recent display caches only; append-only intent/receipt/mark evidence
        # and all cumulative counters remain in the private transaction journal.
        for order in s['orders'].values():
            for key in ('projection','latest_projection'):
                if key in order:order[key].pop('horizons',None)
        terminal=[ref for ref,o in s['orders'].items() if o['state'] in ('FILLED','CANCELED')]
        for ref in terminal[:-8]:del s['orders'][ref]
        used={o['campaign'] for o in s['orders'].values()}
        for ref,root in list(s['campaigns'].items()):
            if root['closed'] and ref not in used:del s['campaigns'][ref]
        points=s['performance_history']
        while len(points)>1200:
            cutoff=points[-1]['at']-25*3600
            candidates=[i for i,p in enumerate(points[1:-1],1) if p['at']<cutoff]
            index=min(candidates,key=lambda i:(points[i+1]['at']-points[i-1]['at'],points[i]['at'])) if candidates else None
            if index is None:raise BetaBlocked('MULTI_DISPLAY_HISTORY_REVIEW_REQUIRED')
            del points[index]
    def placed(self,s,order):s['metrics']['selected_by_horizon'][order['projection']['selected_horizon']]+=1
    def audit_state(self,evidence,s):
        super().audit_state(evidence,s)
        # The checkpoint owns cumulative detailed counts. Avoid appending the
        # same 6 large reason dictionaries on every 10-second observation.
        evidence['metrics']={k:s['metrics'][k] for k in COUNTERS}
        if evidence['decisions'] is not None:
            fields=('state','reason','size','price','projected_marked_change_usd','expected_incremental_usd','forecast_uncertainty_usd','execution_uncertainty_usd','projected_advantage_usd')
            evidence['horizon_review']={r['id']:{name:{k:v[k] for k in fields if k in v} for name,v in r.get('horizons',{}).items()} for r in s['rows']}
            evidence['horizon_rejection_counts']=s['metrics'].get('rejection_detail')
            evidence['forecast_inputs']={}
            for name,f in s['forecast_evidence'].items():
                row={k:f.get(k) for k in ('state','reason','model','horizon_s','feature_at','mean')};p=f.get('provenance') or {}
                row['provenance']={k:p.get(k) for k in ('model','parameters','history_digest','first_at','last_at','maximum_training_end','validation','holdout')}
                evidence['forecast_inputs'][name]=row
            detail={key:evidence.pop(key) for key in ('decisions','horizon_review','horizon_rejection_counts','forecast_inputs')}
            evidence['policy_observation']=encode_observation(detail)
    def resets_episode(self,row):return row['state']=='HOLD' and row['reason'] in ('INSUFFICIENT_HORIZON_EXPECTED_ADVANTAGE','ENTRY_FEE_REMOVES_ADVANTAGE','PORTFOLIO_RISK_REMOVES_ADVANTAGE','FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE','IMMEDIATE_AFTER_FEE_MARK_NOT_POSITIVE')
    def observe(self,s,frame,now):
        if frame.get('portfolio')!=s['account_scope']:s.update(mode='REVIEW_REQUIRED',reason='ACCOUNT_SCOPE_CHANGED_SHADOW_REVIEW_REQUIRED');return
        forecasts=frame.get('horizon_forecasts',{});s['forecast_evidence']={n:{k:deepcopy(forecasts.get(n,{}).get(k)) for k in ('state','reason','model','horizon_s','feature_at','provenance','mean')} for n in HORIZONS}
        if active(s) is not None and (s['last_review_at'] is None or now-s['last_review_at']>=30):s['metrics']['order_active_reviews']+=1
        try:
            current,stamps=marks(frame,admission=True)
            if any(not 0<=now-t<=30 for t in stamps):return
        except (ValueError,TypeError,KeyError,ArithmeticError):return
        counts=s['prediction_counts']
        for p in s['predictions']:
            if p['state']!='WAITING' or now<p['due_at']:continue
            per=s['horizon_prediction_counts'][p['horizon']]
            grace=30 if p['horizon']=='M5' else 60 if p['horizon'] in ('M15','M30') else 120
            if now-p['due_at']>grace:p['state']='UNKNOWN_AT_HORIZON';counts['unknown']+=1;per['unknown']+=1;continue
            if min(stamps)<p['due_at']:continue
            actual={a:current[a]/p['marks'][a]-1 for a in current};p.update(state='OBSERVED_WINDOW_CLOSE',actual=actual,observed_at=now);counts['known']+=1;per['known']+=1
            for direction in DIRECTIONS:
                source,target=direction['source'],direction['target'];pred=p['mean'][target]-p['mean'][source];observed=actual[target]-actual[source]
                if pred:
                    for pc in (counts,per):pc['direction_checks']+=1;pc['direction_matches']+=int(pred*observed>0)
        for name,seconds in HORIZONS.items():
            if not seconds:continue # immediate marks are not forward predictions.
            try:f=forecast_for(frame,name)
            except (ValueError,TypeError,KeyError,ArithmeticError):continue
            prior=[p for p in s['predictions'] if p['horizon']==name]
            if prior and now-prior[-1]['at']<min(seconds,3600):continue
            s['predictions'].append(dict(horizon=name,at=now,due_at=now+seconds,marks=deepcopy(current),mean=deepcopy(f['mean']),state='WAITING',
                model=f['model'],history_digest=f['provenance']['history_digest']))
            counts['registered']+=1;s['horizon_prediction_counts'][name]['registered']+=1
        while len(s['predictions'])>200:
            resolved=next((i for i,p in enumerate(s['predictions']) if p['state']!='WAITING'),None)
            if resolved is None:raise BetaBlocked('MULTI_PENDING_FORECAST_LIMIT')
            s['predictions'].pop(resolved)
    def public(self,value,engine):
        frame=engine.last_frame;now=engine.clock();state=engine.state();fresh=bool(frame and 0<=now-frame['at']<=30);native,refs=coverage(frame,now) if fresh else (0,0)
        order=engine.view().get('active_order');metrics={} if state is None else state['metrics'];evidence={} if state is None else state['forecast_evidence'];per={} if state is None else state['horizon_prediction_counts']
        value.update(data_state='UNOBSERVED' if frame is None else 'STALE' if not fresh else 'FRESH' if engine.lease and engine.lease['valid'] else 'PARTIAL',
            market_coverage=native,valuation_coverage=refs,active_orders=int(order is not None),unresolved_orders=int(order is not None and order['state']=='UNKNOWN'),
            order_active_reviews=metrics.get('order_active_reviews',0),unknown_events_blocking=metrics.get('unknown_events',0))
        horizons={};detail=metrics.get('rejection_detail',{}).get('horizons',{})
        for name,seconds in HORIZONS.items():
            f=evidence.get(name) or {};p=f.get('provenance') or {};d=detail.get(name,dict(checks=0,qualified=0,rejections=empty()));pc=per.get(name,prediction_counts())
            age_limit=3720 if name=='H24' else 630 if name in ('M30','H2') else 150
            ready=f.get('state')=='READY' and fresh and 0<=now-(f.get('feature_at') or 0)<=age_limit
            code='READY' if ready else f.get('reason') or ('HORIZON_FORECAST_INVALID_OR_STALE' if f.get('state')=='READY' else 'UNOBSERVED')
            if code not in set(REASONS)|{'READY','UNOBSERVED'}:code='OTHER_UNCLASSIFIED'
            horizons[name]=dict(horizon_s=seconds,state='READY' if ready else 'HOLD' if f else 'UNOBSERVED',reason=code,
                checks=d['checks'],qualified=d['qualified'],rejected=d['rejections']['total'],selected_orders=metrics.get('selected_by_horizon',{}).get(name,0),
                validation_predictions=(p.get('validation') or {}).get('count',0),holdout_predictions=(p.get('holdout') or {}).get('count',0),
                forward_predictions=pc['registered'],forward_known=pc['known'],forward_unknown=pc['unknown'],direction_checks=pc['direction_checks'],direction_matches=pc['direction_matches'],rejections=d['rejections'])
        return project(value,horizons)
    def report_metadata(self):
        from coincat_version import DISPLAY
        return dict(version=DISPLAY,selected_policy=POLICY,horizons_s=deepcopy(HORIZONS),comparison='INDEPENDENT_LIVE_TRIAL_NOT_PAIRED',
            observation_encoding='ZLIB_BASE64_CANONICAL_JSON_V1',observation_decoder='coincat_multi_trader.decode_observation')

class MultiTrader(MakerShadowTrader):
    def __init__(self,path,**kwargs):super().__init__(path,policy=MultiPolicy(),**kwargs)
    def rolling_performance(self):
        from coincat_portfolio_performance import rolling
        view=self.view();return rolling([] if view['state'] is None else view['state']['performance_history'],view['performance'])
