"""Primary v80 Experimental policy over the existing canonical RAM FIFO engine.

The older component remains an accounting/advisory compatibility engine; this
class is the only Experimental policy constructed by the v80 product UI.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from coincat_v507_shadow_arm import ShadowArmedResearch as AccountingShadow
from coincat_v80_immediate import evaluate,RELEASE_LIMIT


class StrictImmediateShadow(AccountingShadow):
    primary_immediate=True

    def __init__(self,*,experimental=False,mark_horizon_s=300,allow_synthetic_evidence=False):
        super().__init__(experimental=experimental,mark_horizon_s=mark_horizon_s)
        self.allow_synthetic_evidence=bool(allow_synthetic_evidence)
        self.synthetic_evidence={}
        self.immediate_counts=Counter()
        self.immediate_blockers=Counter()
        self.immediate_latest=[]
        self.immediate_funnel={}
        self.immediate_session_totals=Counter()
        self.immediate_session_preconsumer=Counter()

    def arm(self,**kwargs):
        partial=bool(self.experimental and kwargs.get('enrolled_quantities') and kwargs.get('fresh_usd_rates'))
        self._allow_partial_opening=partial
        was_armed=self.armed
        result=super().arm(**kwargs)
        if result and not was_armed:
            self.immediate_counts.clear();self.immediate_blockers.clear();self.immediate_latest=[]
            self.immediate_funnel={};self.synthetic_evidence={}
            self.immediate_session_totals.clear();self.immediate_session_preconsumer.clear()
            if self.experimental:
                self.last_usd_rates=dict(kwargs.get('fresh_usd_rates') or {})
                self.portfolio_marks_complete=set(self.model_balances())<=set(self.last_usd_rates)
        return result

    def observe(self,**kwargs):
        if not self.experimental:return super().observe(**kwargs)
        if not self.armed:return False
        now=kwargs['now']
        if self.last_observation is not None and now<=self.last_observation:return False
        quotes=kwargs.get('quotes') or {};allowed=set(kwargs.get('approved_catalog') or ())
        current_rules=kwargs.pop('current_product_rules',None)
        cycle=deepcopy(kwargs.pop('observation_cycle',None))
        upstream=Counter(kwargs.pop('upstream_rejections',{}))
        preconsumer=Counter()
        passed=[];results=[];funding=self.model_balances()
        for old in kwargs.get('route_ideas') or ():
            idea=deepcopy(old)
            source=idea.get('source');available=funding.get(source,Decimal(0))
            if available<=0:
                preconsumer['NO_CURRENT_RAM_FUNDING']+=1;continue
            if any(s.get('pair') not in allowed for s in idea.get('shadow_fifo_steps',())):
                preconsumer['PRODUCT_NO_LONGER_APPROVED']+=1;continue
            idea['source_units']=min(Decimal(str(idea.get('source_units',available))),available)
            frame=(old.get('immediate_assessment') or {}).get('frame') or {}
            proof=self.synthetic_evidence.get(frame.get('id'))
            rules=current_rules if current_rules is not None else (idea.get('model_product_rules') or {})
            r=evaluate(idea,quotes,rules,now=now,
                       synthetic_evidence=proof,allow_synthetic=self.allow_synthetic_evidence)
            results.append(r);self.immediate_counts[r['state']]+=1;self.immediate_blockers.update(r['blockers'])
            if r['strict']:
                candidate=r['frame']['idea']
                # Parent accounting sees only an already-qualified positive
                # immediate receipt; no forward evidence is handed to it.
                candidate.pop('forward_edge_evidence',None)
                passed.append(candidate)
        preconsumer.update(upstream)
        self.immediate_blockers.update(preconsumer)
        self.immediate_latest=results[:12]
        before=self.fifo_posted
        before_budget=self.rejected_budget;before_quote=self.rejected_quote
        data=dict(kwargs,route_ideas=passed)
        result=super().observe(**data)
        if passed and self.fifo_posted==before:
            self.immediate_blockers['BUDGET_REJECTED' if self.rejected_budget>before_budget else
                'QUOTE_REJECTED' if self.rejected_quote>before_quote else 'RAM_POST_FAILED_OR_REPLAY']+=1
        self.immediate_funnel={'cycle':cycle,'consumer_observed_at':now,'submitted_sizes':len(kwargs.get('route_ideas') or ())+sum(upstream.values()),
            'preconsumer_rejected_sizes':sum(preconsumer.values()),
            'preconsumer_rejections':dict(preconsumer),
            'reviewed_sizes':len(results),
            'positive_estimates':sum(r['positive_estimate'] for r in results),
            'negative_after_cost':sum(r['state']=='ECONOMIC_NEGATIVE' for r in results),
            'unpriced':sum(r['state']=='NOT_PRICED' for r in results),
            'strict_qualified':len(passed),'ram_conversions':self.fifo_posted-before,
            'strict_qualified_routes':len({(i['source'],i['target'],str(i.get('route'))) for i in passed}),
            'strict_failures':dict(Counter(x for r in results for x in r['blockers'])),
            'synthetic_only':self.allow_synthetic_evidence,
            'connected_strict_qualification_available':False}
        self.immediate_funnel['reconciliation_ok']=(self.immediate_funnel['submitted_sizes']==
            self.immediate_funnel['preconsumer_rejected_sizes']+self.immediate_funnel['reviewed_sizes'])
        self.immediate_session_totals['observations']+=1
        for name in ('submitted_sizes','preconsumer_rejected_sizes','reviewed_sizes',
                     'positive_estimates','negative_after_cost','unpriced','strict_qualified','ram_conversions'):
            self.immediate_session_totals[name]+=self.immediate_funnel[name]
        self.immediate_session_preconsumer.update(preconsumer)
        return result

    def reconciliation(self):
        names=('observations','submitted_sizes','preconsumer_rejected_sizes','reviewed_sizes',
               'positive_estimates','negative_after_cost','unpriced','strict_qualified','ram_conversions')
        totals={name:self.immediate_session_totals[name] for name in names}
        totals['state']='OBSERVED' if totals['observations'] else 'NOT_OBSERVED'
        totals['reconciliation_ok']=(totals.get('submitted_sizes',0)==
            totals.get('preconsumer_rejected_sizes',0)+totals.get('reviewed_sizes',0))
        totals['preconsumer_rejections']=dict(self.immediate_session_preconsumer)
        return totals

    def snapshot(self,now=None):
        r=super().snapshot(now)
        if self.experimental:r.update(primary_strategy='STRICT_IMMEDIATE_V80',
            immediate_funnel=dict(self.immediate_funnel),
            immediate_session_states=dict(self.immediate_counts),
            immediate_session_reconciliation=self.reconciliation(),
            immediate_blocker_counts=dict(self.immediate_blockers),
            connected_strict_qualification_available=False,evidence_limit=RELEASE_LIMIT)
        return r
