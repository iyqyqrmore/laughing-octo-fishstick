"""v1.05 policy adapter over the shared, shadow-only maker state machine."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_maker_shadow import MakerShadowTrader,active
from coincat_intelligent_policy import IntelligentConfig,POLICY,seed,evaluate,assess,performance,checked_forecast
from coincat_intelligent_rejections import record,summary,validate_detail
from coincat_intelligent_public import project
from coincat_forecast_24h import HORIZON
from coincat_assumed_math import fee_rate,rounded
from coincat_beta_store import BetaBlocked
from coincat_portfolio_policy import DIRECTIONS,portfolio_value
from coincat_intelligent_market import marks as usd_marks,quality,can_decide,coverage,decision_fresh
from coincat_portfolio_performance import append_point,rolling
from coincat_manual_trade import identity

class IntelligentPolicy:
    name=POLICY
    provider='INTELLIGENT_24H_SHADOW_NO_LIVE_AUTHORITY'
    portfolio='FROZEN_FIVE_ASSET_SHADOW_PORTFOLIO'
    report_prefix='intelligent-24h-'
    view_keys=('performance_history','forecast_evidence','funding_mode','prediction_counts','campaigns')
    def config(self,values=None):return IntelligentConfig(**(values or {})).checked()
    seed=staticmethod(seed)
    evaluate=staticmethod(evaluate)
    assess=staticmethod(assess)
    performance=staticmethod(performance)
    marks=staticmethod(usd_marks)
    frame_quality=staticmethod(quality)
    can_decide=staticmethod(can_decide)
    decision_fresh=staticmethod(decision_fresh)
    def mark_fresh(self,frame,now):return 0<=now-frame['at']<=30 and decision_fresh(frame,now)
    def on_unpriced(self,s,frame,now,engine):
        o=active(s)
        if o is not None:engine._request_cancel(s,o,now,'INPUTS_UNRELIABLE_AT_REVIEW',replace=False)
    record_rejections=staticmethod(record)
    validate_rejections=staticmethod(validate_detail)
    rejection_summary=staticmethod(summary)
    def validate_frame(self,frame):fee_rate(frame,'MAKER')
    def unpriced_reason(self,frame):
        try:fee_rate(frame or {},'MAKER');return 'PARTIAL_OR_UNVERIFIED_INPUTS'
        except (ValueError,TypeError,KeyError,ArithmeticError):return 'FRESH_AUTHENTICATED_MAKER_FEE_REQUIRED'
    def resets_episode(self,row):return row['reason'] in ('INSUFFICIENT_24H_EXPECTED_ADVANTAGE','ENTRY_FEE_REMOVES_ADVANTAGE','PORTFOLIO_RISK_REMOVES_ADVANTAGE','FORECAST_UNCERTAINTY_REMOVES_ADVANTAGE')
    def replacement_size(self,row,remaining,affordable,increment):return rounded(min(remaining,affordable,row['size']),increment)
    def initialize(self,s,frame,config):
        s.update(funding_mode=config.funding_mode,account_scope=identity(frame['portfolio']),performance_history=[],
            forecast_evidence=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT'),predictions=[],
            prediction_counts=dict(registered=0,known=0,unknown=0,direction_checks=0,direction_matches=0))
        s['reason']='WAIT_FOR_DIRECT_24H_HISTORY_AND_POSITIVE_ADVANTAGE'
    def validate_extra(self,s):
        config=self.config(s['config'])
        if s.get('funding_mode')!=config.funding_mode or len(s.get('performance_history',[]))>2100 or len(s.get('predictions',[]))>200:
            raise BetaBlocked('INTELLIGENT_CHECKPOINT_INVARIANT')
        identity(s['account_scope'])
        if portfolio_value(s['original'],s['seed_marks'])!=s['initial_usd']:raise BetaBlocked('INTELLIGENT_ORIGINAL_VALUE_CONFLICT')
        pc=s['prediction_counts']
        if (set(pc)!={'registered','known','unknown','direction_checks','direction_matches'} or
                any(type(n) is not int or n<0 for n in pc.values()) or pc['known']+pc['unknown']>pc['registered'] or
                pc['direction_matches']>pc['direction_checks']):raise BetaBlocked('INTELLIGENT_FORWARD_COUNT_CONFLICT')
    def mark(self,s,frame,perf):append_point(s,perf)
    def audit_state(self,evidence,s):evidence['marked_performance']=deepcopy(s['last_performance'])
    def report_metadata(self):
        from coincat_version import DISPLAY
        return dict(version=DISPLAY,selected_policy=POLICY,forecast_horizon_s=86400)
    def observe(self,s,frame,now):
        if frame.get('portfolio')!=s['account_scope']:
            s.update(mode='REVIEW_REQUIRED',reason='ACCOUNT_SCOPE_CHANGED_SHADOW_REVIEW_REQUIRED');return
        f=frame.get('forecast') or dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT')
        s['forecast_evidence']={k:deepcopy(f[k]) for k in ('state','reason','model','horizon_s','decision_at','forecast_end_at','feature_at','provenance','history') if k in f}
        if not can_decide(frame):return
        marks,_=usd_marks(frame);counts=s['prediction_counts']
        for prediction in s['predictions']:
            if prediction['state']!='WAITING' or now<prediction['due_at']:continue
            if now-prediction['due_at']>120:
                prediction['state']='UNKNOWN_AT_HORIZON';counts['unknown']+=1;continue
            actual={a:marks[a]/prediction['marks'][a]-1 for a in marks};prediction.update(state='OBSERVED_WINDOW_CLOSE',actual=actual,observed_at=now)
            counts['known']+=1
            for direction in DIRECTIONS:
                source,target=direction['source'],direction['target'];pred=prediction['mean'][target]-prediction['mean'][source];observed=actual[target]-actual[source]
                if pred:
                    counts['direction_checks']+=1;counts['direction_matches']+=int(pred*observed>0)
        try:checked_forecast(frame);ready=True
        except (ValueError,TypeError,KeyError,ArithmeticError):ready=False
        if ready and (not s['predictions'] or now-s['predictions'][-1]['at']>=3600):
            s['predictions'].append(dict(at=now,due_at=now+HORIZON,marks=marks,mean=deepcopy(f['mean']),state='WAITING',
                model=f['model'],history_digest=f['provenance']['history_digest']))
            counts['registered']+=1
            while len(s['predictions'])>200:
                if s['predictions'][0]['state']=='WAITING':raise BetaBlocked('INTELLIGENT_PENDING_FORECAST_LIMIT')
                s['predictions'].pop(0)
    def public(self,value,engine):
        frame=engine.last_frame;now=engine.clock();state=engine.state();evidence={} if state is None else state['forecast_evidence']
        history=evidence.get('history',{});provenance=evidence.get('provenance',{});pc={} if state is None else state['prediction_counts']
        fresh=bool(frame and 0<=now-frame['at']<=30)
        model_ready=evidence.get('state')=='READY';reason=evidence.get('reason','')
        history_state='READY' if model_ready else 'STALE' if reason=='FORECAST_HISTORY_STALE' else 'GAP' if reason=='FORECAST_HISTORY_GAP' else 'REVIEW_REQUIRED' if 'REVIEW_REQUIRED' in reason else 'NOT_READY'
        native,refs=coverage(frame,now) if fresh else (0,0)
        o=engine.view().get('active_order');value.update(market_coverage=native,valuation_coverage=refs,data_state='UNOBSERVED' if frame is None else 'STALE' if not fresh else 'FRESH' if engine.lease and engine.lease['valid'] else 'PARTIAL',
            history_state=history_state,history_observations=int(provenance.get('observations',history.get('aligned_observations',0))),
            history_required=2400,history_references=5 if model_ready else int(history.get('reference_count',0)),
            validation_predictions=int(provenance.get('validation',{}).get('count',0)),holdout_predictions=int(provenance.get('holdout',{}).get('count',0)),
            active_orders=int(o is not None),unresolved_orders=int(o is not None and o['state']=='UNKNOWN'),
            forward_predictions=pc.get('registered',0),forward_known=pc.get('known',0),forward_unknown=pc.get('unknown',0),
            forward_direction_checks=pc.get('direction_checks',0),forward_direction_matches=pc.get('direction_matches',0))
        return project(value)

class IntelligentTrader(MakerShadowTrader):
    def __init__(self,path,**kwargs):super().__init__(path,policy=IntelligentPolicy(),**kwargs)
    def rolling_performance(self):
        view=self.view();s=view['state']
        return rolling([] if s is None else s['performance_history'],view['performance'])
