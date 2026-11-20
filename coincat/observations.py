"""Collect synchronized closed observations and track prospective forecast outcomes."""

import time

from .forecast import CADENCE, HORIZONS, HISTORY_DAYS, at_time, fit
from .history import checked_bar, read_bars, relatives
from .market import BASE, QUOTE, PRODUCTS, MarketUnavailable
from .money import D, ONE, native_math


class Observations:
    def __init__(self, directory):
        self.prices = {}
        self.models = {}
        self.bucket = 0
        self.fitted = 0
        self.status = "No imported five-minute history"
        self.directory = directory
        self.revisions = None

    def import_history(self):
        try:
            revisions = tuple(
                (self.directory / f"{product}_5m.csv").stat().st_mtime_ns for product in PRODUCTS
            )
            if revisions != self.revisions:
                prices = relatives(read_bars(self.directory))
                self.prices.update({at: price for at, price in prices.items() if at not in self.prices})
                self.revisions = revisions
                self.fitted = 0
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, ArithmeticError):
            self.status = "Local candle history needs review"

    @native_math
    def obtain(self, client, store, now):
        bucket = int(now) // CADENCE * CADENCE
        if self.bucket == bucket:
            return self.supported(now)
        if not self.bucket:
            with store.transaction() as sql:
                for row in sql.execute(
                    "SELECT * FROM forecast_closes WHERE at>=?", (bucket - (HISTORY_DAYS + 1) * 86400,)
                ):
                    self.prices[row["at"]] = D(row["relative"])
        self.bucket = bucket
        self.import_history()
        observed = {}
        try:
            end = bucket
            start = end - 6 * CADENCE
            series = {}
            for product in PRODUCTS:
                rows = (
                    checked_bar(raw, CADENCE)
                    for raw in client.candle_page(product, start, end, "FIVE_MINUTE")
                )
                closes = {}
                for at, _, _, _, close, _ in rows:
                    if start <= at < end:
                        at += CADENCE
                        if at in closes and closes[at] != D(close):
                            raise ValueError("Conflicting recent bars")
                        closes[at] = D(close)
                series[product] = closes
            for close in set.intersection(*(set(values) for values in series.values())):
                relative = series[f"{BASE}-USD"][close] / series[f"{QUOTE}-USD"][close]
                observed[close] = self.prices.setdefault(close, relative)
        except (MarketUnavailable, KeyError, TypeError, ValueError, ArithmeticError):
            if not self.prices or max(self.prices) < bucket - CADENCE:
                self.status = "Five-minute evidence unavailable"
        if not self.prices:
            return ()
        at = max(self.prices)
        if not self.fitted or at - self.fitted >= 3600:
            cutoff = at - (HISTORY_DAYS + 1) * 86400
            self.prices = {stamp: price for stamp, price in self.prices.items() if stamp >= cutoff}
            self.models = fit(self.prices, at - CADENCE)
            self.fitted = at
        forecasts = self.supported(time.time())
        self.status = f"{len(forecasts)}/{len(HORIZONS)} forecast horizons supported"
        with store.transaction() as sql:
            sql.executemany(
                "INSERT OR IGNORE INTO forecast_closes VALUES (?,?)",
                ((close, str(relative)) for close, relative in observed.items()),
            )
            if not sql.execute("SELECT 1 FROM state").fetchone():
                return forecasts
            for row in sql.execute("SELECT * FROM forecasts WHERE status IN ('PENDING','MISSING')"):
                target = row["made"] + row["horizon"]
                if target in self.prices:
                    outcome = self.prices[target] / D(row["relative"]) - ONE
                    sql.execute(
                        "UPDATE forecasts SET realized=?,status='OBSERVED' WHERE made=? AND horizon=?",
                        (str(outcome), row["made"], row["horizon"]),
                    )
                elif target < bucket - CADENCE and row["status"] == "PENDING":
                    sql.execute(
                        "UPDATE forecasts SET status='MISSING' WHERE made=? AND horizon=?",
                        (row["made"], row["horizon"]),
                    )
            for forecast in forecasts:
                sql.execute(
                    """INSERT OR IGNORE INTO forecasts(made,horizon,relative,expected,low,high)
                    VALUES (?,?,?,?,?,?)""",
                    (
                        at,
                        forecast.horizon,
                        str(self.prices[at]),
                        str(forecast.estimate),
                        str(forecast.lower),
                        str(forecast.upper),
                    ),
                )
        return forecasts

    def supported(self, now):
        if not self.prices:
            return ()
        at = max(self.prices)
        if not 0 <= now - at < CADENCE + 60:
            return ()
        return tuple(item for item in at_time(self.prices, at, self.models) if at + item.horizon > now)
