"""Isolated v1.04 record/engine compatibility; not the v1.05 application policy."""
from coincat_maker_shadow import MakerShadowTrader,validate as validate_state,active,free
from coincat_opportunity_policy import OpportunityConfig,POLICY,seed,evaluate,assess,performance
from coincat_opportunity_rejections import record as record_rejections,summary as rejection_summary,validate_detail as validate_rejection_detail
from coincat_assumed_math import fee_rate,rounded
from coincat_opportunity_public import project
from coincat_portfolio_policy import usd_marks
from coincat_shadow_source import frame_quality

class LegacyOpportunityPolicy:
    def decision_fresh(self,frame,now):return True
    def mark_fresh(self,frame,now):return 0<=now-frame['at']<=30 and all(0<=now-b['at']<=30 for b in frame['books'].values())
    def on_unpriced(self,s,frame,now,engine):pass
    name=POLICY
    provider='OPPORTUNITY_SHADOW_NO_LIVE_AUTHORITY'
    portfolio='FICTIONAL_FIVE_ASSET_PORTFOLIO'
    report_prefix='opportunity-'
    view_keys=()
    def config(self,values=None):return OpportunityConfig(**(values or {})).checked()
    def seed(self,frame,now,config):return seed(frame,now)
    evaluate=staticmethod(evaluate)
    assess=staticmethod(assess)
    performance=staticmethod(performance)
    marks=staticmethod(usd_marks)
    frame_quality=staticmethod(frame_quality)
    def can_decide(self,frame,valid=False):return valid
    def unpriced_reason(self,frame):return 'PARTIAL_OR_UNVERIFIED_INPUTS'
    def replacement_size(self,row,remaining,affordable,increment):return rounded(min(remaining,affordable),increment)
    def initialize(self,s,frame,config):pass
    def validate_extra(self,s):pass
    def mark(self,s,frame,perf):pass
    def audit_state(self,evidence,s):pass
    def report_metadata(self):
        from coincat_version import DISPLAY
        return dict(version=DISPLAY,compatibility_policy='Historical v1.04 opportunity policy')
    def observe(self,s,frame,now):pass
    def validate_frame(self,frame):fee_rate(frame,'TAKER')
    def resets_episode(self,row):return row['reason']=='NO_COST_RISK_JUSTIFIED_ADVANTAGE'
    def record_rejections(self,metrics,rows):return record_rejections(metrics,rows)
    def validate_rejections(self,value,total):return validate_rejection_detail(value,total)
    def rejection_summary(self,metrics):return rejection_summary(metrics)
    def public(self,value,engine):return project(value)

def validate(state):return validate_state(state,LegacyOpportunityPolicy())

class OpportunityTrader(MakerShadowTrader):
    def __init__(self,path,**kwargs):super().__init__(path,policy=LegacyOpportunityPolicy(),**kwargs)
