"""Closed, synchronized public candles for chronological research and forecasting."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import sqlite3
import time

from .market import BASE, QUOTE, PRODUCT, PRODUCTS, Coinbase, MarketUnavailable
from .money import decimal, native_math

INTERVALS = {60: "ONE_MINUTE", 300: "FIVE_MINUTE", 3600: "ONE_HOUR"}
FIELDS = ("open", "high", "low", "close", "volume")


def checked_bar(row, seconds):
    start = int(row["start"])
    if start < 0 or start % seconds or str(start) != str(row["start"]):
        raise ValueError("Unaligned candle")
    opened, high, low, closed, volume = amounts = tuple(decimal(row[key]) for key in FIELDS)
    if not 0 < low <= min(opened, closed) <= max(opened, closed) <= high or volume < 0:
        raise ValueError("Invalid candle OHLCV")

    def canonical(value):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    return (start, *(canonical(value) for value in amounts))


def read_bars(directory, seconds=300):
    interval = {60: "1m", 300: "5m", 3600: "1h"}[seconds]
    data = {}
    for product in PRODUCTS:
        with (directory / f"{product}_{interval}.csv").open(newline="", encoding="utf-8") as file:
            bars = {}
            for row in csv.DictReader(file):
                start, *values = checked_bar(row, seconds)
                amounts = tuple(map(decimal, values))
                if start in bars and bars[start] != amounts:
                    raise ValueError("Conflicting historical bars")
                if start + seconds > time.time():
                    raise ValueError("Historical export includes open candles")
                bars[start] = amounts
            data[product] = bars
    common = sorted(set.intersection(*(set(series) for series in data.values())))
    return [
        dict(
            start=at,
            at=at + seconds,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
            eth_usd=data[f"{BASE}-USD"][at][3],
            btc_usd=data[f"{QUOTE}-USD"][at][3],
        )
        for at in common
        for o, h, l, c, v in (data[PRODUCT][at],)
    ]


@native_math
def relatives(rows):
    return {row["at"]: row["eth_usd"] / row["btc_usd"] for row in rows}


def export(client, out, start, stop, seconds):
    """Resume successful pages. The first observation of a conflicting bar wins."""
    out.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out / "public_export.sqlite3")) as connection, connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS candle (
                product TEXT, seconds INTEGER, start INTEGER, o TEXT, h TEXT, l TEXT, c TEXT, v TEXT,
                PRIMARY KEY (product, seconds, start));
            CREATE TABLE IF NOT EXISTS page (
                product TEXT, seconds INTEGER, start INTEGER, end INTEGER,
                PRIMARY KEY (product, seconds, start, end));
            CREATE TABLE IF NOT EXISTS conflict (
                product TEXT, seconds INTEGER, start INTEGER, incoming TEXT,
                PRIMARY KEY (product, seconds, start, incoming));
        """)
        for product in PRODUCTS:
            for left in range(start, stop, 349 * seconds):
                right = min(stop, left + 349 * seconds)
                key = (product, seconds, left, right)
                if connection.execute(
                    "SELECT 1 FROM page WHERE product=? AND seconds=? AND start=? AND end=?", key
                ).fetchone():
                    continue
                time.sleep(0.4)
                rows = client.candle_page(product, left, right, INTERVALS[seconds])
                if not isinstance(rows, list) or len(rows) > 350:
                    raise MarketUnavailable("Invalid public candle page")
                with connection:
                    for row in rows:
                        at, *amounts = checked_bar(row, seconds)
                        if at == right:
                            continue
                        if not left <= at < right:
                            raise MarketUnavailable("Candle outside requested window")
                        lookup = (product, seconds, at)
                        existing = connection.execute(
                            "SELECT o,h,l,c,v FROM candle WHERE product=? AND seconds=? AND start=?", lookup
                        ).fetchone()
                        if existing is None:
                            connection.execute(
                                "INSERT INTO candle VALUES (?,?,?,?,?,?,?,?)", (*lookup, *amounts)
                            )
                        elif existing != tuple(amounts):
                            connection.execute(
                                "INSERT OR IGNORE INTO conflict VALUES (?,?,?,?)",
                                (*lookup, ",".join(amounts)),
                            )
                    connection.execute("INSERT INTO page VALUES (?,?,?,?)", key)
            interval = {60: "1m", 300: "5m", 3600: "1h"}[seconds]
            path = out / f"{product}_{interval}.csv"
            temporary = path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("start", *FIELDS))
                writer.writerows(
                    connection.execute(
                        "SELECT start,o,h,l,c,v FROM candle WHERE product=? AND seconds=? AND start>=? AND start<? ORDER BY start",
                        (product, seconds, start, stop),
                    )
                )
            temporary.replace(path)
            count = connection.execute(
                "SELECT COUNT(*) FROM candle WHERE product=? AND seconds=? AND start>=? AND start<?",
                (product, seconds, start, stop),
            ).fetchone()[0]
            print(f"{product} {interval}: {count} closed bars, {(stop - start) // seconds - count} missing")
        count = connection.execute("SELECT COUNT(*) FROM conflict WHERE seconds=?", (seconds,)).fetchone()[0]
        print(f"Conflicting revisions retained separately: {count}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--interval", type=int, default=300, choices=INTERVALS)
    parser.add_argument("--end", help="UTC date, YYYY-MM-DD, exclusive")
    args = parser.parse_args()
    if not 1 <= args.days <= 730:
        parser.error("--days must be between 1 and 730")
    stop = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp() if args.end else time.time()
    )
    if stop > time.time():
        parser.error("--end must not be in the future")
    stop = int(stop) // args.interval * args.interval
    try:
        export(Coinbase(), args.output, stop - args.days * 86400, stop, args.interval)
    except (MarketUnavailable, KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        parser.exit(1, "Coinbase export incomplete. Successful pages remain available to resume.\n")


if __name__ == "__main__":
    main()
