"""Read-only USD-normalized *research* sensitivity for portfolio-rotation advantage targets.

NEVER authorizes orders. Historical forward labels are observed public books, not
predicted profit, executable order previews, or independent OOS validation.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3

NEW_TARGET = Decimal('0.55')
PREVIOUS_TARGET = Decimal('0.98')
ROUND_TRIP_SLIPPAGE_STRESS = Decimal('0.0030')  # 15bps on each of two legs
EXAMPLE_NOTIONALS = (Decimal('25'), Decimal('100'), Decimal('500'))
MAX_OBSERVATIONS = 5000


def _decimal(raw):
    if isinstance(raw, (bool, float)):
        raise ValueError('Float/boolean cannot be verified exact outcome evidence')
    try:
        value = Decimal(str(raw))
    except (TypeError, InvalidOperation, ValueError) as exc:
        raise ValueError('Invalid forward result') from exc
    if not value.is_finite():
        raise ValueError('Nonfinite forward result')
    return value


def compare_observations(rows, notionals=EXAMPLE_NOTIONALS, *, slip=ROUND_TRIP_SLIPPAGE_STRESS):
    """Count hypothetical profitable *observed outcomes*, not trade signals.

    Rows are (pair, timestamp, observed_after_fee_pct, fee_source). The existing
    forward signal stores ask->later bid with entry-time authenticated taker fee.
    The additional slippage stress is separately assumed, not actual execution.
    """
    slip = _decimal(slip)
    if not Decimal(0) <= slip < Decimal('.05'):
        raise ValueError('Slippage stress out of research bounds')
    amounts = tuple(_decimal(x) for x in notionals)
    if not amounts or any(n<=0 for n in amounts):
        raise ValueError('Positive example notionals required')
    checked = 0
    excluded = 0
    events = []
    seen = set()
    for pair, timestamp, pct, source in rows:
        if (pair, timestamp) in seen:
            excluded += 1
            continue
        seen.add((pair, timestamp))
        if source != 'ACCOUNT_TIER_NOT_PAIR_PREVIEW':
            excluded += 1
            continue
        try:
            value = _decimal(pct)
        except ValueError:
            excluded += 1
            continue
        checked += 1
        events.append(value/Decimal(100)-slip)
    comparisons=[]
    for amount in amounts:
        low = sum(amount*p >= NEW_TARGET for p in events)
        old = sum(amount*p >= PREVIOUS_TARGET for p in events)
        comparisons.append({'notional':amount,'observed':checked,'target_055':low,
                            'target_098':old,'extra':low-old})
    return {'compared':checked,'excluded':excluded,'comparisons':comparisons,
            'stress':slip,'targets':(NEW_TARGET,PREVIOUS_TARGET),
            'execution_verified':False,'predictive_edge_verified':False}


def read_forward_evidence(ledger_path, *, cap=MAX_OBSERVATIONS):
    """Only SELECT from a local ledger; never expose private balances/fills."""
    if not isinstance(cap, int) or not 1<=cap<=MAX_OBSERVATIONS:
        raise ValueError('Bounded history size required')
    path = Path(ledger_path)
    if not path.is_file():
        raise FileNotFoundError('Forward research ledger not available')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as connection:
        return connection.execute(
          "SELECT pair,at_utc,observed_return_pct,fee_evidence_source "
          "FROM forward_signals WHERE outcome_state='OBSERVED' "
          "AND observed_return_pct IS NOT NULL "
          "ORDER BY at_utc DESC LIMIT ?", (cap,)).fetchall()


def compare_route_ideas(ideas,*, low=NEW_TARGET,high=PREVIOUS_TARGET):
    """Count route proposals, not fills or statistically independent trades.

    Only fee-screened complete-route USD marks + held-out evidence can qualify.
    Research ideas without OOS are counted as UNVERIFIED, never negative edge.
    """
    total=0; qualified=0; above_low=0; above_high=0; unverified=0
    for idea in ideas or ():
        if not isinstance(idea,dict):continue
        total+=1
        if idea.get('oos_validated') is not True:
            unverified+=1;continue
        try:
            p10=_decimal(idea.get('net_p10_usd'))
            mean=_decimal(idea.get('net_mean_usd'))
        except ValueError:
            unverified+=1;continue
        qualified+=1
        if min(p10,mean)>=low:above_low+=1
        if min(p10,mean)>=high:above_high+=1
    return dict(total=total,heldout_measured=qualified,unverified=unverified,
                above_055=above_low,above_098=above_high,
                new_ideas=above_low-above_high)


def report(ledger_path,app=None):
    lines=[
      'CoinCat v50.6R • $0.55 versus $0.98 FULL-ROUTE USD ADVANTAGE SENSITIVITY',
      'READ ONLY • local public-book forward research only • ZERO Coinbase SDK calls / orders.',
      'Separate preferences: full BUY/SELL/SWITCH route advantage $0.55 by default (editable $0.01-$10,000); ordinary profit-taking SELL $0.55 by default (editable $0.01-$5).',
      'AI Lab BUY/SELL/HOLD sampling continues below either target; targets do NOT censor training.',
      'Existing forward outcomes represent entry ask -> later bid after recorded account-tier taker fees.',
      'Research adds an ASSUMED 15bps slippage per BUY and SELL leg; no order-book depth/market impact proof.',
      'These historical outcomes were not all preselected executable trades, and pairs/time blocks may be correlated.',
      'Normalized example order sizes are NOT your balances, recommended funding, or pilot approvals.',
    ]
    if app is not None:
        try:
            auto=(getattr(app,'last_cycle',None) or {}).get('auto_rotation') or {}
            findings=compare_route_ideas(auto.get('ideas') or ())
            lines.append('Current LIVE-OBSERVED shadow proposals (may reuse source and destination): '+str(findings['total']))
            lines.append('Held-out after-cost FULL-ROUTE scenarios: '+str(findings['heldout_measured'])+'; incomplete/unverified: '+str(findings['unverified']))
            lines.append('At least $0.55 projected advantage='+str(findings['above_055'])+
                         '; at least $0.98='+str(findings['above_098'])+
                         '; incremental RESEARCH ideas='+str(findings['new_ideas']))
            lines.append('No real order fills or independent future net-USD return can be inferred from these counts.')
        except Exception as error:
            # Export only exception CLASS; malformed research rows must not
            # break the entire combined diagnostic or reveal user-private data.
            lines.append('[NOT VERIFIED] Current shadow route sensitivity unavailable ('+type(error).__name__+').')
    try:
        evidence=read_forward_evidence(ledger_path)
        result=compare_observations(evidence)
    except (sqlite3.Error,OSError,ValueError,TypeError) as exc:
        lines.extend(['[NOT VERIFIED] Historical target comparison unavailable ('+type(exc).__name__+').',
                      'No zero-hit rate inferred when evidence is unavailable.'])
    else:
        lines.append(f'Recent bounded eligible observed fee-stamped outcomes: {result["compared"]}; excluded/duplicates: {result["excluded"]}')
        for row in result['comparisons']:
            lines.append(f'EXAMPLE ${row["notional"]:.0f} round trip: observed outcomes clearing $0.55={row["target_055"]}, '
                         f'clearing $0.98={row["target_098"]}, incremental=${row["extra"]} count (NOT executable signals).')
        if not result['compared']:
            lines.append('[NOT VERIFIED] No eligible matured outcomes available for comparison.')
    lines.extend([
      'No verified increase in trade frequency or overall profit can be inferred from changing a threshold.',
      'Historical forward-return comparisons are a different population from full-route BUY/SELL/HOLD decisions; DO NOT combine their counts.',
      'NO independent HOLD-versus-SWITCH alpha, order eligibility, Coinbase preview, portfolio floor, or fee-fill reconciliation granted.',
      'LOSS SAFEGUARDS UNCHANGED • LIVE ALL-PAIR POST BLOCKED • END SENSITIVITY AUDIT'
    ])
    return '\n'.join(lines)+'\n'
