"""Compare held-out shadow policies on matched historical Coinbase candles."""

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
import argparse
import json

from coincat.forecast import CADENCE, accuracy, at_time, fit
from coincat.history import read_bars, relatives
from coincat.market import Book, Frame, Rules, BASE, QUOTE
from coincat.money import D, ZERO, conversion, decimal, maker_commission, native_math, snap, value
from coincat.shadow import CHILD_SECONDS, TRADE_PARTICIPATION, TRADE_THROUGH_TICKS
from coincat.strategy import Candidate, candidate, evaluate, strongest
from .preregistered import STRATEGIES, grid
from .simulator import Simulator

BASELINE = D(".005")
SCENARIOS = (
    ("Observed 0.50% research baseline", BASELINE, TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Hypothetical 0.40%", D(".004"), TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Hypothetical 0.25%", D(".0025"), TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Hypothetical 0.15%", D(".0015"), TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Hypothetical 0.10%", D(".001"), TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Doubled fee 1.00%", D(".01"), TRADE_THROUGH_TICKS, TRADE_PARTICIPATION),
    ("Adverse execution 0.50%", BASELINE, 3, D(".001")),
)


def legacy_rules(rules):
    return {
        key: getattr(rules, attr)
        for key, attr in (
            ("base_increment", "base_step"),
            ("quote_increment", "quote_step"),
            ("price_increment", "price_step"),
            ("base_min_size", "base_min"),
            ("quote_min_size", "quote_min"),
            ("base_max_size", "base_max"),
            ("quote_max_size", "quote_max"),
        )
    }


def marks(row):
    return {BASE: row["eth_usd"], QUOTE: row["btc_usd"]}


def frame_for(row, rules):
    tick = rules.price_step
    bid, ask = snap(row["close"], tick) - tick, snap(row["close"], tick, up=True) + tick
    if bid <= 0:
        raise ValueError("Native price incompatible with tick")
    at = row["at"]
    return Frame(
        at,
        Book(bid, ask, at),
        Book(row["eth_usd"], row["eth_usd"], at),
        Book(row["btc_usd"], row["btc_usd"], at),
        rules,
    )


class BookReplay(Simulator):
    """v1.06 policies with the v1.07 comparison evidence limits."""

    def __init__(self, name, row, hold, rules, rate, through, participation, params=None, record=False):
        super().__init__(
            name,
            row,
            legacy_rules(rules),
            params=params,
            fee=rate,
            record=record,
            capital=value(hold, marks(row)),
        )
        self.wallet, self.original = dict(hold), dict(hold)
        self.through = through
        self.participation = participation
        self.reserved_seconds = 0
        self.first_fills = []

    def fill(self, row):
        order = self.order
        if not order:
            return
        was_filled = order["filled"]
        extra = self.rules["price_increment"] * (self.through - 1)
        super().fill(
            dict(
                row,
                low=row["low"] + extra,
                high=row["high"] - extra,
                volume=row["volume"] * self.participation,
            )
        )
        if not was_filled and order["filled"]:
            self.first_fills.append(row["at"] - order["created"])

    def step(self, row, params=None):
        if self.order and self.last and row["start"] == self.last["at"]:
            self.reserved_seconds += CADENCE
        super().step(row, params)

    def summary(self):
        snapshot = self.snapshot()
        pending_unfilled = int(bool(self.order and not self.order["filled"]))
        return dict(
            orders=snapshot["orders"],
            fills=snapshot["fills"],
            filled_orders=snapshot["filled_orders"],
            nonfills=snapshot["misses"],
            open_unfilled=pending_unfilled,
            fee_btc=snapshot["fees_btc"],
            fill_seconds=self.first_fills,
            reserved_seconds=self.reserved_seconds,
            drawdown=snapshot["max_drawdown"],
        )


class OneLegReplay:
    def __init__(self, hold, row, rules, fee, through, participation):
        self.hold, self.wallet = dict(hold), dict(hold)
        self.rules, self.fee = rules, fee
        self.through, self.participation = through, participation
        self.last, self.order = None, None
        self.peak = value(hold, marks(row))
        self.metrics = dict(
            orders=0,
            fills=0,
            filled_orders=0,
            nonfills=0,
            fee_btc=ZERO,
            fill_seconds=[],
            reserved_seconds=0,
            drawdown=ZERO,
        )
        self.predictions = {}

    @native_math
    def step(self, row, forecasts, relative):
        frame = frame_for(row, self.rules)
        order = self.order
        if order:
            continuous = row["start"] == self.last
            if continuous:
                self.metrics["reserved_seconds"] += CADENCE
                self.fill(order, row)
            resting = order["remaining"] and candidate(
                frame,
                self.wallet,
                self.hold,
                self.fee,
                forecasts,
                order["side"],
                resting=(order["price"], order["remaining"]),
            )
            if (
                not continuous
                or not isinstance(resting, Candidate)
                or not resting.qualified
                or row["at"] - order["started"] >= CHILD_SECONDS
            ):
                if not order["filled"]:
                    self.metrics["nonfills"] += 1
                self.order = None
        if self.order is None:
            proposal = strongest(evaluate(frame, self.wallet, self.hold, self.fee, forecasts))
            if proposal:
                self.order = dict(
                    started=row["at"],
                    remaining=proposal.quantity,
                    side=proposal.side,
                    price=proposal.price,
                    filled=False,
                )
                self.metrics["orders"] += 1
        for forecast in forecasts:
            self.predictions[row["at"], forecast.horizon] = (forecast, relative)
        nav = value(self.wallet, marks(row))
        self.peak = max(self.peak, nav)
        self.metrics["drawdown"] = max(self.metrics["drawdown"], 1 - nav / self.peak)
        self.last = row["at"]

    def fill(self, order, row):
        price, side = order["price"], order["side"]
        offset = self.rules.price_step * self.through
        through = row["low"] <= price - offset if side == "BUY" else row["high"] >= price + offset
        if not through:
            return
        size = snap(min(order["remaining"], row["volume"] * self.participation), self.rules.base_step)
        if not size:
            return
        commission = maker_commission(QUOTE, size, price, self.fee)
        for asset, delta in conversion(BASE, QUOTE, side, size, price, commission).items():
            self.wallet[asset] += delta
        if min(self.wallet.values()) < ZERO:
            raise ValueError("Replay overspent native funds")
        if not order["filled"]:
            self.metrics["filled_orders"] += 1
            self.metrics["fill_seconds"].append(row["at"] - order["started"])
        order["filled"] = True
        order["remaining"] -= size
        self.metrics["fills"] += 1
        self.metrics["fee_btc"] += commission.amount

    def summary(self):
        return dict(self.metrics, open_unfilled=int(bool(self.order and not self.order["filled"])))


def select(name, rows, hold, rules):
    best = None
    for index, params in enumerate(grid(name)):
        sim = BookReplay(
            name, rows[0], hold, rules, BASELINE, TRADE_THROUGH_TICKS, TRADE_PARTICIPATION, params
        )
        for row in rows:
            sim.step(row)
        end = sim.snapshot()
        rank = (end["advantage_usd"], -end["fees_usd"], -end["orders"], -index)
        if best is None or rank > best[0]:
            best = rank, params
    return best[1]


def final_result(sim, end, hold, rounds, name):
    data = sim.summary()
    closing = marks(end)
    original = value(hold, closing)
    nav = value(sim.wallet, closing)
    advantage = nav - original
    times = data.pop("fill_seconds")
    concentration = sim.wallet[BASE] * closing[BASE] / nav
    return dict(
        **data,
        modeled_usd=nav,
        hold_usd=original,
        advantage_usd=advantage,
        gross_advantage_usd=advantage + data["fee_btc"] * closing[QUOTE],
        advantage_pct=advantage / original,
        positive_windows=sum(window["changes_usd"][name] > 0 for window in rounds),
        total_windows=len(rounds),
        positive_window_fraction=D(sum(window["changes_usd"][name] > 0 for window in rounds)) / len(rounds),
        mean_first_fill_seconds=mean(times) if times else None,
        ending_eth_concentration=concentration,
        ending_btc_concentration=1 - concentration,
    )


@native_math
def study(rows, rules, *, opening=None, train_days=60, window_days=30):
    if not rows:
        return {"status": "NOT_EVALUATED", "reason": "No synchronized closed candles"}
    prices = relatives(rows)
    start = rows[0]["at"]
    cut = start + train_days * 86400
    finish = rows[-1]["at"] + CADENCE
    first = next((row for row in rows if row["at"] >= cut), None)
    if not first or cut + window_days * 86400 > finish:
        return {
            "status": "NOT_EVALUATED",
            "reason": "Insufficient chronological training and holdout coverage",
        }
    if opening is None:
        hold = {asset: D(100) / price for asset, price in marks(first).items()}
    else:
        hold = opening
    engines = {
        scenario: {
            name: BookReplay(name, first, hold, rules, rate, through, part, record=False)
            if name != "ONE_LEG"
            else OneLegReplay(hold, first, rules, rate, through, part)
            for name in (*STRATEGIES, "ONE_LEG")
        }
        for scenario, rate, through, part in SCENARIOS
    }
    rounds = {scenario: [] for scenario in engines}
    last = first
    original_mark = marks(first)
    for boundary in range(cut, finish - window_days * 86400 + 1, window_days * 86400):
        next_boundary = boundary + window_days * 86400
        training = [row for row in rows if boundary - train_days * 86400 <= row["at"] < boundary]
        heldout = [row for row in rows if boundary <= row["at"] < next_boundary]
        if not training or not heldout:
            continue
        for row in heldout:
            if "bid" not in row:
                frame = frame_for(row, rules)
                row.update(bid=frame.native.bid, ask=frame.native.ask)
        for row in training:
            if "bid" not in row:
                frame = frame_for(row, rules)
                row.update(bid=frame.native.bid, ask=frame.native.ask)
        selection = {
            name: select(name, training, hold, rules)
            for name in STRATEGIES
            if name != "ROUNDTRIP_ALTERNATING"
        }
        selection["ROUNDTRIP_ALTERNATING"] = selection["ROUNDTRIP"]
        model = fit(prices, boundary - CADENCE)
        for scenario, group in engines.items():
            before = {
                name: value(sim.wallet, original_mark) - value(hold, original_mark)
                for name, sim in group.items()
            }
            for sim in group.values():
                if isinstance(sim, BookReplay) and sim.last is None:
                    sim.trail = deque((f["close"] for f in training[-287:]), maxlen=288)
            for row in heldout:
                forecasts = at_time(prices, row["at"], model)
                for name, sim in group.items():
                    if name == "ONE_LEG":
                        sim.step(row, forecasts, prices[row["at"]])
                    else:
                        sim.step(row, selection[name])
            final = marks(heldout[-1])
            rounds[scenario].append(
                dict(
                    from_utc=iso(heldout[0]["at"]),
                    to_utc=iso(heldout[-1]["at"]),
                    rows=len(heldout),
                    missing=(next_boundary - boundary) // CADENCE - len(heldout),
                    changes_usd={
                        name: value(sim.wallet, final) - value(hold, final) - before[name]
                        for name, sim in group.items()
                    },
                    parameters=selection,
                )
            )
        last = heldout[-1]
        original_mark = marks(last)
    if not rounds[next(iter(rounds))]:
        return {"status": "NOT_EVALUATED", "reason": "No usable matched holdout windows"}
    forecasts = engines[SCENARIOS[0][0]]["ONE_LEG"].predictions
    resolved = [
        (forecast.horizon, forecast.estimate, forecast.lower, forecast.upper, prices[at + horizon] / base - 1)
        for (at, horizon), (forecast, base) in forecasts.items()
        if at + horizon <= last["at"] and at + horizon in prices
    ]
    return dict(
        status="EVALUATED_CONDITIONAL",
        real_fills=0,
        actual_commissions=None,
        holdout_end_utc=iso(last["at"]),
        forecasts=accuracy(resolved),
        forecast_outcomes_missing=len(forecasts) - len(resolved),
        scenarios={
            scenario: dict(
                windows=rounds[scenario],
                strategies={
                    name: final_result(sim, last, hold, rounds[scenario], name) for name, sim in group.items()
                },
            )
            for scenario, group in engines.items()
        },
    )


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def report_text(report):
    lines = ["# CoinCat v1.07 matched research comparison", "", f"Status **{report['status']}**", ""]
    if report["status"] == "NOT_EVALUATED":
        return "\n".join([*lines, report["reason"], ""])
    lines += [
        "Five-minute close-derived book proxies and subsequent strict trade-through only.",
        "Conditional fill times are measured at bar close. Fill, queue and exact commissions are unverified.",
        "Gross USD advantage adds modeled BTC commissions back at the ending BTC mark.",
        "",
    ]
    for scenario, result in report["scenarios"].items():
        lines.extend(
            [
                f"## {scenario}",
                "",
                "| Strategy | Net USD vs HOLD | Gross USD vs HOLD | Winning windows | Fills | Nonfills | Drawdown |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for name, row in result["strategies"].items():
            lines.append(
                f"| {name} | {row['advantage_usd']:.6f} | {row['gross_advantage_usd']:.6f} | "
                f"{row['positive_windows']}/{row['total_windows']} | {row['fills']} | "
                f"{row['nonfills']} | {row['drawdown']:.2%} |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--fees", type=Path, required=True, help="Output of coincat.fees --rules")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eth", type=decimal)
    parser.add_argument("--btc", type=decimal)
    args = parser.parse_args()
    if (args.eth is None) != (args.btc is None) or (
        args.eth is not None and (min(args.eth, args.btc) < 0 or not (args.eth or args.btc))
    ):
        parser.error("Provide both starting quantities, nonnegative and with a positive portfolio")
    try:
        verified = json.loads(args.fees.read_text(encoding="utf-8-sig"))
        if verified["status"] != "VERIFIED":
            raise ValueError("Account fee schedule unverified")
        rules = Rules(
            **{
                key: decimal(val) if val is not None else None
                for key, val in verified["public_eth_btc_rules"].items()
            }
        )
        history = read_bars(args.data)
        opening = {BASE: args.eth, QUOTE: args.btc} if args.eth is not None else None
        report = study(history, rules, opening=opening)
        report["verified_current_account_maker_percent"] = verified["fees"]["one_leg_maker_percent"]
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
        report = {
            "status": "NOT_EVALUATED",
            "reason": "Verified fee schedule, valid native rules and three synchronized public candle exports are required.",
            "input_error_type": type(error).__name__,
        }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(report, default=str, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "comparison.md").write_text(report_text(report), encoding="utf-8")
    print(report["status"])
    return 0 if report["status"] == "EVALUATED_CONDITIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
