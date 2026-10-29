"""Deterministic passive text advice. Inputs are observations, never callbacks.

No access to scanner decisions, settings writers, funds, clients or execution.
"""
from decimal import Decimal
from coincat_v80_immediate import exact

DEFAULT_NOTE = 'No setting change recommended; actual execution economics are not verified.'


def settings_advice(result, *, scan_interval_s=Decimal(5)):
    """Operational cadence advice only; correlated reviews cannot prove returns."""
    current = exact(scan_interval_s)
    if not Decimal(5) <= current <= Decimal(60):
        raise ValueError('SCAN_INTERVAL_OUT_OF_BOUNDS')
    elapsed = result.get('fetch_ms')
    try:
        latency = Decimal(str(elapsed)) / 1000
        if not latency.is_finite() or latency < 0:
            raise ValueError()
    except (ValueError, TypeError, ArithmeticError):
        latency = None
    if latency is not None and latency > current and current < 60:
        suggested = min(Decimal(60), max(current+1, (latency*2).to_integral_value(rounding='ROUND_CEILING')))
        return (f'PRELIMINARY | Manual control: Scan interval. Current {current} s; '
                f'suggested {suggested} s. Measured latest quote-collection duration: {latency} s '
                '(one pass, not representative execution evidence). A longer interval reduces '
                'request load but can miss short-lived observations. '
                'Manual decision only / no setting changed. Actual execution economics remain unverified.')
    return ('INSUFFICIENT | '+DEFAULT_NOTE+' '
            'Reserve targets remain proposed; earned ETH, settled allocation and sized depth are unknown. '
            'Manual decision only / no setting changed.')
