"""Explicit SYNTHETIC calibration for plumbing tests, never market evidence.

Accounting/capacity fixtures inject this provider to isolate receipts and
budgets. Real passive SQLite learning is exercised independently in v70.6 tests.
"""
from coincat_v706_selection import MODEL,features


def evidence(pair,side,now,*,growth='.024',context='UP_STRONG',label=None):
    label=now if label is None else label
    return dict(model=MODEL,state='READY_EXPERIMENTAL',pair=pair,side=side,
        context=context,asof=now,feature_at=now,horizon_s=300,
        observed_windows=8,missing_windows=0,nonoverlap_verified=True,
        first_opened_at=label-2400,last_label_at=label,
        mean_relative_growth=growth,p25_relative_growth=growth)


def calibrated(idea,now,**kwargs):
    step=idea['shadow_fifo_steps'][0]
    return dict(idea,selection_asof=now,
        forward_edge_evidence=evidence(step['pair'],step['side'],now,**kwargs))


class SyntheticCalibratedProvider:
    """Intentional favorable evidence stub; not used by strategy replays."""
    def observe(self,**kwargs):return {'state':'SYNTHETIC_CALIBRATION_STUB'}
    def forecasts(self,*,pairs,snapshot,now):
        current=features(snapshot,now)
        return {(p,s):evidence(p,s,now,context=current[p][s])
                for p in pairs if p in current for s in ('BUY','SELL')}
    def summary(self):return {'state':'SYNTHETIC_CALIBRATION_STUB','execution_certified':False}
