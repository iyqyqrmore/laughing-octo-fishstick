"""On-demand strictly offline predictive/safeguards verification for CoinCat v50.6R.

No API, live order, ARM, writable account ledger, or training mutation.
It replays *disposable* mock exchange events and honestly distinguishes production
NOT VERIFIED from isolated test PASS. A passing mock must never unlock POST.
"""
from __future__ import annotations
from decimal import Decimal
from coincat_v506_reconciliation import integrated_12_order_rehearsal
from coincat_v506_coinbase_evidence import evidence_rehearsal
from coincat_v506_capital import capital_rehearsal
from coincat_v502_relative_learning import evaluate_hold_switch
from coincat_v503_lab_evidence import capture_app_lab


def synthetic_predictive_cases():
    # Pure deterministic historical/heldout *contract* for no-censor learning.
    # The route USD post-conversion mark incorporates both route legs, including
    # modeled account-tier fees and explicit slippage/spread costs.
    evidence=dict(state='OBSERVED_WINDOWS_READY_NOT_PREDICTIVE', n=42,
                  oos_validated=True,mean_relative_return='.012',
                  p10_relative_return='.012')
    base=dict(initial_wallet_usd_mark='100',post_route_wallet_usd_mark='99.5',
              source_units='1',input_units_planned='1')
    good=evaluate_hold_switch(base,evidence,'0.55')
    stringent=evaluate_hold_switch(base,evidence,'0.98')
    lower=evaluate_hold_switch(base,evidence,'0.85')
    fake=dict(evidence,oos_validated=False)
    unverified=evaluate_hold_switch(base,fake,'0.55')
    assert good['net_p10_usd']==Decimal('.70') and good['research_decision']=='SWITCH_WORTH_RESEARCH'
    assert stringent['research_decision']=='HOLD_PREFERRED'
    assert lower['research_decision']=='HOLD_PREFERRED'
    assert unverified['research_decision']=='HOLD_UNTIL_VERIFIED'
    assert unverified['minimum_satisfied'] is True  # threshold met but prediction not validated
    # Unknown evidence and malformed preference cannot qualify.
    unknown=evaluate_hold_switch(base,{'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0},'0.55')
    invalid=evaluate_hold_switch(base,evidence,'NaN')
    assert unknown['research_decision']!='SWITCH_WORTH_RESEARCH'
    assert invalid['research_decision']!='SWITCH_WORTH_RESEARCH'
    return {'predictive_cases':6,'good_net_usd':good['net_p10_usd'],
            'autotrade_permission':False}


def report(app=None):
    """Single source for the temporary UI test button and combined export."""
    lines=['CoinCat v50.6R • OFFLINE PREDICTIVE ADVANTAGE + EXECUTION SAFEGUARDS',
      'No Coinbase SDK/API/POST, no ARM, no real financial writes. All tests use FAKE evidence or READ-ONLY local snapshots.',
      'This test cannot certify predictive superiority, Coinbase fee currency, journal migration or safe live trading.']
    try:
        x=synthetic_predictive_cases()
        lines.append('[PASS / SYNTHETIC ONLY] BUY/SELL/HOLD full-route cost-adjusted USD advantage: '+str(x['predictive_cases'])+' test scenarios; $0.70 passes $0.55 but fails $0.98')
        lines.append('[PASS / SYNTHETIC ONLY] Missing held-out evidence, invalid target and inferior route all fail closed')
    except Exception as exc:
        lines.append('[BLOCKED] Predictive screening contract: '+type(exc).__name__)
    try:
        x=integrated_12_order_rehearsal()
        if int(x['fake_orders']) != 12 or int(x['fake_split_fills']) != 24 or int(x['duplicate_post_claim_refusals']) != 12:
            raise ValueError('Unexpected incomplete rehearsal')
        lines.append('[PASS / SYNTHETIC ONLY] Atomic disposable FIFO + durable journal: 12 orders; 24 fills; duplicate POST claims, restart, rollback tests')
    except Exception as exc:
        lines.append('[BLOCKED] Unified isolated settlement/recovery: '+type(exc).__name__)
    try:
        x=evidence_rehearsal()
        lines.append('[PASS / FAKE SDK ONLY] Paginated evidence reader: '+str(x['mock_pages'])+' pages; '+str(x['mock_fills'])+' fake fills; no live orders')
    except Exception as exc:
        lines.append('[BLOCKED] Offline exchange evidence adapter: '+type(exc).__name__)
    try:
        capital_rehearsal()
        lines.append('[PASS / SYNTHETIC ONLY] Protected reserve/quarterly manual approval; broker caps and ARM unchanged')
    except Exception as exc:
        lines.append('[BLOCKED] Capital reserve exercise: '+type(exc).__name__)
    if app is not None:
        try:
            research=capture_app_lab(app)
            lines += [
                'Current AI target (full rotation) USD: '+str(research.get('minimum_net_advantage_usd')),
                'Current time-separated qualifying routes: '+str(research.get('positive_after_cost_routes')),
                'Research preferred $/order: '+str(research.get('research_preferred_order_usd')),
                'Verified independent positive predictive USD edge in current session: '+
                ('NOT VERIFIED' if not research.get('budget_eligible') else 'RESEARCH ONLY; NOT PRODUCTION CERTIFIED')]
        except Exception as exc:
            lines.append('[NOT VERIFIED] Current local lab evidence could not be read: '+type(exc).__name__)
        error=getattr(app,'_last_ui_callback_error_type',None)
        lines.append('Last UI callback error: '+(str(error) if error else 'none recorded'))
        lines.append('Callback source: '+str(getattr(app,'_last_ui_callback_error_origin','NOT AVAILABLE')))
        if error == 'FileNotFoundError':
            lines.append('[BLOCKED] Missing-file UI callback root cause requires REDACTED local traceback; not solved by synthetic execution tests')
    lines += [
      '[NOT VERIFIED / LIVE] Real Coinbase fee currencies, partial fills, maker/taker rates by actual fill and order history paging',
      '[NOT VERIFIED / LIVE] Durable ambiguous POST / multi-leg execution and canonical financial FIFO migration',
      '[BLOCKED / PRODUCTION] Independent fail-closed portfolio-wide USD loss floor',
      '[BLOCKED / PRODUCTION] Whole-enrolled-portfolio USD return versus frozen no-trade HOLD benchmark',
      '[BLOCKED / PRODUCTION] Fully autonomous 12-real-order pilot; every order POST intentionally disabled',
      'NO RISK ACKNOWLEDGEMENT OR GOOD OFFLINE SCORE REMOVES ANY PRODUCTION BLOCKER',
      'END v50.6R OFFLINE GATES']
    return '\n'.join(lines)+'\n'
