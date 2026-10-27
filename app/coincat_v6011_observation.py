"""v60.11 safe runtime errors and strictly advisory forward evidence.

Never serialize exception messages, filenames/paths, local variables, account data,
or research candidates into exported troubleshooting breadcrumbs.
"""
from __future__ import annotations
import traceback

def _known_module_basename(name):
    # Allow only code-like CoinCat basenames, not arbitrary path components.
    if name in ('coinbase_account.py',):
        return True
    stem=name[:-3] if name.endswith('.py') else ''
    return stem.startswith('coincat_') and all(
        c in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in stem)


def safe_callback_breadcrumb(exc):
    """Only vetted CoinCat module basename + function + line; never file paths.

    Unknown frames are completely redacted. Exception messages intentionally
    omitted because FileNotFoundError can carry private absolute paths.
    """
    frames=[]
    tb=exc.__traceback__
    for frame in traceback.extract_tb(tb)[-12:]:
        basename=frame.filename.replace('\\','/').rsplit('/',1)[-1]
        if _known_module_basename(basename):
            func=frame.name if frame.name.isidentifier() else 'unknown'
            frames.append('%s:%s:%d' % (basename,func,int(frame.lineno)))
        else:
            frames.append('EXTERNAL_FRAME_REDACTED')
    return ' > '.join(frames[-6:]) if frames else 'NO_PYTHON_FRAME_AVAILABLE'

def annotate_study(candidates, study):
    """Send existing mature observations to planner as NON-AUTHORIZING context.

    A pair-vs-cash label cannot establish strategy-conditioned funded portfolio
    HOLD-vs-SWITCH evidence. Preserve explicit no-order/no-validation properties.
    """
    out=[]
    for candidate in candidates or ():
        c=dict(candidate)
        horizon=(study or {}).get(str(c.get('strategy'))+':60m') or {}
        c['forward_observed_hourly']=int(horizon.get('OBSERVED',0))
        c['forward_positive_cash_after_cost']=int(horizon.get('positive_cash_after_cost',0))
        c['forward_maturity']=str(horizon.get('maturity','NOT_YET_OBSERVED'))
        c['oos_validated']=False
        c['sends_orders']=False
        c['action']='EXPLORE_ONLY'
        out.append(c)
    return out
