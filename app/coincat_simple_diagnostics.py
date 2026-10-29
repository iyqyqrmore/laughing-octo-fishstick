"""Eight current read-only diagnostic sections; no obsolete experiment audits."""
from contextlib import closing
from datetime import datetime,timezone
import sqlite3
import time
from coincat_version import DISPLAY
from coincat_live import TERMINAL


def make_report(app, *, now=None):
    now=time.time() if now is None else now
    scanner=app.scanner
    result=app.last_result or {}
    best=result.get('best')
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
        ('COVERAGE',{key:result.get(key,'UNOBSERVED') for key in ('scan','at','eligible_directions','priced_directions','positive_directions','blockers','quote_errors')}),
        ('IMMEDIATE RESULT',{'state':result.get('state','UNOBSERVED'),'reason':result.get('reason','UNOBSERVED'),
            'best_advantage_usd':str(best['w']) if best else 'NONE_OBSERVED','live_order_permission':False}),
        ('COST EVIDENCE',{'account_taker_estimate':str(result['fee_rate']) if result.get('fee_rate') is not None else 'UNKNOWN',
            'slippage_reserve_pct':'0.15 ASSUMED','sized_depth_impact':'UNKNOWN',
            'exchange_event_time':'UNVERIFIED','actual_fees_and_execution_slippage':'NOT_MEASURED'}),
        ('PASSIVE AI LAB',{'counts':dict(scanner.lab.counts) if scanner else {},
            'pending':len(scanner.lab.pending) if scanner else 'UNOBSERVED',
            'report_interval_s':180,'scope':'RAM proposal comparisons; correlated hypothetical outcomes, never fills; no decision or size authority'}),
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
