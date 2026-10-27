"""CoinCat v30 fail-closed live pilot preflight.

Never calls Coinbase submit/preview functions. Research-only crypto/crypto
rotation is explicitly NOT cleared by this preflight. The broker independently
validates permissions, account quantities, order state and all risk limits.
"""
from __future__ import annotations
import math

# A fresh process must first observe a meaningful window of real research.
# Time alone is NOT evidence of profitability or predictive power.
MIN_OBSERVATION_SECONDS = 30 * 60
MAX_SCAN_AGE_SECONDS = 180
MAX_BALANCE_AGE_SECONDS = 300
MAX_CATALOG_AGE_SECONDS = 7200


def _recent(value, max_age):
    try:
        number = float(value)
        return math.isfinite(number) and 0 <= number <= max_age
    except (ValueError, TypeError, OverflowError):
        return False


def assess_readiness(*, broker, catalog, catalog_age_s, balance_age_s,
                     scan_age_s, observed_runtime_s, external_mismatches=(),
                     storage_ok=True, valuation_complete=None, valuation_age_s=None):
    """Checks exchange-dependent data freshness and local state, no side effects.

    NOT permission to submit cross-quoted/multi-leg orders. ARM confirmation,
    live permission check and per-order broker validation stay mandatory.
    """
    blockers=[]
    if broker is None:
        blockers.append('No authenticated Coinbase broker connection')
    if not catalog or not _recent(catalog_age_s,MAX_CATALOG_AGE_SECONDS):
        blockers.append('Coinbase spot catalog missing or older than two hours')
    if not _recent(balance_age_s,MAX_BALANCE_AGE_SECONDS):
        blockers.append('Coinbase available balances unverified or older than five minutes')
    if not _recent(scan_age_s,MAX_SCAN_AGE_SECONDS):
        blockers.append('AI Lab has no fresh completed REST bid/ask scan (three-minute limit)')
    try:
        run=float(observed_runtime_s)
        if not math.isfinite(run) or run < MIN_OBSERVATION_SECONDS:
            blockers.append('DISARMED research warm-up less than 30 minutes in current session')
    except (ValueError,TypeError,OverflowError):
        blockers.append('Research warm-up duration unavailable')
    if external_mismatches:
        blockers.append('Enrolled holdings exceed Coinbase verified available balances')
    if not storage_ok:
        blockers.append('Financial/research storage safeguard tripped')
    # The portfolio-value objective cannot be judged from a known partial
    # total. Keep legacy tests/backends API-compatible via optional inputs;
    # the actual v30.2 UI always supplies these two current observations.
    if valuation_complete is False:
        blockers.append('Current available Coinbase portfolio USD valuation is incomplete')
    if valuation_age_s is not None and not _recent(valuation_age_s, MAX_BALANCE_AGE_SECONDS):
        blockers.append('Portfolio market pricebooks unverified or older than five minutes')
    if broker is not None:
        ledger=getattr(broker,'ledger',None)
        if ledger is None:blockers.append('Broker has no verified financial ledger')
        else:
            if ledger.setting('halted','0')=='1':blockers.append('Emergency STOP remains latched')
            if ledger.pending():blockers.append('Unreconciled/uncertain Coinbase order')
            if not any(x.get('enabled',1) and float(x.get('remaining_qty','0'))>0
                       for x in ledger.assets()):
                blockers.append('No enabled, authorized, liquid funding assets')
    return {'ready':not blockers,'blockers':blockers,'live_scope':'ALL_SPOT_READ_ONLY_UNTIL_PRODUCTION_CERTIFICATION',
            'cross_crypto_ready':False, 'research_runtime_s':observed_runtime_s}


def format_readiness(result):
    if result['ready']:
        return ('DATA HEALTH PASS • all-spot research/previews only; LIVE POST NOT CERTIFIED • not a profit forecast')
    return ('PREFLIGHT NOT READY • '+ '; '.join(result['blockers'][:4])+
            ('; plus further blockers' if len(result['blockers'])>4 else ''))
