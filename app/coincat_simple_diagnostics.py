"""Eight current read-only diagnostic sections; no obsolete experiment audits."""
from contextlib import closing
from datetime import datetime,timezone
import sqlite3
import time
from coincat_version import DISPLAY
from coincat_live import TERMINAL
from coincat_working_allocation import allocation_diagnostics
from coincat_eth_evaluator import public_cycle_report


def make_report(app, *, now=None):
    now=time.time() if now is None else now
    scanner=app.scanner
    result=app.last_result or {}
    best=result.get('best')
    eth=getattr(app,'eth_measurement',None) or {}
    reserve=getattr(app,'reserve_calculation',None) or {}
    mixer=getattr(app,'mixer',None)
    proposed={} if mixer is None else {k:str(v) for k,v in mixer.values().items()}
    allocation=getattr(app,'working_allocation',None) or result.get('working_allocation')
    editor=getattr(app,'allocation_editor',None)
    if editor is not None:allocation=editor.assessment()
    working_eth=getattr(app,'working_eth_measurement',None) or {}
    ledger_state='UNAVAILABLE';pending='UNVERIFIED'
    try:
        with closing(sqlite3.connect(app.ledger.path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON');ledger_state=db.execute('PRAGMA quick_check(1)').fetchone()[0]
            pending=db.execute('SELECT COUNT(*) FROM orders WHERE state NOT IN ('+
                ','.join('?'*len(TERMINAL))+')',tuple(TERMINAL)).fetchone()[0]
    except (sqlite3.Error,OSError,AttributeError):pass
    sections=[
        ('CONNECTION',{'connected':app.connected,'running':app.running,'busy':app.busy,
            'account_age_s':None if scanner is None or scanner.account_at is None else now-scanner.account_at,
            'last_error_class':app.last_error}),
        ('POLICY','Greatest positive immediate after-cost USD wallet advantage. Full verified AVAILABLE source; no portfolio caps, no fractional fit search, no dollar profit floor. Exchange product rules, exclusions, freshness and exact receipts apply.'),
        ('COVERAGE',{key:result.get(key,'UNOBSERVED') for key in ('scan','at','eligible_directions',
            'priced_directions','positive_directions','blockers','quote_errors','fetch_ms',
            'coverage_complete','result_scope','book_conditions','coverage_history','quote_scheduling',
            'eth_quote_scheduling','eth_cycle_feasibility','observation_engine')}),
        ('IMMEDIATE RESULT',{'state':result.get('state','UNOBSERVED'),'reason':result.get('reason','UNOBSERVED'),
            'best_advantage_usd':str(best['w']) if best else 'NONE_OBSERVED','live_order_permission':False,
            'eth_measurement':{k:eth.get(k,'UNKNOWN') for k in ('state','reason','scope','at','balances_at',
                'reference_product','quote_span_s','oldest_quote_age_s','allocation_state','evidence','synchronization_state')},
            'reference_eth_usd':str(eth['reference_eth_usd']) if eth.get('reference_eth_usd') is not None else 'UNKNOWN',
            'realized_earned_eth':'UNKNOWN_NOT_INFERRED_FROM_BALANCES',
            'unconverted_asset_count':len(eth['hold']['unconverted_native']) if eth.get('hold') is not None else 'UNKNOWN_NOT_EVALUATED',
            'eth_conversion_blockers':eth.get('conversion_diagnostics',{'state':'UNOBSERVED'}),
            'working_allocation':allocation_diagnostics(allocation) if allocation else 'UNOBSERVED',
            'working_eth_measurement':{k:working_eth.get(k,'UNKNOWN') for k in ('state','reason','scope')},
            'eth_cycle_research':public_cycle_report(result['eth_cycle_research']) if result.get('eth_cycle_research') else 'UNOBSERVED',
            'eth_profit_selection_enabled':False,
            'reserve_preview_state':reserve.get('state','UNOBSERVED'),
            'actual_reserved_eth':'UNKNOWN_NO_EARMARKING',
            'manual_mixer_proposal':proposed,'preference_storage':'RAM_ONLY'}),
        ('COST EVIDENCE',{'account_taker_estimate':str(result['fee_rate']) if result.get('fee_rate') is not None else 'UNKNOWN',
            'slippage_reserve_pct':'0.15 ASSUMED','sized_depth_impact':'UNKNOWN',
            'exchange_event_time':'UNVERIFIED','actual_fees_and_execution_slippage':'NOT_MEASURED'}),
        ('PASSIVE AI LAB',{'counts':dict(scanner.lab.counts) if scanner else {},
            'eth_redenominated_comparisons':dict(scanner.lab.eth_counts) if scanner else {},
            'missed_endpoint_causes':dict(scanner.lab.missed_causes) if scanner else {},
            'research_scheduler':result.get('research_scheduler') or (scanner.lab.diagnostics() if scanner else {}),
            'pending':len(scanner.lab.pending) if scanner else 'UNOBSERVED',
            'report_interval_s':180,'scope':'RAM proposal comparisons; correlated hypothetical outcomes, never fills; no decision, size or settings authority. ETH re-denomination does not create an edge. Passive recommendations are manual decisions only.'}),
        ('LOCAL RECORDS',{'sqlite_integrity':ledger_state,'local_unresolved_orders':pending,
            'note':'No private ledger, lot, tax basis or authorization quantities were modified by the scanner.'}),
        ('EXECUTION','UNAVAILABLE. LiveBroker.submit remains unconditionally blocked. No submitted orders or synthetic wallet posts. Durable order intents, exact fill/fee settlement and ambiguous-outcome restart recovery remain required for actual trading.')]
    lines=[DISPLAY+' — COMPLETE DIAGNOSTICS',
        'Snapshot '+datetime.fromtimestamp(now,timezone.utc).isoformat(),
        'READ ONLY • no account IDs, private balances, funding quantities, keys, raw errors or financial paths',
        'SECTION COMPLETENESS: COMPLETE (8/8)',
        'No Coinbase requests, order calls or financial writes are performed by this export.']
    for title,body in sections:lines.extend(('',title,str(body)))
    return '\n'.join(lines)+'\n'
