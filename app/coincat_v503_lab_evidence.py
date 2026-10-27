"""Evidence-graded AI Lab research & read-only trading budget advisory.

Never imports Coinbase, broker submission, or mutates user budgets. Deliberately
returns a ZERO eligible research budget when validation is incomplete. Display
advice is separate from per-order / portfolio safeguards and ARM controls.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation


def _fraction(n, denominator):
    try:
        return max(0, min(100, round(100 * float(n) / max(1, float(denominator)))))
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return 0


def _positive_decimal(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and n > 0 else Decimal(0)
    except (TypeError, InvalidOperation, ValueError):
        return Decimal(0)


def grade_lab(*, catalog_total=0, catalog_seen=0, focused_total=0,
              focused_mature=0, verified_forward_labels=0,
              relative_marks=0, relative_assets=0, route_ideas=(),
              fee_fresh=False, usd_complete=False, gpu_heldout=False,
              current_order_budget='0', scan_fresh=False, minimum_net_advantage_usd='0.10'):
    """A deterministic, non-predictive audit of research maturity and usability.

    Old count-only readiness is intentionally not treated as a model win rate.
    Cross-currency validation is considered ONLY where a chronologically held-out
    USD-relative model passed its naive HOLD baseline AND cost-adjusted tail.
    """
    minimum=_positive_decimal(minimum_net_advantage_usd)
    routes=list(route_ideas or ())
    oos_routes=[r for r in routes if r.get('oos_validated') is True]
    feasible=[r for r in oos_routes if r.get('research_decision')=='SWITCH_WORTH_RESEARCH'
              and minimum>0 and _positive_decimal(r.get('net_p10_usd'))>=minimum
              and _positive_decimal(r.get('net_mean_usd'))>=minimum]
    # Research-only preferred transaction size, derived from independently
    # observed source-asset funding. Manual broker caps do NOT restrict AI Lab
    # research or the advisory. SHADOW/LIVE have separate checks before fills.
    possible=[]
    for r in feasible:
        try:
            before=Decimal(str(r['initial_wallet_usd_mark']))
            src=Decimal(str(r['source_units']))
            used=Decimal(str(r['input_units_planned']))
            if before.is_finite() and src>0 and 0<used<=src:
                possible.append(before*used/src)
        except (InvalidOperation,KeyError,TypeError,ValueError,ZeroDivisionError):pass
    order_cap=_positive_decimal(current_order_budget)
    eligible=bool(fee_fresh and usd_complete and scan_fresh and feasible and possible)
    suggested=min(possible) if eligible else Decimal(0)
    cards=[
        {'key':'catalog','name':'All-spot catalog observations','value':_fraction(catalog_seen,catalog_total),
         'detail':f'{catalog_seen}/{catalog_total} discovered; coverage is not prediction skill'},
        {'key':'quotes','name':'Focused live-quote maturity','value':_fraction(focused_mature,focused_total),
         'detail':f'{focused_mature}/{focused_total} focused pairs with sufficient quotes'},
        {'key':'forward','name':'Verified BUY / SELL outcomes','value':_fraction(verified_forward_labels,240),
         'detail':f'{verified_forward_labels}/240 authenticated-fee forward observations'},
        {'key':'relative','name':'HOLD versus SWITCH out-of-sample','value':100 if feasible else (50 if oos_routes else 0),
         'detail':f'{len(oos_routes)} chronologically validated; {len(feasible)} with positive estimated cost-adjusted downside; public USD marks {relative_marks} across {relative_assets} assets'},
        {'key':'fees','name':'Verified execution-cost inputs','value':100 if fee_fresh else 0,
         'detail':'Authenticated account fee tier fresh; pair previews and realized fills remain separate' if fee_fresh else 'FEE UNVERIFIED • no estimated profitable trades'},
        {'key':'gpu','name':'GPU held-out directional model','value':100 if gpu_heldout else 0,
         'detail':'Held-out GPU model assessed (observe-only)' if gpu_heldout else 'WAIT • model not yet verified; never a substitute for portfolio validation'},
    ]
    blockers=[]
    if not scan_fresh:blockers.append('stale scan')
    if not fee_fresh:blockers.append('unverified fee tier')
    if not usd_complete:blockers.append('incomplete portfolio USD marks')
    if not oos_routes:blockers.append('no qualified out-of-sample route evidence')
    if not feasible and oos_routes:blockers.append('no positive after-cost HOLD/SWITCH downside')
    if minimum<=0:blockers.append('invalid net USD advantage preference')
    reason='; '.join(blockers) if blockers else 'held-out route research merits further read-only review'
    return {'cards':cards,'budget_eligible':eligible,'research_preferred_order_usd':suggested,
            'manual_order_cap_usd':order_cap,'total_ideas':len(routes),'oos_routes':len(oos_routes),
            'positive_after_cost_routes':len(feasible),'reason':reason,
            'minimum_net_advantage_usd':minimum,
            'catalog_total':int(catalog_total),'catalog_seen':int(catalog_seen),
            'forward_labels':int(verified_forward_labels),'gpu_observe_only':True,
            'changes_broker_limits':False,'authorizes_order':False}


def budget_text(report,manual_daily='',manual_exposure='',manual_attempts=''):
    current=report['manual_order_cap_usd']
    pref=report['research_preferred_order_usd']
    lines=[f'Minimum projected full-route advantage vs HOLD: ${report["minimum_net_advantage_usd"]:.2f} (research only)',
           f'Saved manual SHADOW budgets • Order ${current:f} | Daily ${manual_daily} | Exposure ${manual_exposure} | Attempts/24h {manual_attempts}',
           f'AI Lab research-preferred candidate size: ${pref:.2f} (NOT capped by manual budgets; NOT an order setting)']
    if report['budget_eligible']:
        lines.append('RESEARCH CANDIDATE • held-out HOLD/SWITCH edge passed a preliminary cost screen; execution and production ledger still BLOCKED')
    else:
        lines.append('PREFERRED ACTION: HOLD / no new research-funded exposure • '+report['reason'])
    lines.append('No model, gauge or advisory can ARM trading, increase caps, or permit unverified Coinbase orders.')
    return '\n'.join(lines)


def diagnostic_text(report):
    lines=['AI LAB EVIDENCE → AUTO TRADER PREFERRED BUDGET • OBSERVATION ONLY',
           'Catalog/quote/forward coverage numbers describe DATA, never probability of winning.',
           'Validation requires a chronological hold-out; after-cost positive-route screening is independent.',
           'Independent full-production broker, fills, risk and Coinbase order previews remain NOT VERIFIED.']
    for c in report['cards']:
        lines.append(f'{c["name"]}: {c["value"]}% visualization • {c["detail"]}')
    lines += [f'Full HOLD-vs-SWITCH after-cost advantage target: ${report["minimum_net_advantage_usd"]:.2f} (editable, NOT guaranteed realized P&L)',
              f'Routes evaluated on this screen: {report["total_ideas"]}',
              f'Chronological held-out routes: {report["oos_routes"]}',
              f'Positive estimated cost-adjusted downside routes: {report["positive_after_cost_routes"]}',
              f'Research preferred $/order: {report["research_preferred_order_usd"]}',
              'Risk action: '+('RESEARCH REVIEW ONLY' if report['budget_eligible'] else 'HOLD / $0 preferred research exposure'),
              'AI LAB funding research not restricted by manual SHADOW caps; Broker limits modified: NO • Order execution permission: NO',
              'Capacity Advisor UI retired; existing risk-stage caps and explicit typed approvals retained internally.',
              'NO REAL ORDER • NO AUTHORIZE • END AI LAB EVIDENCE AUDIT']
    return '\n'.join(lines)+'\n'


def capture_app_lab(app,now=None):
    """Read-only shared view used by both tabs and the single export.

    No authenticated GET, subprocess, broker order or database write. Public
    per-pair labels can be shown; financial portfolio/holding details remain out.
    """
    import time
    wall=time.time() if now is None else float(now)
    cycle=getattr(app,'last_cycle',None) or {}
    disc=cycle.get('discovery') or {}
    reviewed=cycle.get('reviews') or []
    seen=int(disc.get('coverage') or 0)
    total=len(set(getattr(app,'catalog',()) or ()))
    mature=sum(1 for r in reviewed if r.get('count',0)>=8)
    auto=cycle.get('auto_rotation') or {}
    try:forward=int(app.directional.overview().get('verified',0))
    except (AttributeError,ValueError,TypeError):forward=0
    try:stats=app.relative_lab.public_stats(now=wall)
    except (AttributeError,ValueError,TypeError):stats={}
    try:tier=app.fee_learning.latest_tier(now=int(wall))
    except (AttributeError,ValueError,TypeError):tier={'fresh':False}
    age=wall-float(getattr(app,'catalog_at',0) or 0)
    import time as _t
    scan_age=_t.monotonic()-float(getattr(app,'_last_scan_at',0) or 0)
    return grade_lab(catalog_total=total,catalog_seen=seen,
        focused_total=len(reviewed),focused_mature=mature,
        verified_forward_labels=forward,relative_marks=stats.get('rows',0),
        relative_assets=stats.get('assets',0),route_ideas=auto.get('ideas') or (),
        fee_fresh=tier.get('fresh') is True,
        usd_complete=bool((getattr(app,'_portfolio_coverage',{}) or {}).get('complete')),
        gpu_heldout=bool(getattr(app,'_gpu_validated',False)),
        current_order_budget=(getattr(app,'_manual_budget_saved',{}).get('per_order_usd','0')),
        scan_fresh=bool(total and 0<=age<=7200 and 0<=scan_age<=180),
        minimum_net_advantage_usd=getattr(app,'switch_minimum_usd',Decimal('0.10')))


def saved_gpu_heldout_status(folder):
    """Verify saved research reports exist and BOTH held-out directions won.

    An assessed model, stale label count, or single passing direction does NOT
    qualify. Safe read-only JSON; never loads or executes the model weights.
    """
    import json
    from pathlib import Path
    folder=Path(folder)
    report=folder/'CoinCat_GPU_Two_Way_Research_Report.json'
    weights=folder/'CoinCat_GPU_Two_Way_ObserveOnly.pt'
    if not report.is_file() or not weights.is_file():return False
    try:
        if report.stat().st_size>100_000:return False
        data=json.loads(report.read_text(encoding='utf-8'))
        return bool(data.get('status')=='EVALUATED' and int(data.get('labeled',0))>=240
                    and data.get('BUY',{}).get('better_than_baseline') is True
                    and data.get('SELL_REBUY',{}).get('better_than_baseline') is True)
    except (OSError,UnicodeError,ValueError,TypeError,KeyError):return False
