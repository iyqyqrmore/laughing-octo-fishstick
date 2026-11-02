"""Pure research identity/quality/freshness helpers. No execution permission."""
from decimal import Decimal
import math
from coincat_working_allocation import assess_allocation,quantity
from coincat_v6010_registry import REJECT_FLAGS
from coincat_v80_discovery import book_status


def eth_funding(*,balances,balances_at,now,draft=(),excluded=()):
    """Apply the unchanged allocation contract to this ETH-only research slice.

    The original whole-account assessment remains separate; this subset confers
    no authorization or reconciliation and can never permit actual execution.
    """
    wallet={'ETH':balances['ETH']} if 'ETH' in balances else {}
    rows=tuple(r for r in draft if r.asset=='ETH')
    value=assess_allocation(balances=wallet,balances_at=balances_at,now=now,draft=rows,
                            excluded=('ETH',) if 'ETH' in excluded else ())
    row=next(iter(value['rows']),{})
    try:
        key=('ETH_RESEARCH_FUNDING_V1',quantity(wallet.get('ETH',0)),
             tuple(quantity(row.get(k,0)) for k in ('working','manual','protected','excluded','unassigned')),
             value['state']=='INVALID_DRAFT','ETH' in excluded)
    except (ValueError,ArithmeticError):key=('ETH_RESEARCH_FUNDING_V1','INVALID')
    valid=(value['state']!='INVALID_DRAFT' and 'AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED' not in value['blockers']
           and 'ETH' not in excluded and row.get('working',0)>0)
    return dict(assessment=value,key=key,valid=valid,row=row)


def research_identity(config,market,rules,funding):
    """Typed stable fields only: ignore catalog prices/volumes/key ordering."""
    p=rules[market['pair']];base,quote=market['pair'].split('-')
    numeric=[]
    for name in ('base_increment','quote_increment','base_min_size','quote_min_size','base_max_size','quote_max_size'):
        raw=p.get(name)
        numeric.append((name,None if raw in (None,'') else Decimal(str(raw))))
    numeric.append(('price_increment',Decimal(str(p.get('price_increment',p['quote_increment'])))))
    product=(market['pair'],str(p['product_type']).upper(),str(p['status']).lower(),
             p.get('base_currency_id',base),p.get('quote_currency_id',quote),
             tuple((k,p.get(k) is True) for k in REJECT_FLAGS),tuple(numeric))
    controls=tuple(getattr(config,k) for k in ('amount_eth','entry_offset_bps','target_pct',
                    'expiry_hours','scan_interval_s','taker_slippage_bps'))
    return dict(version=1,controls=controls,product=product,funding=funding['key'])


def identity_change(old,new):
    if old is None:return None
    if old==new:return None
    if not isinstance(old,dict) or not isinstance(new,dict):return 'RESEARCH_CONFIGURATION_CHANGED'
    for field,reason in (('funding','ETH_FUNDING_CHANGED'),('controls','RESEARCH_CONFIGURATION_CHANGED'),
                         ('product','SELECTED_PRODUCT_RULES_CHANGED'),('version','IDENTITY_VERSION_CHANGED')):
        if old.get(field)!=new.get(field):return reason
    return None


def quote_reason(raw,now,transport_code=None):
    if raw is not None:
        condition=book_status(raw,now)
        return {'FRESH':None,'UNOBSERVED':'QUOTE_NOT_RETURNED','STALE':'QUOTE_STALE',
                'WIDE':'QUOTE_WIDE','INVALID':'QUOTE_INVALID','FUTURE':'QUOTE_FUTURE'}[condition]
    code=str(transport_code or '')
    if code in ('ConnectionError','CONNECTION_ERROR'):return 'CONNECTION_ERROR'
    if code in ('Timeout','ReadTimeout','ConnectTimeout','SCOUT_DEADLINE','SLOW_OR_LATE_QUOTE'):return 'READ_TIMEOUT'
    if code in ('GET_RATE_BUDGET_DEFERRED','PREVIOUS_GETS_IN_FLIGHT','HTTP_429_RETRY_AFTER'):return 'GET_DEFERRED'
    if code.startswith('HTTP_'):
        try:
            status=int(code.split('_')[1])
            if 400<=status<=599:return 'HTTP_'+str(status)
        except (ValueError,IndexError):pass
    return 'QUOTE_NOT_RETURNED'


def age(stamp,now):
    try:
        value=float(now)-float(stamp)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError,OverflowError):return None


def freshness(result,now,*,fee_ttl=7200):
    scan_age=age(result.get('at'),now);markets=[]
    for row in result.get('rows',()):
        stamp=row.get('quote_observed_at')
        if stamp is None and row.get('quote_age_s') is not None:stamp=result['at']-row['quote_age_s']
        quote_age=age(stamp,now)
        label=('QUOTE_NOT_OBSERVED' if quote_age is None else 'FUTURE_LAST_OBSERVATION' if quote_age<0 else
               'STALE_LAST_OBSERVATION' if quote_age>30 else 'LAST_OBSERVATION_WITHIN_AGE_LIMIT')
        markets.append(dict(pair=row['market']['pair'],quote_observed_at=stamp,
            quote_age_s_at_export=quote_age,quote_age_s_at_last_good_scan=row.get('quote_age_s'),
            freshness_state=label,observation_state=row.get('observation_state','UNOBSERVED'),
            reason_codes=list(row.get('blockers',())),
            setup_entry_at=(row.get('hypothesis') or {}).get('entry_at'),
            original_expiry_at=(row.get('hypothesis') or {}).get('expiry_at'),
            waiting_s_at_export=age((row.get('hypothesis') or {}).get('entry_at'),now),
            expired_at_export=bool(row.get('hypothesis') and now>=row['hypothesis']['expiry_at'])))
    tier=result.get('fee_evidence',{});captured=tier.get('captured_at')
    if captured is None and tier.get('age_s') is not None and result.get('at') is not None:
        captured=result['at']-tier['age_s']
    fee_age=age(captured,now)
    return dict(last_good_scan_at=result.get('at'),last_good_scan_age_s=scan_age,
        display_state='STALE_LAST_OBSERVATION' if scan_age is not None and (scan_age>30 or scan_age<0) else
                      'LAST_GOOD_OBSERVATION' if scan_age is not None else 'UNOBSERVED',
        fee_fresh_at_last_good_scan=bool(tier.get('fresh')),fee_captured_at=captured,
        fee_age_s_at_export=fee_age,fee_valid_at_export=bool(tier.get('fresh')) and fee_age is not None and 0<=fee_age<=fee_ttl,
        products=markets)
