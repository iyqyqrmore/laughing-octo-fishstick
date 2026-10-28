"""Single, shareable v50.6 diagnostics: health + AI Lab + Trader + Shadow.

Observation-only: no Coinbase requests, order/arm/stop calls or DB writes.
Existing report generators remain internal building blocks, not GUI actions.
All account-identifying material and funding quantities are excluded by them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import sqlite3
import time
from pathlib import Path

from coincat_diagnostics import make_report
from coincat_shadow_diagnostics import make_shadow_report
from coincat_v607_strategy_research import report as strategy_research_report
from coincat_v608_outcomes import diagnostics as v608_decision_diagnostics
from coincat_v40_1_safety import live_data_health
from coincat_version import DISPLAY
from coincat_v705_worker import worker_state
from coincat_go_live_readiness import readiness_report
from coincat_v50_final_verification import final_verification_report
from coincat_v502_microstructure import microstructure_report
from coincat_v502_legacy_parity import parity_report
from coincat_v502_order_intents import recovery_rehearsal
from coincat_v503_lab_evidence import capture_app_lab, diagnostic_text
from coincat_v603_research_audit import report as research_db_report
from coincat_v506_readiness import report as v506_capital_report
from coincat_v506_gate_verifier import report as v506_gate_report
from coincat_v507_shadow_arm import shadow_report as v507_shadow_report, experimental_shadow_report
from coincat_v506_profit_sensitivity import report as profit_sensitivity_report
from coincat_snowball import report as snowball_report


def _age(now, last):
    """Return unknown rather than incorrectly reporting a zero/healthy age."""
    try:
        value = float(last)
        return max(0, now - value) if value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _show_age(value):
    return 'unavailable' if value is None else f'{int(value)}s'


def _ledger_status(path):
    """Independently verify that current order-state counts are queryable.

    Avoid conflating a locked/missing SQLite database with a healthy 0 count.
    Never connect using the ordinary production sql() context (it can write).
    """
    try:
        path = Path(path)
        if not path.is_file():
            return 'UNAVAILABLE: financial database missing; counts are NOT verified'
        uri = path.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            conn.execute('PRAGMA query_only=ON')
            nonterminal = conn.execute("""SELECT COUNT(*) FROM orders
                WHERE state NOT IN ('FILLED','COMPLETED','REJECTED','CANCELLED','EXPIRED','FAILED')""").fetchone()[0]
            orphan = conn.execute('''SELECT COUNT(*) FROM fills f
                LEFT JOIN orders o ON o.cid=f.cid WHERE o.cid IS NULL''').fetchone()[0]
        if nonterminal or orphan:
            return f'REVIEW: unresolved order rows={nonterminal}; unmatched fill rows={orphan} (counts only)'
        return 'QUERY PASS: no unresolved order rows or unmatched fill rows (local DB only)'
    except (sqlite3.Error, OSError):
        return 'UNAVAILABLE: SQLite read could not be completed; do NOT interpret missing counts as zero'


def diagnostic_led_ready(app, wall=None, mono=None):
    """Non-mutating LED status; RED never disables the diagnostic export."""
    wall=time.time() if wall is None else float(wall)
    mono=time.monotonic() if mono is None else float(mono)
    health=live_data_health(
        connected=bool(getattr(app,'broker',None)),
        catalog_age_s=_age(wall,getattr(app,'catalog_at',0)),
        portfolio_age_s=_age(mono,getattr(app,'_last_portfolio_sync_monotonic',0)),
        scan_age_s=_age(mono,getattr(app,'_last_scan_at',0)),
        valuation_age_s=_age(wall,getattr(app,'_portfolio_quote_at',0)),
        poll_age_s=_age(mono,getattr(app,'_last_poll_heartbeat',0)),
        tick_age_s=_age(mono,getattr(app,'_last_tick_heartbeat',0)),
        history_in_progress=getattr(app,'_history_in_progress',False),
        scan_processing=getattr(app,'_scan_processing',False),
        portfolio_sync_running=getattr(app,'_portfolio_sync_running',False),
    )
    return bool(health['ready'] and not getattr(app,'worker_busy',False)
                and not getattr(app,'_connection_in_progress',False)
                and getattr(app,'_portfolio_coverage',{}).get('complete',False)
                and not getattr(app,'_fill_sync_faulted',False))


def _health_summary(app, wall, mono):
    worker=worker_state(app,mono=mono,wall=wall)
    catalog_age = _age(wall, getattr(app, 'catalog_at', 0))
    portfolio_age = _age(mono, getattr(app, '_last_portfolio_sync_monotonic', 0))
    scan_age = _age(mono, getattr(app, '_last_scan_at', 0))
    valuation_age = _age(wall, getattr(app, '_portfolio_quote_at', 0))
    poll_age = _age(mono, getattr(app, '_last_poll_heartbeat', 0))
    tick_age = _age(mono, getattr(app, '_last_tick_heartbeat', 0))
    broker = getattr(app, 'broker', None)
    health = live_data_health(
        connected=bool(broker), catalog_age_s=catalog_age, portfolio_age_s=portfolio_age,
        scan_age_s=scan_age, valuation_age_s=valuation_age,
        poll_age_s=poll_age, tick_age_s=tick_age,
        history_in_progress=getattr(app, '_history_in_progress', False),
        scan_processing=getattr(app, '_scan_processing', False),
        portfolio_sync_running=getattr(app, '_portfolio_sync_running', False),
    )
    lines = [
        'RUNTIME HEALTH / IMPORTANT BLOCKERS (independently computed)',
        'Broad authenticated-data health: ' + ('PASS (observation only)' if health['ready'] else 'BLOCKED / INCOMPLETE')+
            ' — independent of urgent public-REST research below',
        'Broker connection: ' + ('CONNECTED object present' if broker else 'NOT CONNECTED'),
        'Real-order ARM: ' + ('ARMED — review risk immediately' if broker and getattr(broker,'armed',False) else 'DISARMED'),
        'Catalog age / max 7200s: ' + _show_age(catalog_age),
        'Balances age / max 300s: ' + _show_age(portfolio_age),
        'Broad REST completed scan age / max 180s: ' + _show_age(scan_age),
        'Authenticated USD pricebooks age / max 300s: ' + _show_age(valuation_age),
        'UI poll callback age / max 15s: ' + _show_age(poll_age),
        'UI research timer age / max 15s: ' + _show_age(tick_age),
        'Worker busy: ' + str(bool(getattr(app, 'worker_busy', False))),
        'GPU automatic observe-only research: ' + (
            'ACTIVE' if getattr(getattr(app,'_gpu_schedule',None),'active',False) else 'IDLE')+
            '; sessions='+str(getattr(getattr(app,'_gpu_schedule',None),'runs','unavailable'))+
            '; last error class='+str(getattr(getattr(app,'_gpu_schedule',None),'last_error_type',None) or 'none'),
        'GPU forward training outcome: '+str((getattr(app,'_gpu_last_forward_report',{}) or {}).get('status','NOT_RUN'))+
            '; observed labels='+str((getattr(app,'_gpu_last_forward_report',{}) or {}).get('labeled','unknown'))+
            '; required='+str((getattr(app,'_gpu_last_forward_report',{}) or {}).get('required','varies by temporal validation'))+
            '; reason='+str((getattr(app,'_gpu_last_forward_report',{}) or {}).get('message','await first completed GPU cycle'))[:240],
        'Validated SHADOW stop/pause reason (session only): '+str(getattr(app,'_shadow_stop_reason','UNKNOWN')),
        'Most recent sleep/resume research gap: ' + (_show_age(getattr(app,'_research_resume_gap_s',0)) if getattr(app,'_research_resume_gap_s',0)>120 else 'none observed') + ' • skipped quotes are NOT reconstructed',
        'Research scan processing: ' + str(bool(getattr(app,'_scan_processing',False))),
        'History catch-up processing: ' + str(bool(getattr(app,'_history_in_progress',False))),
        'Portfolio refresh processing: ' + str(bool(getattr(app,'_portfolio_sync_running',False))),
        'Current research scan elapsed: ' + _show_age(worker['elapsed_s'] if worker['scan_active'] else None),
        'Actual serial worker operation: '+str(worker['operation'] or 'IDLE')+
            '; elapsed='+_show_age(worker['elapsed_s'] if worker['busy'] else None),
        'Actual broad-scan phase: '+str(worker['phase'] or 'NOT RUNNING')+
            '; phase elapsed='+_show_age(worker['phase_elapsed_s'] if worker['scan_active'] else None),
        'Broad phase timings (seconds, completed phases): '+str(dict(getattr(app,'_scan_phase_timings',{}))),
        'Latest bounded broad quote pass: '+str((getattr(app,'last_cycle',{}) or {}).get('scan_network',{})),
        'Current history job elapsed: ' + _show_age(_age(mono, getattr(app,'_history_started_at',0)) if getattr(app,'_history_in_progress',False) else None),
        'Last UI callback error type: ' + (str(getattr(app,'_last_ui_callback_error_type','none') or 'none')),
        'UI callback origin (no paths): ' + str(getattr(app,'_last_ui_callback_error_origin','unavailable')),
        ('FileNotFoundError root cause: NOT VERIFIED; safe code-location breadcrumb below' if getattr(app,'_last_ui_callback_error_type',None)=='FileNotFoundError' else 'No missing-file callback error reported'),
        'Safe callback code location (no paths, exception text, account data): '+str(getattr(app,'_last_ui_callback_breadcrumb','NOT_CAPTURED')),
    ]
    for issue in health['blockers']:
        # Each item comes from the fixed enum list in live_data_health.
        lines.append('  FRESHNESS BLOCKER: ' + issue)
    if scan_age is not None and scan_age > 180 and poll_age is not None and poll_age <= 15:
        lines.append('  DIAGNOSTIC CLUE: GUI poll is running but broad REST scan is stale; urgent research has a separate timestamp below.')
    if scan_age is not None and scan_age > 180 and tick_age is not None and tick_age > 15:
        lines.append('  DIAGNOSTIC CLUE: research callback and REST scan both stale; check UI timer failures.')
    if not broker:
        lines.append('  DISCONNECTED IS NOT A SCHEDULER FAILURE: fresh authenticated observations may not yet be available.')
    lines.append('Production ledger reconciliation: ' + _ledger_status(app.ledger.path))
    lines.extend([
        'FAST SNOWBALL: urgent checks before background research, same serial worker/planner; READ ONLY.',
        'Last completed urgent decision age: '+_show_age(_age(wall,getattr(app,'_fast_observed_at',0)))+
            ' (successful pricing/planning; no order or execution proof)',
        'Latest urgent attempt age: '+_show_age(_age(wall,(getattr(app,'_fast_last_result',{}) or {}).get('captured_at',0))),
        'Urgent approved/fundable scope counts: '+str((getattr(app,'_fast_last_result',{}) or {}).get('scope',{})),
        'Urgent listed funding routes / waiting for next quote batch: '+str((getattr(app,'_fast_last_result',{}) or {}).get('funding_routes',{})),
        'Common Snowball panel source: '+str((getattr(app,'_snowball_summary',{}) or {}).get('event_source','UNKNOWN'))+
            '; age='+_show_age(_age(wall,(getattr(app,'_snowball_summary',{}) or {}).get('observed_at',0))),
        'Fast research loop count: '+str(getattr(app,'_fast_runs',0))+
          '; aggregate='+str(getattr(app,'_fast_totals',{})),
        'Fast latest decision funnel (research counts, not orders): '+str(
          (getattr(app,'_fast_last_result',{}) or {}).get('funnel',{})),
        'Fast request and planner timing (ms): '+str({k:(getattr(app,'_fast_last_result',{}) or {}).get(k)
            for k in ('alert_age_ms','queue_delay_ms','fetch_ms','request_latency_ms','planner_ms')}),
        'Fast event latency percentiles (ms, completed events only): '+str(getattr(app,'_fast_latency_summary',{})),
        'Fast latest cost-selection summary: '+str((getattr(app,'_fast_last_result',{}) or {}).get('selection',{'state':'NOT_OBSERVED'})),
        'Fast passive learning update (counts only): '+str((getattr(app,'_fast_last_result',{}) or {}).get('passive_selection',{'state':'NOT_OBSERVED'})),
        'Fast mark coverage: '+str((getattr(app,'_fast_last_result',{}) or {}).get('mark_coverage',{})),
        'Fast GET failures: '+str((getattr(app,'_fast_last_result',{}) or {}).get('get_errors',{})),
        'Fast quote provenance: public REST best bid/ask; LOCAL REQUEST START age; exchange time/depth NOT VERIFIED.',
        'Fast most recent state: '+str((getattr(app,'_fast_last_result',{}) or {}).get('reason','WAIT'))[:60],
        'Fast path cannot clear production approval gates; FIFO/recovery/loss floor/actual order previews remain NOT CERTIFIED.',
    ])
    lines.append('Multi-currency production fill settlement: BLOCKED / NOT IMPLEMENTED')
    lines.append('Performance and candidate rankings are not forecasts; no report authorizes live trading.')
    return '\n'.join(lines)


class _CompositeReport:
    """Retain good subreports while propagating partial collection status."""
    def __init__(self,text,complete):
        self.text=text;self.complete=complete


def _section(name, generate):
    """Keep generating other sections if a single read fails, without exporting exception details."""
    try:
        result = generate()
        complete=True
        if isinstance(result,_CompositeReport):
            complete=result.complete;result=result.text
        if not isinstance(result, str) or not result.strip():
            raise ValueError('empty report')
        return f'\n{"="*76}\n{name}\n{"="*76}\n{result.rstrip()}\n', complete
    except Exception as exc:
        # Export only the class and vetted code metadata, never exception
        # strings, full tracebacks, private paths or local variables.
        kind=type(exc).__name__
        from coincat_v6011_observation import safe_callback_breadcrumb
        return (f'\n{"="*76}\n{name}\n{"="*76}\n'
                'SECTION UNAVAILABLE: '+kind+'. This export is INCOMPLETE. '
                'No balances, paths, or exception message included. '
                'Inspect local redacted logs; do not infer zero orders or healthy data.\n'
                'Safe code location: '+safe_callback_breadcrumb(exc)+'\n'), False


def _diagnostic_storage_snapshot(root):
    """Retry one transient disappearing-file read; never substitute zero usage.

    SQLite WAL/SHM files can vanish between is_file() and stat() while the
    collector keeps running. This changes diagnostic collection only; the
    shared storage functions and trading/storage gates remain untouched.
    """
    from coincat_storage import storage_health
    try:return storage_health(root)
    except FileNotFoundError:return storage_health(root)


def _shadow_section(app,wall):
    """One of the existing 18 sections, with independent read-only subreports."""
    cycle=getattr(app,'last_cycle',None) or {}
    if not isinstance(cycle,dict):cycle={}
    parts=(
        ('ROUTE RESEARCH',lambda:make_shadow_report(app,now=wall)),
        ('SNOWBALL IMMEDIATE COMPARISON',lambda:snowball_report(getattr(app,'_snowball_summary',{}))),
        ('EXPERIMENTAL SHADOW RESULTS',lambda:experimental_shadow_report(app,include_learning=False)),
        ('PASSIVE FORWARD-COST LEARNING',lambda:_selection_learning_report(app)),
        ('STRATEGY OBSERVATIONS',lambda:strategy_research_report(cycle.get('strategy_research'))),
        ('DECISION & STORAGE SNAPSHOT',lambda:v608_decision_diagnostics(
            cycle.get('strategy_research'),
            cycle.get('shadow_rotation') if getattr(getattr(app,'shadow_pilot',None),'armed',False) else cycle.get('auto_rotation'),
            cycle.get('strategy_horizons'),_diagnostic_storage_snapshot(app.ledger.path.parent))),
    )
    fragments=[];complete=True
    for title,generate in parts:
        fragment,ok=_section(title,generate)
        fragments.append(fragment);complete=complete and ok
    return _CompositeReport(''.join(fragments),complete)


def _selection_learning_report(app):
    learner=getattr(getattr(app,'forward',None),'selection',None)
    summary=learner.summary() if learner is not None else {'state':'NO_FORWARD_OBSERVATIONS'}
    return ('PASSIVE PUBLIC FORWARD-COST OBSERVATIONS\n'
        'Independent of ARM; no wallet quantities or modeled conversions.\n'+str(summary))


def _v601_baseline_audit(app):
    """Read-only current baseline and tax provenance; no raw holdings or bases."""
    from datetime import datetime,timezone
    try:
        ledger=Path(app.ledger.path)
        if not ledger.is_file():return 'NOT VERIFIED: private financial ledger missing; no baseline or zero balances inferred'
        with closing(sqlite3.connect(ledger.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as con:
            table=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v601_performance_periods'").fetchone()
            if table:
                period=con.execute('SELECT period_id,captured_at_utc FROM v601_performance_periods ORDER BY period_id DESC LIMIT 1').fetchone()
            else:period=None
            legacy=con.execute("SELECT COUNT(*) FROM enrollment WHERE enabled=1 AND basis_source='USER_REPORTED_ORIGINAL'").fetchone()[0]
            historical=con.execute("SELECT COUNT(*) FROM inventory_lots WHERE source='PERSONAL_OPENING' AND tax_unit_quote IS NOT NULL").fetchone()[0]
            purchased=con.execute("SELECT COUNT(*) FROM inventory_lots WHERE source='COINBASE_CONFIRMED_BUY'").fetchone()[0]
        detail=('NOT CAPTURED: use the explicit current-USD performance snapshot button after fresh verified prices'
                if not period else 'CAPTURED: '+datetime.fromtimestamp(period[1],timezone.utc).strftime('%Y-%m-%d %H:%M UTC')+
                ' (NOT historical taxable purchase cost)')
        return ('V60.1 PERFORMANCE START & TAX-LOT SAFETY • READ ONLY\n'
            'Frozen enrolled portfolio USD performance baseline: '+detail+'\n'
            f'Older user-entered purchase costs awaiting documentary review: {legacy}; '
            f'personal opening tax lots with historical entries: {historical}.\n'
            f'Existing individually confirmed local acquisition lot rows: {purchased}; Coinbase account parity NOT independently verified.\n'
            'All old cost values are PRESERVED, not reset to market price or certified as tax basis.\n'
            'Future verified buys create new exact acquisition lots; disposals preserve closed history.\n'
            'No exchange POST, actual tax-basis rewriting, or ledger mutation by this report.')
    except (sqlite3.Error,OSError,TypeError,ValueError):
        return 'NOT VERIFIED: unable to read current baseline/tax provenance; real orders blocked'


def _recovery_section():
    checks=recovery_rehearsal(12)
    return ('CoinCat v50.5 • 12 isolated order journal reopen/duplicate tests • NO SDK/POST\n'
            + '\n'.join(f'{key}: {value}' for key,value in checks.items())
            + '\n[BLOCKED] Actual exchange/production journal not integrated or certified.\n')


def _relative_section(app,now):
    """Public USD research only; no portfolio holdings or funding source names."""
    from coincat_v502_relative_learning import MIN_WINDOWS,MIN_SPAN_S
    lab=getattr(app,'relative_lab',None)
    if lab is None:return 'NO RELATIVE USD RESEARCH LAB • functionality missing'
    stats=lab.public_stats(now)
    auto=(getattr(app,'last_cycle',{}) or {}).get('auto_rotation') or {}
    checked=int(auto.get('route_attempts',0))
    cycle=getattr(app,'last_cycle',{}) or {}
    forward=cycle.get('forward_windows') or {}
    focus=cycle.get('adaptive_focus') or {}
    promote=cycle.get('focused_discovery') or {}
    scout=cycle.get('discovery') or {}
    ideas=auto.get('ideas') or []
    lines=[
        'CoinCat v50.5 — AI LAB + AUTO TRADER USD HOLD / SWITCH HANDOFF',
        'LOCAL PUBLIC BOOK MARKS; NO Coinbase request, wallet holdings, API secrets or orders.',
        'Synchronized 60-minute USD asset observations, nonoverlapping paired windows.',
        'V60.4 EVENT-DRIVEN SCOUT / FOCUSED RESEARCH / FORWARD WINDOWS (NO BUY PERMISSION)',
        f'Adaptive deep-study slots: {focus.get("focus_capacity","unknown")} (bounded 48–128);'
        f' total scout promoted: {len(promote.get("promoted",[]))};'
        f' newly urgent: {len(promote.get("urgent_added",[]))}',
        f'Research scheduler note: {focus.get("reason","no completed adaptive capacity decision")}',
        f'RISING-PRIORITY SCOUT: rising REST candidates={promote.get("rising_scouts",0)};'
        f' falling REST candidates retained={promote.get("falling_scouts",0)};'
        f' rising promoted={promote.get("rising_promoted",0)};'
        ' scout only, not predictive or executable',
        f'Ranked destination shortlist: {(cycle.get("exploratory_market_research") or {}).get("ranked",0)}'
        f' / capacity {(cycle.get("exploratory_market_research") or {}).get("shortlist_capacity",0)};'
        f' rising first={(cycle.get("exploratory_market_research") or {}).get("rising_prioritized",0)};'
        ' existing unified planner + COST/ROUTE/HOLD gates unchanged',
        f'Full-catalog rotating REST discovery: {scout.get("sampled",0)} sampled;'
        f' stream-triggered REST scout: {scout.get("stream_alerts_rest",0)};'
        f' available event scout budget: {scout.get("stream_alert_budget",0)}',
        'Do NOT mistake public ticker subscription requests for fresh authenticated bid/ask coverage.',
        f'Pair-level forward outcome status: {forward.get("state","NOT YET MEASURED")};'
        f' price-marked pairs: {forward.get("pair_count",0)};'
        ' canonical existing market_quotes database ONLY; no duplicate research store.',
        f'Persistent public USD mark rows: {stats["rows"]}; distinct assets: {stats["assets"]}',
    ]
    for horizon in (60,180,300,900,3600):
        item=(forward.get('horizons') or {}).get(horizon) or {}
        lines.append(f'  Observed future pair-price window {horizon//60}m:'
            f' matched={item.get("matured",0)}; positive after assumed costs={item.get("positive",0)};'
            f' missing a timely later mark={item.get("missing_future",0)};'
            f' average_pct={item.get("mean_net_pct", "unavailable")}')
    lines += [
        'These are historical pair-level BUY ask / later SELL bid counterfactuals vs cash, NOT'
        ' independent portfolio USD-over-HOLD validation, fills, predictions, or order authority.',
        f'BUY-qualified source/target route-size checks: {checked}',
        f'Prequalification exploratory source/target route-size checks: {auto.get("exploratory_route_attempts",0)}',
        f'Exploratory read-only ideas (NOT BUY or FIFO fills): {auto.get("exploratory_shortlist",0)}',
        f'Portfolio strict-price funding eligibility: {auto.get("funding_assets",0)} eligible assets; {auto.get("funding_unpriceable",0)} excluded from route research',
        f'Route ideas exported (max 12): {len(ideas)}',
        'V60.12 PLAIN-ENGLISH BLOCKER DISPLAY (presentation only; raw codes below unchanged):',
        'History X% = minimum of paired 1h window count /35 and observed span /7 days; 100% is data maturity, NEVER prediction accuracy or approval.',
        'Small = confirmed Coinbase minimum exceeds approved quote-side funding; market study retained, redundant broker review skipped.',
        'Costs X% = immediate after-cost simulated wallet mark drag, rounded UP to 0.1%; not actual fill fee, not a future-return forecast.',
        'Hold = keep current inventory; S.Ready Y/N = candidate delivered to armed SHADOW observer or not, NOT a simulated fill.',
        f'Known-small direct BUY candidates withheld from broker review this scan: {len(cycle.get("minimum_prefiltered") or ())}',
        f'Formerly active unlisted/restricted market pairs excluded from live research pending authenticated recheck (this app session): {len(getattr(app,"_inactive_market_pairs",set()))}',
        'Coinbase Recheck excluded pairs button issues authenticated catalog refresh only; never invents unlisted crypto conversion pairs, changes permissions, or erases historical market evidence.',
        'Missing USD valuation means fresh FX books absent or invalid, NOT necessarily a missing direct pair. Suppress trade qualification until priced; do not permanently blacklist.',

        f'HOLD favored evidence labels: {auto.get("hold_preferred",0)}',
        f'SWITCH worth further research: {auto.get("switch_worth_research",0)}',
        f'Insufficient USD relative-evidence route labels: {auto.get("forward_unverified",0)}',
        f'Chronological OOS validation passed routes: {sum(idea.get("oos_validated") is True for idea in ideas)}',
        'OOS method: nonoverlapping hourly USD marks, chronological 75/25 train/test with one-window embargo; compare train-only forecast to future HOLD=0 baseline.',
        f'Required maturity: {MIN_WINDOWS} independent hour windows spanning {MIN_SPAN_S//86400} days.',
        'HOLD-vs-SWITCH comparison accounts for capped source quantity, residual source, immediate fee/slippage drag and historical relative USD returns.',
        'P&L/TAX: independent dated performance baseline and tax acquisition lots are unaffected by read-only opportunity research.',
        'A positive historical after-cost comparison without a positive held-out result cannot recommend SWITCH; at most WAIT/HOLD.',
        '[NOT VERIFIED] Past relative USD returns do not prove next-period predictive advantage. HOLD is safe research default.',
        '[BLOCKED] Full spot-pair live order POST: unified durable production FIFO and recovery not certified.',
        'END HOLD/SWITCH RESEARCH DIAGNOSTICS']
    return '\n'.join(lines)+'\n'

def _daily_loss_resume_section(app, wall):
    """Risk status from read-only local ledger; no USD holdings or amounts exposed."""
    from coincat_daily_risk import loss_decision,LossEvidenceUnavailable,reversible_rehearsal
    broker=getattr(app,'broker',None)
    rehearsal=reversible_rehearsal()
    lines=[
        'CoinCat v50.5 -- DAILY REALIZED-LOSS BUY PAUSE / RESUME',
        'Read-only verification on local ledger; disposable fake-data pause/resume rehearsal.',
        f'Synthetic pause -> later SELL -> eligible BUY: {"PASS" if rehearsal["synthetic_pause"] and rehearsal["synthetic_resume"] else "FAIL"}',
        'Coinbase requests: ZERO; live orders: ZERO; real financial writes: ZERO',
        'Loss cap configurable $0.01 to $10,000.00; $5.00 default; larger caps require separately typed approval.',
        'Confirmed SELL results are recomputed for each BUY decision. BUY pause auto-lifts when',
        '  verified cumulative UTC-day realized USD P&L is strictly above NEGATIVE authorized limit.',
        'A profitable SELL is not enough unless the day-wide total crosses the threshold.',
        'Emergency STOP, explicit DISARM, unresolved orders, account/FX uncertainty, position',
        '  ceilings, per-order/day caps, and portfolio-wide loss protection are NOT bypassed.',
        'No automatic ARM; resumption means BUY eligibility under THIS daily rule only.',
    ]
    if not broker:
        lines.append('Current daily-rule status: UNKNOWN, broker disconnected')
    else:
        try:
            detail=loss_decision(app.ledger.path,broker.daily_realized_loss_limit_usd,wall)
            label=('BUY ELIGIBLE UNDER DAILY RULE ONLY' if detail['new_buys_allowed']
                   else 'BUY PAUSED UNDER DAILY RULE')
            lines.append('Current daily-rule status: '+label)
            lines.append('Confirmed UTC-day SELL fill count: '+str(detail['sell_fills']))
        except (LossEvidenceUnavailable,ValueError,AttributeError):
            lines.append('Current daily-rule status: NOT VERIFIED -- new BUY must be blocked')
    lines.append('ALL-SPOT LIVE POST REMAINS DISABLED -- production settlement/recovery not certified')
    return '\n'.join(lines)+'\n'

def _complete_sections(app,wall,clock):
    """Read-only, synchronous per-section generators; no Coinbase calls."""
    sections = (
        ('SETTLEMENT & RECOVERY — FINAL VERIFICATION EVIDENCE', lambda: final_verification_report(app)),
        ('GO-LIVE APPROVAL GATES', lambda: readiness_report(app,wall=wall,mono=clock)),
        ('AI LAB RESEARCH DATABASE AND SINGLE-PLANNER AUDIT', lambda: research_db_report(app.ledger.path.parent)),
        ('DAILY REALIZED-LOSS PAUSE / AUTO-RESUME', lambda: _daily_loss_resume_section(app,wall)),
        ('HEALTH & DATA FRESHNESS', lambda: _health_summary(app,wall,clock)),
        ('AI LAB', lambda: make_report(app,'AI_Lab',now=wall)),
        ('AUTO TRADER', lambda: make_report(app,'Auto_Trader',now=wall)),
        ('SHADOW ROTATION & SIMULATED ROUTES', lambda: _shadow_section(app,wall)),
        ('USD HOLD VS SWITCH FORWARD LEARNING', lambda: _relative_section(app,wall)),
        ('AI LAB HELD-OUT VALIDATION & BUDGET EVIDENCE', lambda: diagnostic_text(capture_app_lab(app,wall))),
        ('FEE EVIDENCE & AI COST LEARNING', lambda: app.fee_learning.report(getattr(app,'catalog',()),now=wall)),
        ('PERSONAL-PC COST AND EXECUTION FEASIBILITY', lambda: microstructure_report(app)),
        ('PRODUCTION LOT READ-ONLY MIGRATION PARITY', lambda: parity_report(app.ledger.path)),
        ('V60.1 PERFORMANCE START & TAX LOT PROVENANCE', lambda: _v601_baseline_audit(app)),
        ('LEGACY V50.6 RESERVE REHEARSAL (NOT ACTIVE FUNDING) / JOURNAL + FIFO EVIDENCE', lambda: v506_capital_report(app)),
        ('V50.6R NET PROFIT TARGET SENSITIVITY', lambda: profit_sensitivity_report(app.ledger.path,app=app)),
        ('V50.6R PREDICTIVE EDGE + EXECUTION SAFEGUARDS OFFLINE TEST', lambda: v506_gate_report(app)),
        ('V50.7 ARM SHADOW + SEGREGATED FIFO ACCOUNTING', lambda: v507_shadow_report(app)),
    )
    return sections


def _finish_complete_report(wall, sections_count, fragments, failed, *,elapsed_s=None):
    stamp = datetime.fromtimestamp(wall,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    head = [
        f'{DISPLAY} — COMPLETE DIAGNOSTICS',
        f'Captured {stamp} (start timestamp; sections gathered sequentially)',
        'ONE FILE • OFFLINE / READ ONLY • NO COINBASE REQUESTS OR ORDER SUBMISSIONS',
        'GO-LIVE VERDICT: NOT APPROVED — unverified multi-currency production settlement and recovery.',
        'Private balances, funding source quantities, cost basis, API keys and order IDs are not deliberately included.',
        'Before sharing, review this report for sensitive data; derived public trading pairs may be shown.',
        'This report is neither a profit forecast nor go-live authorization.',
        'SECTION COMPLETENESS: ' + (f'COMPLETE ({sections_count}/{sections_count})' if not failed else 'INCOMPLETE — '+', '.join(failed)),
        'All-spot LIVE submission DISABLED. Previous dollar-quoted fill journal retained only for historical reconciliation; no dollar-only live fast lane.',
        'ACTIVE v60.10 RESEARCH: all authenticated eligible SPOT products, one exchange order per funded conversion; USD/USDC may be traded directly when held and eligible; USD value remains the profit measure.',
        'V60.17 FULL-FUEL RESEARCH: no optional-profit or 10% BUY withholding; modeled taker fee/slippage remain inside actual input-coin spend, within verified enrolled available balance, product rules and order-size checks. LIVE protections unchanged.',
        'LEGACY v50-v60.9 sections below retain historical two-leg research/recovery evidence, NOT active route-selection policy.',
        'New available spot assets may locally auto-enroll under user authorization; original externally purchased tax basis remains UNKNOWN; past lots preserved.',
        '-'*76,
    ]
    if elapsed_s is not None:
        head.append('Diagnostic collection duration: '+f'{float(elapsed_s):.1f}s; live freshness ages within sections may differ.')
    return '\n'.join(head) + '\n' + ''.join(fragments) + '\nEND OF COMPLETE REPORT\n'


class CompleteReportSession:
    """Chunk GUI report work between Tk events; never use Tk widgets from threads.

    A session does one bounded section per GUI after() event. No broker orders,
    background helpers, or source-ledger writes. Caller must check shutdown.
    """
    def __init__(self,app,now=None,mono=None):
        self.wall=int(time.time() if now is None else now)
        self.mono=time.monotonic() if mono is None else mono
        self.sections=_complete_sections(app,self.wall,self.mono)
        self.index=0
        self.fragments=[]
        self.failed=[]
        self.started=time.monotonic()

    def step(self):
        if self.index>=len(self.sections):return False
        title,func=self.sections[self.index]
        result,ok=_section(title,func)
        self.fragments.append(result)
        if not ok:self.failed.append(title)
        self.index+=1
        return self.index<len(self.sections)

    def finish(self):
        if self.index!=len(self.sections):raise RuntimeError('Incomplete collection')
        return _finish_complete_report(self.wall,len(self.sections),self.fragments,self.failed,
                  elapsed_s=time.monotonic()-self.started)


def make_complete_report(app, now=None, mono=None):
    """Synchronous offline test/API entrypoint; GUI uses chunked session."""
    session=CompleteReportSession(app,now=now,mono=mono)
    while session.step():pass
    return session.finish()

