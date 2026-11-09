"""Manual-client support exports contain controlled states/counts only."""
from coincat_version import DISPLAY
import hashlib
from pathlib import Path

KEYS={'blocked','state','orders','fills','unresolved','completed','canceled','provider','automation','profit'}
STATES={'BLOCKED','READY','RESTING','UNKNOWN_LOCKED','EXPIRED'}

def validate(value):
    if not isinstance(value,dict) or set(value)!=KEYS:raise ValueError('INVALID_MANUAL_PUBLIC_SCHEMA')
    if type(value['blocked']) is not bool or value['state'] not in STATES:raise ValueError('INVALID_MANUAL_PUBLIC_GATE')
    for k in ('orders','fills','unresolved','completed','canceled'):
        if type(value[k]) is not int or not 0<=value[k]<=8192:raise ValueError('INVALID_MANUAL_PUBLIC_COUNT')
    if (value['provider']!='COINBASE_MANUAL_LIMIT_GTC' or value['automation'] is not False or
            value['profit']!='NOT_ASSESSED'):raise ValueError('INVALID_MANUAL_PUBLIC_AUTHORITY')
    if value['completed']+value['canceled']+value['unresolved']>value['orders']:raise ValueError('INVALID_MANUAL_PUBLIC_TOTALS')
    return value

def diagnostic(app):
    from coincat_monitor import capture
    try:manifest_sha=hashlib.sha256((Path(__file__).resolve().parents[1]/'SHA256_MANIFEST.json').read_bytes()).hexdigest()
    except OSError:manifest_sha=None
    snap=capture(app,session='0'*32,sequence=1,manifest_sha256=manifest_sha)
    manual=validate(snap['manual_execution']);history=snap['beta']['manual'];shadow=snap.get('intelligent_shadow')
    lines=[DISPLAY+' Manual Spot / Intelligent 24-hour shadow + independent multi-horizon — redacted diagnostics','SECTION COMPLETENESS: COMPLETE (8/8)',
        '[1/8] Build: INTELLIGENT_ONE_LEG_24H_V1 + MULTI_HORIZON_ONE_LEG_V1 + MANUAL_LIMIT_GTC; no automatic real orders.',
        'Source manifest SHA256: '+str(manifest_sha),
        '[2/8] Manual connection: '+snap['health']['connection_state'],
        '[3/8] Native REST pricebooks / exchange candles. Five USD historical products are read-only forecast references, never order markets.',
        '[4/8] Current manual session: '+manual['state']+'; live block '+('ON' if manual['blocked'] else 'OFF')+
            '; order attempts '+str(manual['orders'])+'; CoinCat fills '+str(manual['fills'])+'; unresolved '+str(manual['unresolved'])+
            '. Deliberate OFF plus manual click retains existing bounded real order permissions.',
        '[5/8] One own commission per filled leg. Authenticated maker rate is an estimate, not settled currency/precision proof. No counterparty fee or compulsory future-exit charge.',
        '[6/8] Imported Coinbase history: '+history['state']+'; orders '+str(history['orders'])+'; filled '+str(history['filled'])+
            '; known native flows '+str(history['known_native_flow'])+'; unresolved settlement '+str(history['unknown'])+'. Read only; not shadow funding.',
        '[7/8] Intelligent 24-hour shadow: '+('UNAVAILABLE' if shadow is None else shadow['state'])]
    if shadow is not None:
        lines.extend(['Selected policy: '+shadow['selected_policy']+'; forecast horizon '+str(shadow['horizon_s'])+' seconds.',
            'Input state '+shadow['data_state']+'; history '+shadow['history_state']+'; aligned hourly observations '+str(shadow['history_observations'])+
            ' / '+str(shadow['history_required'])+'; reference coverage '+str(shadow['history_references'])+' / 5.',
            'Current native market coverage '+str(shadow['market_coverage'])+' / 7; current USD valuation references '+str(shadow['valuation_coverage'])+' / 5.',
            'Valid monitoring seconds '+str(shadow['valid_seconds'])+' / 604800; restarts '+str(shadow['restart_count'])+'.',
            'Reviews '+str(shadow['reviews'])+'; directional checks '+str(shadow['direction_checks'])+'; qualified '+str(shadow['qualified_checks'])+
            '; rejected '+str(shadow['rejected_checks'])+'; deduplicated episodes '+str(shadow['opportunity_episodes'])+'.',
            'Order state '+shadow['order_state']+'; conditional orders '+str(shadow['orders'])+'; fill events '+str(shadow['fill_events'])+
            '; model '+str(shadow['modeled_fills'])+' / replay '+str(shadow['replay_fills'])+'; partials '+str(shadow['partials'])+
            '; nonfills '+str(shadow['nonfills'])+'; canceled '+str(shadow['canceled'])+'; replacements '+str(shadow['replacements'])+
            '; active '+str(shadow['active_orders'])+'; unresolved '+str(shadow['unresolved_orders'])+'.',
            'Forecast '+shadow['forecast_validation']+'; chronological validation predictions '+str(shadow['validation_predictions'])+
            '; holdout predictions '+str(shadow['holdout_predictions'])+'; forward predictions '+str(shadow['forward_predictions'])+
            ' / known '+str(shadow['forward_known'])+' / unknown '+str(shadow['forward_unknown'])+'.',
            'Execution '+shadow['execution_calibration']+'; evidence '+shadow['execution_evidence']+'; automatic real authority NONE; profit NOT_ESTABLISHED.',
            'Rejections: repeated direction checks / first blockers, not rejected exchange orders.'])
        for category,n in shadow['rejection_breakdown']['categories'].items():lines.append('  '+category+': '+str(n))
        lines.append('Fixed rejection reason codes:')
        for reason,n in shadow['rejection_breakdown']['reasons'].items():
            if n:lines.append('  '+reason+': '+str(n))
    multi=snap.get('multihorizon_shadow')
    if multi is not None:
        lines.extend(['Independent multi-horizon shadow: '+multi['state']+'; '+multi['selected_policy']+'; '+multi['data_state']+' inputs.',
            'Valid monitoring seconds '+str(multi['valid_seconds'])+' / 604800; restarts '+str(multi['restart_count'])+'; directional checks '+str(multi['direction_checks'])+
            '; qualified '+str(multi['qualified_checks'])+'; rejected '+str(multi['rejected_checks'])+'.',
            'Orders '+str(multi['orders'])+'; fill events '+str(multi['fill_events'])+'; partials '+str(multi['partials'])+'; nonfills '+str(multi['nonfills'])+
            '; canceled '+str(multi['canceled'])+'; replacements '+str(multi['replacements'])+'; unresolved '+str(multi['unresolved_orders'])+'.',
            'Selection '+multi['selection_validation']+'; execution '+multi['execution_calibration']+'; automatic real authority NONE.',
            'Order already active reviews '+str(multi['order_active_reviews'])+'; unresolved execution events '+str(multi['unknown_events_blocking'])+'.',
            'Live comparisons '+multi['comparison']+'; original baselines and periods are not silently aligned.'])
        for name,row in multi['horizons'].items():
            lines.append('  '+name+' '+row['state']+' '+row['reason']+'; checks '+str(row['checks'])+'; qualified '+str(row['qualified'])+'; rejected '+str(row['rejected'])+
                '; selected orders '+str(row['selected_orders'])+'; validation / holdout '+str(row['validation_predictions'])+' / '+str(row['holdout_predictions'])+
                '; forward known / unknown '+str(row['forward_known'])+' / '+str(row['forward_unknown'])+'.')
            lines.append('    Horizon rejection categories: '+', '.join(k+'='+str(n) for k,n in row['rejections']['categories'].items()))
        lines.append('Multi-horizon aggregate rejection categories: '+', '.join(k+'='+str(n) for k,n in multi['rejection_breakdown']['categories'].items()))
    backfill=snap.get('history_backfill')
    if backfill is not None:
        lines.extend(['Historical collector '+backfill['state']+'; '+backfill['reason']+'; jobs '+str(backfill['attempts'])+'; failed jobs '+str(backfill['failures'])+' this app run.',
            'Seconds since last successful historical page: '+str(backfill['last_success_age_s'])+'. Bar counts are not portfolio amounts.'])
        for gran,row in backfill['granularities'].items():
            lines.append('  '+gran+' '+row['state']+'; aligned bars '+str(row['aligned'])+' / '+str(row['required'])+'.')
            lines.append('    Reference bars / saved pages: '+', '.join(p+'='+str(r['bars'])+'/'+str(r['pages']) for p,r in row['products'].items()))
    lines.extend(['[8/8] Storage: separate v1.05 24h and multi-horizon trials; existing v1.05 and v1.04 identities, records and HOLD benchmarks preserved. No tray/custom minimize behavior; Close exits safely.',
        'Native Windows, connected endpoints and calibrated fill/forecast evidence remain local acceptance work.',
        'No portfolio amounts, prices, quantities, native commissions, policy values, private paths, account/order IDs, wallet contents or raw receipts are exported.'])
    return '\n'.join(lines)+'\n'
