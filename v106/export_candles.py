"""M1: closed public ETH-BTC candles and USD references; no authentication/orders."""
from datetime import datetime, timezone
from contextlib import nullcontext
from pathlib import Path
import argparse
import csv
import hashlib
import json
import time

from v106.fee_check import ROOT, as_dict, exact, number, protect_sdk_logs, save_report

PRODUCTS = ("ETH-BTC", "BTC-USD", "ETH-USD")
FRAMES = {"1h": ("ONE_HOUR", 3600), "5m": ("FIVE_MINUTE", 300)}
OHLCV = ("open", "high", "low", "close", "volume")
COLUMNS = ("start", "start_utc", "end_utc") + OHLCV
GAPS = ("product", "interval", "start_utc", "end_utc", "missing_bars", "kind")
CONFLICTS = ("product", "interval", "start_utc", "first_ohlcv", "received_ohlcv")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def stamp(text):
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if len(text) != 10:
            raise ValueError("Use UTC dates or timestamps with an explicit offset")
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def canonical(value):
    text = number(exact(value))
    return text.rstrip("0").rstrip(".") if "." in text else text


def bar(item, seconds):
    t = int(item["start"])
    if str(t) != str(item["start"]) or t % seconds:
        raise ValueError("UNALIGNED_CANDLE")
    values = tuple(canonical(item[k]) for k in OHLCV)
    o, h, low, c, v = map(exact, values)
    if not 0 < low <= min(o, c) <= max(o, c) <= h or v < 0:
        raise ValueError("INVALID_OHLCV")
    return t, values


def parse_page(raw, start, end, seconds, received):
    items = as_dict(raw).get("candles")
    if not isinstance(items, list) or len(items) > 350:
        raise ValueError("INVALID_CANDLE_PAGE")
    result = []
    for item in items:
        t = int(item["start"])
        if str(t) != str(item["start"]) or t % seconds:
            raise ValueError("UNALIGNED_CANDLE")
        if t == end:
            continue
        if not start <= t < end or t + seconds > received:
            raise ValueError("OUT_OF_WINDOW_OR_OPEN_CANDLE")
        result.append(bar(item, seconds))
    return result


def missing_ranges(start, end, covered):
    cursor = start
    result = []
    for a, b in sorted(covered):
        a, b = max(start, a), min(end, b)
        if a >= b:
            continue
        if b <= cursor:
            continue
        if a > cursor:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < end:
        result.append((cursor, end))
    return result


def gaps(start, end, rows, seconds):
    cursor = start
    for t in sorted(t for t in rows if start <= t < end):
        if t > cursor:
            yield cursor, t
        cursor = t + seconds
    if cursor < end:
        yield cursor, end


def write_csv(path, columns, rows):
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f); writer.writerow(columns); writer.writerows(rows)
    tmp.replace(path)


def csv_row(t, values, seconds):
    return (t, iso(t), iso(t + seconds), *values)


class Exporter:
    def __init__(self, client, output, *, pause=.4, clock=time.time, sleeper=time.sleep, progress=print):
        self.client, self.output, self.pause = client, Path(output), pause
        self.clock, self.sleep, self.progress = clock, sleeper, progress
        self.output.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output / "export_state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(schema=1, streams={})
        if self.state.get("schema") != 1 or not isinstance(self.state.get("streams"), dict):
            raise ValueError("INVALID_EXPORT_STATE")
        self.conflicts_path = self.output / "conflicts.csv"
        with self.conflicts_path.open(newline="", encoding="utf-8") if self.conflicts_path.exists() else nullcontext([]) as f:
            self.conflicts = set(tuple(row) for row in csv.reader(f) if row and tuple(row) != CONFLICTS)
        self.requests = 0
        self.limited = False

    def load(self, path, seconds):
        result = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if tuple(reader.fieldnames or ()) != COLUMNS:
                    raise ValueError("INVALID_EXISTING_CSV_HEADER")
                for row in reader:
                    t, value = bar(row, seconds)
                    if t in result and result[t] != value:
                        product, interval = path.stem.rsplit('_', 1)
                        self.conflicts.add((product, interval, iso(t), "|".join(result[t]), "|".join(value)))
                        continue
                    result[t] = value
        return result

    def stream(self, product, frame, start, end):
        granularity, seconds = FRAMES[frame]; name = product + "_" + frame
        path = self.output / (name + ".csv"); rows = self.load(path, seconds)
        metadata = self.state["streams"].get(name, dict(pages=[], rows=0))
        covered = metadata["pages"] if path.exists() and len(rows) >= metadata["rows"] else []
        if not path.exists():
            write_csv(path, COLUMNS, [])
        pages, error = 0, None
        try:
            for a, right in reversed(missing_ranges(start, end, covered)):
                while right > a:
                    if self.limited:
                        error = "RATE_LIMITED_RETRY_LATER"; break
                    left = max(a, right - 349 * seconds)  # + inclusive endpoint <= 350 response bars
                    self.sleep(self.pause); self.requests += 1
                    raw = self.client.get_public_candles(product_id=product, start=str(left), end=str(right), granularity=granularity, limit=350)
                    received = self.clock(); incoming = parse_page(raw, left, right, seconds, received)
                    fresh = []
                    for t, value in incoming:
                        if t in rows:
                            if rows[t] != value:
                                self.conflicts.add((product, frame, iso(t), "|".join(rows[t]), "|".join(value)))
                        else:
                            rows[t] = value; fresh.append(csv_row(t, value, seconds))
                    with path.open("a", newline="", encoding="utf-8") as f:
                        csv.writer(f).writerows(fresh)
                    covered.append([left, right]); pages += 1
                    self.state["streams"][name] = dict(pages=covered, rows=len(rows))
                    save_report(self.state, self.state_path)
                    write_csv(self.conflicts_path, CONFLICTS, sorted(self.conflicts))
                    if pages == 1 or pages % 25 == 0:
                        self.progress(f"{name}: {pages} pages this run; {len(rows)} saved bars; reached {iso(left)}")
                    right = left
        except Exception as exc:
            response = getattr(exc, "response", None); status = getattr(response, "status_code", None)
            error = "HTTP_" + str(status) if type(status) is int else "INVALID_CANDLES" if isinstance(exc, (ValueError, KeyError, TypeError)) else "PUBLIC_CANDLE_READ_FAILED"
            if status == 429:
                self.limited = True  # Stop further GETs; resume later rather than hammering the API.
        finally:
            write_csv(path, COLUMNS, (csv_row(t, v, seconds) for t, v in sorted(rows.items())))
            write_csv(self.conflicts_path, CONFLICTS, sorted(self.conflicts))
        selected = {t: v for t, v in rows.items() if start <= t < end}
        unrequested = missing_ranges(start, end, covered); gap_rows = []
        for a, b in gaps(start, end, selected, seconds):
            cuts = sorted({a, b} | {max(a, x) for x, y in unrequested if x < b and y > a} | {min(b, y) for x, y in unrequested if x < b and y > a})
            for x, y in zip(cuts, cuts[1:]):
                kind = "NOT_FETCHED" if any(u <= x < v for u, v in unrequested) else "NO_CANDLE_RETURNED"
                gap_rows.append((product, frame, iso(x), iso(y), (y-x)//seconds, kind))
        report = dict(product=product, interval=frame, status="FAILED" if error else "COMPLETE", error=error,
            requested_start_utc=iso(start), requested_end_utc=iso(end), rows=len(selected), total_saved_rows=len(rows),
            first_start_utc=iso(min(selected)) if selected else None, last_end_utc=iso(max(selected)+seconds) if selected else None,
            missing_bars=sum(r[4] for r in gap_rows if r[5]=="NO_CANDLE_RETURNED"),
            unfetched_bars=sum((b-a)//seconds for a,b in unrequested), pages_this_run=pages,
            csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.progress(f"{name}: {report['status']}; rows {len(selected)}; {report['first_start_utc']} to {report['last_end_utc']}; gaps {report['missing_bars']}; unfetched {report['unfetched_bars']}")
        return report, gap_rows

    def run(self, *, days=730, start=None, end=None):
        now = int(self.clock()); cutoff = now if end is None else end
        if not 1 <= days <= 730 or cutoff > now or start is not None and not 0 < cutoff-start <= 730*86400:
            raise ValueError("USE_PAST_UTC_WINDOW_AT_MOST_730_DAYS")
        reports, gap_rows = [], []
        for product in PRODUCTS:
            for frame, (_, seconds) in FRAMES.items():
                right = cutoff//seconds*seconds
                left = right-days*86400 if start is None else (start+seconds-1)//seconds*seconds
                if left >= right:
                    raise ValueError("NO_COMPLETE_CANDLE_IN_WINDOW")
                report, missing = self.stream(product, frame, left, right)
                reports.append(report); gap_rows.extend(missing)
        write_csv(self.output / "gaps.csv", GAPS, sorted(gap_rows))
        result = dict(version="1.06", milestone="M1", source="COINBASE_ADVANCED_TRADE_PUBLIC_CANDLES", read_only=True,
            status="COMPLETE" if all(r["status"]=="COMPLETE" for r in reports) else "INCOMPLETE", requests_this_run=self.requests,
            streams=reports, conflicting_versions=len(self.conflicts))
        save_report(result, self.output / "export_summary.json")
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"v106_out"/"data")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--start", type=stamp); parser.add_argument("--end", type=stamp)
    args = parser.parse_args(argv); protect_sdk_logs()
    from coinbase.rest import RESTClient
    client = RESTClient(api_key="", api_secret="", timeout=20, verbose=False)
    try:
        result = Exporter(client, args.output).run(days=args.days, start=args.start, end=args.end)
        print("M1", result["status"], "| see gaps.csv, conflicts.csv and export_summary.json | No trades.")
        return 0 if result["status"]=="COMPLETE" else 1
    finally:
        client.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
