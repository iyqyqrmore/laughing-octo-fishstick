"""M0 only: authenticated fee/product GETs, no order or balance operations."""
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from coinbase_account import as_dict, load_encrypted, parse_key_json
from coincat_authenticated_client import client_from_credentials
from coincat_sdk_logging import protect_sdk_logs
from coincat_spot_market import native_book
from coincat_state_v50 import data_root
from coincat_v80_immediate import exact

PAIR = "ETH-BTC"
DEFAULT_OUTPUT = ROOT / "v106_out" / "fees.json"


class FeeCheckError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def number(value):
    return format(value, "f")


def fee_summary(raw):
    tier = raw["fee_tier"]
    maker, taker = (exact(tier[key]) for key in ("maker_fee_rate", "taker_fee_rate"))
    if not (0 <= maker < 1 and 0 <= taker < 1):
        raise FeeCheckError("INVALID_API_FEE_RATE")
    with localcontext() as ctx:
        ctx.prec = 80
        return dict(maker_rate=number(maker), taker_rate=number(taker),
            maker_percent=number(100 * maker), taker_percent=number(100 * taker),
            round_trip_rate_sums=dict(maker_maker=number(2 * maker), taker_taker=number(2 * taker)),
            round_trip_percent_sums=dict(maker_maker=number(200 * maker), taker_taker=number(200 * taker)),
            basis="SUM_OF_TWO_LEG_RATES_EXCLUDES_SPREAD_AND_PRICE_CHANGES",
            source="AUTHENTICATED_SPOT_TRANSACTION_SUMMARY")


def product_summary(raw):
    if (raw.get("product_id") != PAIR or raw.get("product_type") != "SPOT" or
            raw.get("base_currency_id", "ETH") != "ETH" or raw.get("quote_currency_id", "BTC") != "BTC"):
        raise FeeCheckError("WRONG_NATIVE_PRODUCT")
    fields = ("base_increment", "quote_increment", "base_min_size", "quote_min_size")
    values = {key: exact(raw[key]) for key in fields}
    values["price_increment"] = exact(raw.get("price_increment", raw["quote_increment"]))
    for key in ("base_max_size", "quote_max_size"):
        values[key] = None if raw.get(key) in (None, "") else exact(raw[key])
    if any(v is not None and v <= 0 for v in values.values()):
        raise FeeCheckError("INVALID_NATIVE_PRODUCT_RULES")
    for currency in ("base", "quote"):
        maximum = values[currency + "_max_size"]
        if maximum is not None and maximum < values[currency + "_min_size"]:
            raise FeeCheckError("CONFLICTING_NATIVE_PRODUCT_LIMITS")
    return dict(product_id=PAIR, base_asset="ETH", quote_asset="BTC",
        **{key: None if value is None else number(value) for key, value in values.items()},
        status=raw.get("status"), view_only=raw.get("view_only"),
        trading_disabled=raw.get("trading_disabled"), cancel_only=raw.get("cancel_only"))


def minimum_orders(product, book):
    """Gross rule-based minimums at maker touch, not balance/fee/preview approval."""
    with localcontext() as ctx:
        ctx.prec = 80
        inc = exact(product["base_increment"])
        tick = exact(product["price_increment"])
        result = {}
        for side, touch, rounding in (("BUY", book["bid"], ROUND_FLOOR), ("SELL", book["ask"], ROUND_CEILING)):
            price = (touch / tick).to_integral_value(rounding=rounding) * tick
            if price <= 0:
                raise FeeCheckError("NO_POSITIVE_NATIVE_MAKER_PRICE")
            quantity = max(exact(product["base_min_size"]), exact(product["quote_min_size"]) / price)
            quantity = (quantity / inc).to_integral_value(rounding=ROUND_CEILING) * inc
            notional = quantity * price
            for key, value in (("base_max_size", quantity), ("quote_max_size", notional)):
                if product[key] is not None and value > exact(product[key]):
                    raise FeeCheckError("EXCHANGE_MINIMUM_EXCEEDS_MAXIMUM_AT_PRICE")
            result[side] = dict(quantity_eth=number(quantity), notional_btc=number(notional),
                price_btc_per_eth=number(price))
        return result


def blank_report(clock=utc_now):
    return dict(version="1.06", milestone="M0", status="UNVERIFIED", read_only=True,
        checked_at_utc=clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        product_id=PAIR, fees=None, product=None, minimum_orders=None,
        minimum_basis="GROSS_NATIVE_RULES_AT_MAKER_TOUCH_EXCLUDES_FEES_NOT_ORDER_ACCEPTANCE",
        errors=[])


def collect(client, clock=utc_now):
    report = blank_report(clock)
    try:
        report["fees"] = fee_summary(as_dict(client.get_transaction_summary(product_type="SPOT")))
    except Exception:
        report["errors"].append("AUTHENTICATED_SPOT_FEES_UNAVAILABLE")
    try:
        raw = as_dict(client.get_product(product_id=PAIR, get_tradability_status=True))
        report["product"] = product_summary(raw)
    except Exception:
        report["errors"].append("ETH_BTC_PRODUCT_RULES_UNAVAILABLE")
    if report["product"] is not None:
        try:
            raw = as_dict(client.get_product_book(product_id=PAIR, limit=1))
            book = native_book(PAIR, raw, clock().timestamp())
            report["minimum_orders"] = minimum_orders(report["product"], book)
        except Exception:
            report["errors"].append("ETH_BTC_MINIMUM_AT_CURRENT_BOOK_UNAVAILABLE")
    report["status"] = "VERIFIED" if not report["errors"] else "PARTIAL" if report["fees"] or report["product"] else "UNVERIFIED"
    return report


def credentials_from_local():
    name, secret = os.environ.get("COINBASE_API_KEY"), os.environ.get("COINBASE_API_SECRET")
    if name or secret:
        if not name or not secret:
            raise FeeCheckError("BOTH_COINBASE_ENVIRONMENT_VALUES_REQUIRED")
        return parse_key_json(json.dumps(dict(name=name, privateKey=secret)))
    # Avoid creating a new data directory just to discover there is no vault.
    if not (data_root() / "coinbase_key.dpapi").is_file():
        raise FeeCheckError("SAVED_KEY_OR_ENVIRONMENT_CREDENTIALS_REQUIRED")
    value = load_encrypted()
    if value is None:
        raise FeeCheckError("SAVED_KEY_OR_ENVIRONMENT_CREDENTIALS_REQUIRED")
    return value


def run(clock=utc_now):
    protect_sdk_logs()
    report = blank_report(clock)
    try:
        credentials = credentials_from_local()
    except FeeCheckError as exc:
        report["errors"].append(str(exc))
        return report
    except Exception:
        report["errors"].append("LOCAL_CREDENTIALS_UNAVAILABLE_USE_ORIGINAL_WINDOWS_USER")
        return report
    client = None
    try:
        client = client_from_credentials(credentials)
        report = collect(client, clock)
    except Exception:
        report["errors"].append("AUTHENTICATED_QUERY_UNAVAILABLE")
    finally:
        if client is not None:
            try:
                client.session.close()
            except Exception:
                report["errors"].append("READ_ONLY_SESSION_CLOSE_FAILED")
                if report["status"] == "VERIFIED":
                    report["status"] = "PARTIAL"
    return report


def save_report(report, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = run()
    try:
        save_report(report, args.output)
    except OSError:
        print("M0: could not save fees.json; no orders were sent.")
        return 2
    print("CoinCat v1.06 M0:", report["status"], "| GET-only | ETH-BTC")
    fees = report["fees"]
    if fees:
        print("Maker:", fees["maker_percent"] + "%", "| Taker:", fees["taker_percent"] + "%")
        costs = fees["round_trip_percent_sums"]
        print("Round-trip rate sums: maker+maker", costs["maker_maker"] + "%", "| taker+taker", costs["taker_taker"] + "%")
        print("Rate sums exclude spread/price changes; each executed leg has its own fee.")
    else:
        print("Maker, taker and round-trip rates: UNKNOWN; no assumed fee substituted.")
    if report["product"]:
        print("Native product rules:", json.dumps(report["product"], sort_keys=True))
    for side, value in (report["minimum_orders"] or {}).items():
        print("Minimum", side + ":", value["quantity_eth"], "ETH /", value["notional_btc"], "BTC at", value["price_btc_per_eth"], "BTC/ETH (gross, before fees)")
    if report["minimum_orders"] is None:
        print("Minimum ETH/BTC order at current book: UNKNOWN.")
    if report["errors"]:
        print("Unverified checks:", ", ".join(report["errors"]))
    print("Saved:", args.output, "| No trades. Stop after M0.")
    return 0 if report["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
