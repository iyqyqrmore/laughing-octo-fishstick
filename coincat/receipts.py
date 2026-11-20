"""Read-only actual Coinbase receipt audit, kept outside the shadow wallet."""

import argparse
from uuid import UUID
import sqlite3

from .market import Coinbase, MarketUnavailable, PRODUCT, BASE, QUOTE, timestamp
from .money import decimal, native_math
from .store import Store


def normalize_receipt(raw):
    if raw["product_id"] != PRODUCT or raw["side"] not in ("BUY", "SELL"):
        raise ValueError("Unexpected native receipt")
    identity, order, executed_at = raw["entry_id"], raw["order_id"], raw["trade_time"]
    timestamp(executed_at)
    if not isinstance(identity, str) or not identity or not isinstance(order, str) or not order:
        raise ValueError("Missing durable fill identity")
    quantity, price, fee = map(decimal, (raw["size"], raw["price"], raw["commission"]))
    if min(quantity, price) <= 0 or fee < 0:
        raise ValueError("Invalid native receipt amount")
    flag = raw.get("size_in_quote")
    unit = QUOTE if flag is True else BASE if flag is False else None
    evidence = [
        str(raw[key]).strip().upper() for key in ("commission_currency", "fee_currency") if raw.get(key)
    ]
    currency = evidence[0] if evidence and len(set(evidence)) == 1 and evidence[0].isalnum() else None
    liquidity = {"M": "MAKER", "MAKER": "MAKER", "T": "TAKER", "TAKER": "TAKER"}.get(
        raw.get("liquidity_indicator"), "UNKNOWN"
    )
    return (
        identity,
        order,
        executed_at,
        raw["side"],
        str(quantity),
        unit,
        str(price),
        str(fee),
        currency,
        liquidity,
    )


def import_receipts(client, store, *, max_pages=20, order=None):
    cursor, seen = None, set()
    received, changed, conflicts = 0, 0, 0
    complete = False
    for _ in range(max_pages):
        page = client.receipt_page(cursor, order)
        rows = page["fills"]
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Invalid account receipt page")
        with store.transaction() as sql:
            for raw in rows:
                received += 1
                values = normalize_receipt(raw)
                if order and values[1] != order:
                    raise ValueError("Receipt falls outside the requested order")
                old = sql.execute("SELECT * FROM actual_receipts WHERE id=?", (values[0],)).fetchone()
                if old is None:
                    sql.execute("INSERT INTO actual_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", values)
                    changed += 1
                elif tuple(old) != values:
                    sql.execute("""CREATE TABLE IF NOT EXISTS actual_receipt_conflicts
                        (receipt_id TEXT, payload TEXT, PRIMARY KEY(receipt_id,payload))""")
                    sql.execute(
                        "INSERT OR IGNORE INTO actual_receipt_conflicts VALUES (?,?)",
                        (values[0], repr(values)),
                    )
                    conflicts += 1
        cursor = page.get("cursor")
        if not cursor:
            complete = True
            break
        if cursor in seen:
            break
        seen.add(cursor)
    return received, changed, conflicts, complete


@native_math
def reconcile_order(client, store, order):
    raw = client.order_receipt(order)
    if raw["product_id"] != PRODUCT or raw["order_id"] != order:
        raise ValueError("Order does not match the requested ETH-BTC receipt")
    filled = decimal(raw["filled_size"])
    if filled < 0:
        raise ValueError("Negative filled order quantity")
    config = raw.get("order_configuration") or {}
    limit = config.get("limit_limit_gtc") or {}
    base_size = limit.get("base_size")
    ordered = decimal(base_size) if base_size not in (None, "") else None
    state = raw["status"]
    valid = {"OPEN", "FILLED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED", "PENDING", "QUEUED"}
    if state not in valid or ordered is not None and (ordered <= 0 or ordered < filled):
        raise ValueError("Unexpected order status or size")
    with store.transaction() as sql:
        prior = sql.execute("SELECT filled_base,status FROM actual_orders WHERE id=?", (order,)).fetchone()
        if prior and (
            filled < decimal(prior["filled_base"])
            or prior["status"] in {"FILLED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED"}
            and (state != prior["status"] or filled != decimal(prior["filled_base"]))
        ):
            raise ValueError("Conflicting order history")
        sql.execute(
            """INSERT INTO actual_orders VALUES (?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status,filled_base=excluded.filled_base,
            ordered_base=excluded.ordered_base,fill_currency=excluded.fill_currency""",
            (order, state, str(filled), str(ordered) if ordered is not None else None, BASE),
        )
        credited = 0
        for receipt in sql.execute("SELECT * FROM actual_receipts WHERE order_id=?", (order,)):
            if receipt["size_unit"] != BASE:
                return "UNVERIFIED_NATIVE_SIZE"
            credited += decimal(receipt["size"])
        return "QUANTITIES_MATCH" if credited == filled else "UNRESOLVED_FILL_QUANTITY"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", type=UUID, help="Inspect one known ETH-BTC order as well as its fills")
    args = parser.parse_args()
    order = str(args.order) if args.order else None
    client = Coinbase()
    if not client.has_credentials:
        parser.exit(1, "Read-only Coinbase credentials unavailable. No data imported.\n")
    try:
        store = Store()
        received, changed, conflicts, complete = import_receipts(client, store, order=order)
        reconciliation = reconcile_order(client, store, order) if order else None
    except (MarketUnavailable, KeyError, TypeError, ValueError, OSError, ImportError, sqlite3.Error):
        parser.exit(1, "Coinbase fill reconciliation incomplete. Prior committed receipts are retained.\n")
    print(f"Actual receipts observed {received}; newly recorded {changed}; conflicts retained {conflicts}.")
    print("History coverage:", "cursor exhausted" if complete else "partial")
    if reconciliation:
        print("Actual order reconciliation:", reconciliation)
    return 0 if complete and not conflicts and reconciliation in (None, "QUANTITIES_MATCH") else 1


if __name__ == "__main__":
    raise SystemExit(main())
