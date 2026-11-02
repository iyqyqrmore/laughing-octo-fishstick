"""Eight v95 diagnostic sections. Strict quantity-free projections only."""
from contextlib import closing
from datetime import datetime,timezone
import sqlite3
import time
from coincat_version import DISPLAY
from coincat_live import TERMINAL
from coincat_eth_maker import public_summary
from coincat_working_allocation import allocation_diagnostics


def make_report(app,*,now=None):
    now=time.time() if now is None else now
    scanner=app.scanner;result=app.last_result or {}
    allocation=getattr(app,'working_allocation',None) or result.get('working_allocation')
    editor=getattr(app,'allocation_editor',None)
    if editor is not None:allocation=editor.assessment()
    tier=result.get('fee_evidence',{})
    ledger_state='UNAVAILABLE';pending='UNVERIFIED'
    try:
        with closing(sqlite3.connect(app.ledger.path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            ledger_state=db.execute('PRAGMA quick_check(1)').fetchone()[0]
            pending=db.execute('SELECT COUNT(*) FROM orders WHERE state NOT IN ('+
                ','.join('?'*len(TERMINAL))+')',tuple(TERMINAL)).fetchone()[0]
    except (sqlite3.Error,OSError,AttributeError):pass
    sections=[
        ('CONNECTION',dict(connected=app.connected,running=app.running,busy=app.busy,
            account_age_s=None if scanner is None or scanner.account_at is None else now-scanner.account_at,
            last_error_class=app.last_error)),
        ('POLICY','ETH-only funding and success unit. At most three manually approved direct-ETH companions; '
            'no USD/USDC bridges or automatic market expansion. Independent scenarios use identical ETH versus HOLD; '
            'never sum them as simultaneous deployments. Old USD/cycle libraries are secondary; old experiments do not run in ETH Growth.'),
        ('COVERAGE',dict(scan=result.get('scan','UNOBSERVED'),at=result.get('at','UNOBSERVED'),
            state=result.get('state','UNOBSERVED'),quote_scheduling=result.get('quote_scheduling',{}),
            quote_errors=result.get('quote_errors',{}),fetch_ms=result.get('fetch_ms','UNOBSERVED'),
            price_integrity='BOUNDED_LOCAL_REST_OBSERVATIONS_ONLY',
            limits='30s age / 0.25% spread / 12s per-decision span; entry/exit separated intentionally')),
        ('ETH MAKER RESEARCH',public_summary(result)),
        ('COST EVIDENCE',dict(account_tier={k:str(tier[k]) for k in
            ('state','fresh','maker','taker','age_s','captured_at','source') if k in tier},
            pair_exceptions='NOT VERIFIED',fee_currency='UNVERIFIED_QUOTE_DEBIT_SCENARIO',
            maker='LIMIT_PRICES_WITH_ACCOUNT_MAKER_ESTIMATE; NO_TAKER_SLIPPAGE',
            taker='BID_ASK_PLUS_ACCOUNT_TAKER_ESTIMATE_AND_EXPLICIT_SLIPPAGE_STRESS',
            depth_queue_exchange_event_time='NOT VERIFIED',cost_status='MODELED_ONLY')),
        ('ALLOCATION AND LOCAL RECORDS',dict(
            working_allocation=allocation_diagnostics(allocation) if allocation else 'UNOBSERVED',
            reconciliation='NOT VERIFIED',reserve='PROPOSED_CALCULATOR_ONLY_NO_EARMARKING',
            preferences='RAM_ONLY',sqlite_integrity=ledger_state,local_unresolved_orders=pending,
            financial_mutations='NONE_BY_RESEARCH',earned_eth='NOT_ESTABLISHED')),
        ('PASSIVE RESEARCH',dict(observations=result.get('study_counts',{}),
            guidance='Manual controls only. No AI settings, pricing, funding, ARM or execution authority.',
            fill_evidence='TOUCH_OR_CROSSING_IS_NOT_A_FILL',hypothetical_full_fills=0,
            verified_fills=0,partial_fill_returns='UNVERIFIED_NO_CREDIT',actual_profit='NOT_ESTABLISHED',
            observations_persisted='PUBLIC_QUOTES_ONLY; SETUPS_AND_COUNTS_RAM_ONLY')),
        ('EXECUTION AND ACCEPTANCE',dict(LIVE='BLOCKED_UNCONDITIONALLY',
            broker_settlement_recovery='NOT VERIFIED',Windows_DPAPI='NOT VERIFIED_BY_CLOUD',
            GUI='LOCAL_ACCEPTANCE_REQUIRED',orders_submitted=0,previews_submitted=0,
            no_qualified_evidence='VALID_RESEARCH_OUTCOME',
            note='Source verification and offline tests cannot establish market eligibility, actual fees, fills or profit.'))]
    lines=[DISPLAY+' — ETH GROWTH COMPLETE DIAGNOSTICS',
        'Snapshot '+datetime.fromtimestamp(now,timezone.utc).isoformat(),
        'RESEARCH ONLY • native quantities, receipts, account IDs, keys and private paths omitted',
        'SECTION COMPLETENESS: COMPLETE (8/8)',
        'No network requests, order calls or financial writes are performed by this export.']
    for title,body in sections:lines.extend(('',title,str(body)))
    return '\n'.join(lines)+'\n'
