"""Eight v95 diagnostic sections. Strict quantity-free projections only."""
from contextlib import closing
from datetime import datetime,timezone
import sqlite3
import time
from coincat_version import DISPLAY
from coincat_live import TERMINAL
from coincat_eth_maker import public_summary
from coincat_working_allocation import allocation_diagnostics
from coincat_continuity import freshness,age


def make_report(app,*,now=None):
    now=time.time() if now is None else now
    scanner=app.scanner;result=app.last_result or {}
    allocation=getattr(app,'working_allocation',None) or result.get('working_allocation')
    editor=getattr(app,'allocation_editor',None)
    if editor is not None:allocation=editor.assessment()
    tier=result.get('fee_evidence',{})
    recovery=getattr(app,'recovery',None)
    connection=(recovery.diagnostics() if recovery else dict(connection_state=
        'PAUSED_NEEDS_ATTENTION' if app.last_error else 'RUNNING' if app.running else 'STOPPED'))
    view=freshness(result,now,fee_ttl=getattr(getattr(app,'fees',None),'ttl',7200))
    account_at=None if scanner is None else scanner.account_at
    account_age=age(account_at,now)
    authenticated_fresh=account_age is not None and 0<=account_age<=120 and app.last_error is None
    current_products=[]
    for row in view['products']:
        item=dict(row)
        item['state_at_export']=('SETUP_EXPIRED' if row['expired_at_export'] else 'SETUP_ACTIVE_UNPRICED'
            if connection['connection_state'] in ('RETRYING','PAUSED_NEEDS_ATTENTION') or row['freshness_state']!='LAST_OBSERVATION_WITHIN_AGE_LIMIT'
            else row['observation_state'])
        current_products.append(item)
    ledger_state='UNAVAILABLE';pending='UNVERIFIED'
    try:
        with closing(sqlite3.connect(app.ledger.path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            ledger_state=db.execute('PRAGMA quick_check(1)').fetchone()[0]
            pending=db.execute('SELECT COUNT(*) FROM orders WHERE state NOT IN ('+
                ','.join('?'*len(TERMINAL))+')',tuple(TERMINAL)).fetchone()[0]
    except (sqlite3.Error,OSError,AttributeError):pass
    sections=[
        ('CONNECTION',dict(connected=bool(app.connected and authenticated_fresh and connection['connection_state']!='RETRYING'),
            running=app.running,busy=app.busy,account_age_s=account_age,
            local_monitor=app.monitor.diagnostics() if hasattr(app,'monitor') else 'UNOBSERVED',
            last_error_class=app.last_error,**connection,
            last_good_scan_at=view['last_good_scan_at'],last_good_scan_age_s=view['last_good_scan_age_s'],
            last_successful_account_refresh_at=getattr(scanner,'last_successful_account_refresh_at',account_at))),
        ('POLICY','ETH-only funding and success unit. Four possible direct ETH companions in the seven-market approved scope; '
            'no USD/USDC bridges or automatic market expansion. Independent scenarios use identical ETH versus HOLD; '
            'never sum them as simultaneous deployments. BTC cross-pairs are observations awaiting usable inventory; no independent BTC budget is invented. '
            'Old USD/cycle libraries remain secondary; no cycle strategy is enabled.'),
        ('COVERAGE',dict(scan=result.get('scan','UNOBSERVED'),at=result.get('at','UNOBSERVED'),
            chart_history=app.chart.diagnostics() if hasattr(app,'chart') else 'UNOBSERVED',
            observation_freshness_at_export=view['display_state'],products_at_export=current_products,
            watch_scope=[dict(pair=r['pair'],mode=r['mode'],deferred=r['deferred'],reason=r['reason'])
                for r in result.get('watched_markets',())],
            state=result.get('state','UNOBSERVED'),quote_scheduling=result.get('quote_scheduling',{}),
            quote_errors=result.get('quote_errors',{}),fetch_ms=result.get('fetch_ms','UNOBSERVED'),
            price_integrity='BOUNDED_LOCAL_REST_OBSERVATIONS_ONLY',
            limits='30s age / 0.25% spread / 12s per-decision span; entry/exit separated intentionally')),
        ('ETH MAKER RESEARCH',public_summary(result)),
        ('COST EVIDENCE',dict(account_tier_at_last_good_scan={k:str(tier[k]) for k in
            ('state','fresh','maker','taker','age_s','captured_at','source') if k in tier},
            fee_fresh_at_last_good_scan=view['fee_fresh_at_last_good_scan'],
            fee_valid_at_export=view['fee_valid_at_export'],fee_age_s_at_export=view['fee_age_s_at_export'],
            pair_exceptions='NOT VERIFIED',fee_currency='UNVERIFIED_QUOTE_DEBIT_SCENARIO',
            maker='LIMIT_PRICES_WITH_ACCOUNT_MAKER_ESTIMATE; NO_TAKER_SLIPPAGE',
            taker='BID_ASK_PLUS_ACCOUNT_TAKER_ESTIMATE_AND_EXPLICIT_SLIPPAGE_STRESS',
            depth_queue_exchange_event_time='NOT VERIFIED',cost_status='MODELED_ONLY')),
        ('ALLOCATION AND LOCAL RECORDS',dict(
            working_allocation=allocation_diagnostics(allocation) if allocation else 'UNOBSERVED',
            portfolio_reference=dict(basis='WATCHED_BASKET_MIDPOINT_BEFORE_EXIT_FEES',flow_adjusted=False,
                trading_profit='UNVERIFIED',
                baseline_observed=getattr(getattr(app,'portfolio_view',None),'baseline_at',None) is not None,
                basket_priced=getattr(app,'portfolio_result',{}).get('watched_value_eth') is not None,
                outside_asset_count=len(getattr(app,'portfolio_result',{}).get('outside_assets',())),
                unpriced_asset_count=len(getattr(app,'portfolio_result',{}).get('missing_assets',()))),
            reconciliation='NOT VERIFIED',reserve='PROPOSED_CALCULATOR_ONLY_NO_EARMARKING',
            preferences='RAM_ONLY',sqlite_integrity=ledger_state,local_unresolved_orders=pending,
            financial_mutations='NONE_BY_RESEARCH',earned_eth='NOT_ESTABLISHED')),
        ('PASSIVE RESEARCH',dict(observations=result.get('study_counts',{}),
            current_continuity=scanner.maker_study.diagnostics() if scanner is not None else 'UNOBSERVED',
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
