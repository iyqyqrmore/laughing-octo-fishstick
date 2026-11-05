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
    manual=validate(snap['manual_execution'])
    history=snap['beta']['manual']
    lines=[DISPLAY+' Manual Spot — redacted diagnostics','SECTION COMPLETENESS: COMPLETE (8/8)',
        '[1/8] Build: MANUAL_SPOT + RESUMABLE_SHADOW_V1_04; authenticated manual LIMIT GTC; no automatic live orders.',
        'Source manifest SHA256: '+str(manifest_sha),
        '[2/8] Connection: '+snap['health']['connection_state'],
        '[3/8] Quotes: REST pricebooks; exchange trade candles; displayed snapshots are not fills.',
        '[4/8] CoinCat current session: '+manual['state']+'; live block '+('ON' if manual['blocked'] else 'OFF')+
            '; order attempts '+str(manual['orders'])+'; CoinCat fills '+str(manual['fills'])+'; unresolved '+str(manual['unresolved']),
        '[5/8] Fees: authenticated maker/taker estimates; preview does not prove realized fee units.',
        '[6/8] Imported Coinbase history: '+history['state']+'; orders '+str(history['orders'])+
            '; filled '+str(history['filled'])+'; partials '+str(history['partials'])+
            '; canceled unfilled '+str(history['canceled_unfilled'])+
            '; known native flows (API or CSV) '+str(history['known_native_flow'])+
            '; unresolved settlement '+str(history['unknown'])+'. Read-only; account reconciliation UNKNOWN.',
        '[7/8] Resumable shadow trial: '+snap.get('shadow_trial',{}).get('state','OFF')+
            '; valid seconds '+str(snap.get('shadow_trial',{}).get('valid_seconds',0))+
            ' / 604800; restarts '+str(snap.get('shadow_trial',{}).get('restart_count',0))+
            '; full-market coverage '+str(snap.get('shadow_trial',{}).get('coverage_percent',0))+
            '%. Risk-adjusted portfolio USD vs original HOLD; forecast UNVALIDATED; automatic live authority NONE.',
        '[8/8] Storage: separate manual identity journal; private financial records preserved.',
        'Connected acceptance and native Windows verification must be run locally.',
        'No amounts, prices, limits, private paths, account IDs, order IDs or raw API responses are exported.']
    return '\n'.join(lines)+'\n'
