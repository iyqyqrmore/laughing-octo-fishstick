"""Independent, chronologically validated ETH/BTC relative forecasts."""

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from statistics import median

from .money import D, ONE, ZERO, native_math

CADENCE = 300
LOOKBACK = 3600
HISTORY_DAYS = 730
HORIZONS = (300, 900, 1800, 7200, 86400)
NAMES = {0: "Immediate", 300: "5 min", 900: "15 min", 1800: "30 min", 7200: "120 min", 86400: "24 hours"}
MIN_TRAIN = 60
MIN_VALIDATION = 100
# Two directions across five horizon targets, each allocated 1% from 10%.
TAIL = D(".01")


@dataclass(frozen=True)
class Forecast:
    horizon: int
    regime: int
    estimate: D
    lower: D
    upper: D
    validation_count: int
    validation_mae: D
    anchor: D | None = None

    @native_math
    def shift(self, side):
        return self.lower if side == "BUY" else self.upper


@native_math
def regime(prices, at):
    past, now = prices.get(at - LOOKBACK), prices.get(at)
    if past is None or now is None:
        return None
    return 1 if now >= past else -1


@native_math
def fit(prices, through):
    """Price keys identify closes. Training targets end before validation begins."""
    times = sorted(at for at in prices if through - HISTORY_DAYS * 86400 <= at <= through)
    if not times:
        return {}
    split = times[0] + (through - times[0]) * 2 // 3
    models = {}
    for horizon in HORIZONS:
        train, validate = defaultdict(list), defaultdict(list)
        next_train = next_validation = times[0]
        for at in times:
            if at + horizon > through or at + horizon not in prices:
                continue
            feature = regime(prices, at)
            if feature is None:
                continue
            outcome = prices[at + horizon] / prices[at] - ONE
            if at + horizon <= split and at >= next_train:
                train[feature].append(outcome)
                next_train = at + horizon
            elif at >= split and at >= next_validation:
                validate[feature].append(outcome)
                next_validation = at + horizon
        for feature in (-1, 1):
            training, evidence = train[feature], validate[feature]
            if len(training) < MIN_TRAIN or len(evidence) < MIN_VALIDATION:
                continue
            estimate = median(training)
            errors = sorted(outcome - estimate for outcome in evidence)
            mae = sum(map(abs, errors), ZERO) / len(errors)
            if mae >= sum(map(abs, evidence), ZERO) / len(evidence):
                continue
            tail_index = max(0, int(TAIL * (len(errors) + 1)) - 1)
            models[horizon, feature] = Forecast(
                horizon,
                feature,
                estimate,
                max(-ONE, estimate + errors[tail_index]),
                estimate + errors[-tail_index - 1],
                len(errors),
                mae,
            )
    return models


def at_time(prices, at, models):
    feature = regime(prices, at)
    return tuple(replace(models[h, feature], anchor=prices[at]) for h in HORIZONS if (h, feature) in models)


def accuracy(rows):
    counts, errors, covered = Counter(), Counter(), Counter()
    for horizon, estimate, lower, upper, realized in rows:
        counts[horizon] += 1
        errors[horizon] += abs(estimate - realized)
        covered[horizon] += lower <= realized <= upper
    return {
        NAMES[h]: {"outcomes": n, "mae": errors[h] / n, "interval_coverage": D(covered[h]) / n}
        for h, n in counts.items()
    }
