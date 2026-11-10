"""Fixed M2 design, committed before backtests; no fitted/live parameters here."""
from decimal import Decimal as D
from itertools import product

MAKER = D("0.005")
TAKER = D("0.009")
FEE_STRESS = D(2)
CAPITAL_USD = D(200)  # Simulated capital only; no live allocation.
TRAIN_DAYS, TEST_DAYS = 60, 30
SOURCE_FRACTION = D("0.5")
ENTRY_MINUTES = 10
MAX_SPREAD = D("0.001")
ENTRY_SIDE = "BTC_MID_WEIGHT_TOTAL_ETH_BTC_ONLY_CYCLE_START_TIE_BUY"
ROUNDTRIPS = ("ROUNDTRIP", "ROUNDTRIP_ALTERNATING")
ALTERNATING_SIDE = "FIRST_BUY_FLIP_AFTER_COMPLETED_CYCLE_ONLY"
ALTERNATING_PARAMETERS = "SAME_TRAINING_SELECTION_AS_ROUNDTRIP_NO_SEPARATE_SEARCH"
STRATEGIES = ("HOLD50", "BAND", "RATIO", *ROUNDTRIPS)
BANDS = tuple(map(D, ("0.03", "0.05", "0.08")))  # absolute weight percentage points
ZSCORES = tuple(map(D, ("1.5", "2.0", "2.5")))
MARGINS = tuple(map(D, ("0.002", "0.003", "0.005")))
REPRICE_TICKS = (1, 3, 5)
MAX_HOLD_DAYS = (None, 1, 3)


def grid(name):
    if name == "HOLD50": return [{}]
    if name == "BAND": return [dict(band=x) for x in BANDS]
    if name == "RATIO": return [dict(k=x) for x in ZSCORES]
    if name in ROUNDTRIPS:
        return [dict(profit_margin=m, reprice_ticks=n, max_hold_days=h) for m,n,h in product(MARGINS,REPRICE_TICKS,MAX_HOLD_DAYS)]
    raise ValueError("Unknown registered strategy")


def verdict(wins, windows, advantage, stressed_advantage):
    return "GO" if windows and wins*5 >= windows*3 and advantage > 0 and stressed_advantage >= 0 else "NO-GO"
