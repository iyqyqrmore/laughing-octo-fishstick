"""Fresh, versioned SQLite shadow ledger. No legacy database is opened."""

from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .forecast import accuracy
from .market import BASE, QUOTE
from .money import Commission, D, ZERO, conversion, maker_commission, native_math, reserve, value

DATA = Path(__file__).resolve().parents[1] / "private_data" / "v107"
DB_NAME = "one_leg.sqlite3"
APP_ID = 107
ASSETS = (BASE, QUOTE)
SCHEMA = """
CREATE TABLE opening (asset TEXT PRIMARY KEY, amount TEXT NOT NULL);
CREATE TRIGGER freeze_opening_update BEFORE UPDATE ON opening BEGIN
    SELECT RAISE(ABORT, 'Opening HOLD is immutable'); END;
CREATE TRIGGER freeze_opening_delete BEFORE DELETE ON opening BEGIN
    SELECT RAISE(ABORT, 'Opening HOLD is immutable'); END;
CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL,
                    wave REAL NOT NULL DEFAULT 0);
CREATE TABLE wallet (asset TEXT PRIMARY KEY, amount TEXT NOT NULL);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY, campaign INTEGER REFERENCES orders(id), side TEXT NOT NULL,
    price TEXT NOT NULL, quantity TEXT NOT NULL, rate TEXT NOT NULL,
    source_cap TEXT NOT NULL, started REAL NOT NULL, anchor TEXT NOT NULL,
    horizon INTEGER NOT NULL, edge TEXT NOT NULL, remaining TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN', ended REAL, reason TEXT);
CREATE UNIQUE INDEX one_active_order ON orders ((1)) WHERE status IN ('OPEN','UNKNOWN');
CREATE TABLE fills (
    order_id INTEGER NOT NULL REFERENCES orders(id), evidence_id TEXT NOT NULL,
    filled_at REAL NOT NULL, quantity TEXT NOT NULL, fee_currency TEXT NOT NULL,
    commission TEXT NOT NULL, btc_usd TEXT NOT NULL,
    PRIMARY KEY(order_id, evidence_id));
CREATE TABLE marks (
    at REAL PRIMARY KEY, eth_usd TEXT NOT NULL, btc_usd TEXT NOT NULL,
    nav TEXT NOT NULL, hold TEXT NOT NULL, peak TEXT NOT NULL, drawdown TEXT NOT NULL);
CREATE TABLE rejections (reason TEXT PRIMARY KEY, count INTEGER NOT NULL);
CREATE TABLE forecast_closes (at INTEGER PRIMARY KEY, relative TEXT NOT NULL);
CREATE TABLE forecasts (
    made INTEGER NOT NULL, horizon INTEGER NOT NULL, relative TEXT NOT NULL, expected TEXT NOT NULL,
    low TEXT NOT NULL, high TEXT NOT NULL, realized TEXT, status TEXT NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY(made,horizon));
CREATE TABLE actual_receipts (
    id TEXT PRIMARY KEY, order_id TEXT NOT NULL, executed_at TEXT NOT NULL, side TEXT NOT NULL,
    size TEXT NOT NULL, size_unit TEXT, price TEXT NOT NULL, commission TEXT NOT NULL,
    fee_currency TEXT, liquidity TEXT NOT NULL);
CREATE TABLE actual_orders (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, filled_base TEXT NOT NULL,
    ordered_base TEXT, fill_currency TEXT);
"""


class Store:
    def __init__(self, directory=DATA):
        self.path = directory / DB_NAME
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Database path is a symbolic link")
        with self.transaction(initialize=True):
            pass

    @contextmanager
    def transaction(self, *, initialize=False):
        with closing(sqlite3.connect(self.path, timeout=3)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                identity = connection.execute("PRAGMA application_id").fetchone()[0]
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if initialize and identity == 0 and version == 0:
                    if connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                        raise ValueError("Database belongs to another build")
                    for sql in split_schema(SCHEMA):
                        connection.execute(sql)
                    connection.execute(f"PRAGMA application_id={APP_ID}")
                    connection.execute("PRAGMA user_version=1")
                elif (identity, version) != (APP_ID, 1):
                    raise ValueError("Unsupported shadow database")
                yield connection

    def seed(self, portfolio):
        if set(portfolio) != set(ASSETS) or min(portfolio.values()) < ZERO or not any(portfolio.values()):
            raise ValueError("Enter the actual opening ETH and BTC quantities")
        with self.transaction() as sql:
            sql.execute("INSERT INTO state(id, paused) VALUES (1,1)")
            sql.executemany(
                "INSERT INTO opening VALUES (?,?)", ((asset, str(portfolio[asset])) for asset in ASSETS)
            )
            sql.execute("INSERT INTO wallet SELECT * FROM opening")

    def recover(self, at):
        with self.transaction() as sql:
            if (
                sql.execute("PRAGMA quick_check").fetchone()[0] != "ok"
                or sql.execute("PRAGMA foreign_key_check").fetchone()
            ):
                raise ValueError("Shadow database needs review")
            verify_ledger(sql)
            order = active(sql)
            if order and order.status == "OPEN":
                finish(sql, order, "UNKNOWN", at, "RESTART_GAP")
            sql.execute("UPDATE state SET paused=1")

    def pause(self, at, *, shutdown=False):
        with self.transaction() as sql:
            sql.execute("UPDATE state SET paused=1")
            order = active(sql)
            if order and order.status == "OPEN":
                if shutdown:
                    finish(sql, order, "UNKNOWN", at, "CLOSE_BEFORE_NEXT_REVIEW")
                else:
                    finish(sql, order, "CANCELED", at, "SIMULATION_PAUSED_AT_LAST_REVIEW")

    def resume(self):
        with self.transaction() as sql:
            if not quantities(sql, "opening"):
                raise ValueError("Save an opening portfolio first")
            order = active(sql)
            if order and order.status == "UNKNOWN":
                raise ValueError("Review the unresolved shadow order before resuming")
            sql.execute("UPDATE state SET paused=0")

    def acknowledge(self, at):
        with self.transaction() as sql:
            order = active(sql)
            if order and order.status == "UNKNOWN":
                finish(sql, order, "UNRESOLVED_CLOSED", at, "ACKNOWLEDGED_WITHOUT_ASSUMING_A_FILL")
                sql.execute("UPDATE state SET paused=1")

    def view(self):
        with self.transaction() as sql:
            return view(sql)


def split_schema(script):
    sql = ""
    for line in script.splitlines(keepends=True):
        sql += line
        if sqlite3.complete_statement(sql):
            yield sql
            sql = ""


@dataclass(frozen=True)
class Order:
    id: int
    campaign: int | None
    side: str
    price: D
    quantity: D
    rate: D
    source_cap: D
    started: float
    anchor: str
    horizon: int
    edge: D
    remaining: D
    status: str

    @classmethod
    def from_row(cls, row):
        fields = dict(row)
        for name in ("price", "quantity", "rate", "source_cap", "edge", "remaining"):
            fields[name] = D(fields[name])
        del fields["ended"], fields["reason"]
        return cls(**fields)


def quantities(sql, table):
    query = {"wallet": "SELECT * FROM wallet", "opening": "SELECT * FROM opening"}[table]
    return {row["asset"]: D(row["amount"]) for row in sql.execute(query)}


def active(sql):
    row = sql.execute("SELECT * FROM orders WHERE status IN ('OPEN','UNKNOWN')").fetchone()
    return Order.from_row(row) if row else None


def order_by_id(sql, order_id):
    return Order.from_row(sql.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())


def finish(sql, order, status, at, reason):
    sql.execute("UPDATE orders SET status=?, ended=?, reason=? WHERE id=?", (status, at, reason, order.id))


@native_math
def record_fill(sql, order, evidence, quantity, btc_usd):
    if quantity <= ZERO or quantity > order.remaining or order.status != "OPEN":
        raise ValueError("Invalid conditional fill quantity")
    fee = maker_commission(QUOTE, quantity, order.price, order.rate)
    inserted = sql.execute(
        "INSERT OR IGNORE INTO fills VALUES (?,?,?,?,?,?,?)",
        (
            order.id,
            evidence.trade_id,
            evidence.at,
            str(quantity),
            fee.currency,
            str(fee.amount),
            str(btc_usd),
        ),
    )
    if inserted.rowcount == 0:
        return order
    wallet = quantities(sql, "wallet")
    changes = conversion(BASE, QUOTE, order.side, quantity, order.price, fee)
    updated = {asset: wallet[asset] + changes[asset] for asset in ASSETS}
    if min(updated.values()) < ZERO:
        raise ValueError("Conditional fill exceeds wallet")
    sql.executemany("UPDATE wallet SET amount=? WHERE asset=?", ((str(v), a) for a, v in updated.items()))
    remaining = order.remaining - quantity
    sql.execute("UPDATE orders SET remaining=? WHERE id=?", (str(remaining), order.id))
    if not remaining:
        finish(sql, order, "FILLED", evidence.at, "CONDITIONAL_TRADE_THROUGH")
    return order_by_id(sql, order.id)


@native_math
def verify_ledger(sql):
    wallet = quantities(sql, "opening")
    if set(wallet) not in (set(), set(ASSETS)) or any(v < ZERO or not v.is_finite() for v in wallet.values()):
        raise ValueError("Invalid immutable opening inventory")
    totals = Counter()
    for row in sql.execute(
        "SELECT f.*,o.price,o.rate,o.side FROM fills f JOIN orders o ON o.id=f.order_id ORDER BY f.rowid"
    ):
        credited, price, rate = map(D, (row["quantity"], row["price"], row["rate"]))
        expected = maker_commission(QUOTE, credited, price, rate)
        fee = Commission(row["fee_currency"], D(row["commission"]))
        if fee != expected:
            raise ValueError("Shadow commission ledger fails reconciliation")
        for asset, change in conversion(BASE, QUOTE, row["side"], credited, price, fee).items():
            wallet[asset] += change
        if min(wallet.values()) < ZERO:
            raise ValueError("Shadow ledger has negative source inventory")
        totals[row["order_id"]] += credited
    for row in sql.execute("SELECT * FROM orders"):
        order = Order.from_row(row)
        if (
            order.quantity <= ZERO
            or not ZERO <= order.remaining <= order.quantity
            or order.quantity - order.remaining != totals[order.id]
            or (order.status == "FILLED") != (order.remaining == ZERO)
        ):
            raise ValueError("Shadow order ledger fails reconciliation")
    if wallet != quantities(sql, "wallet"):
        raise ValueError("Shadow inventory fails reconciliation")
    resting = active(sql)
    if resting:
        asset, held = reserve(BASE, QUOTE, resting.side, resting.remaining, resting.price, resting.rate)
        if held > wallet[asset]:
            raise ValueError("Shadow reservation exceeds inventory")


@native_math
def mark(sql, frame, wallet, hold):
    marks = frame.marks
    nav, reference = value(wallet, marks), value(hold, marks)
    past = sql.execute("SELECT peak,drawdown FROM marks ORDER BY at DESC LIMIT 1").fetchone()
    peak = max(nav, D(past["peak"])) if past else nav
    drawdown = max(1 - nav / peak, D(past["drawdown"]) if past else ZERO) if peak else ZERO
    sql.execute(
        "INSERT INTO marks VALUES (?,?,?,?,?,?,?)",
        (frame.at, str(marks[BASE]), str(marks[QUOTE]), str(nav), str(reference), str(peak), str(drawdown)),
    )


@native_math
def view(sql):
    seed, wallet, order = quantities(sql, "opening"), quantities(sql, "wallet"), active(sql)
    state = sql.execute("SELECT * FROM state").fetchone()
    last = sql.execute("SELECT * FROM marks ORDER BY at DESC LIMIT 1").fetchone()
    modeled = ZERO
    for row in sql.execute("SELECT commission FROM fills"):
        modeled += D(row["commission"])
    actual, actual_filled, unknown = Counter(), Counter(), 0
    for row in sql.execute("SELECT commission,fee_currency,side,size,size_unit FROM actual_receipts"):
        if row["size_unit"]:
            actual_filled[row["side"], row["size_unit"]] += D(row["size"])
        if row["fee_currency"] is None:
            unknown += 1
        else:
            actual[row["fee_currency"]] += D(row["commission"])
    reasons = dict(sql.execute("SELECT reason,count FROM rejections"))
    metrics = {}
    if last:
        nav, hold = D(last["nav"]), D(last["hold"])
        metrics = {
            "nav": nav,
            "hold": hold,
            "advantage": nav - hold,
            "pct": (nav - hold) / hold,
            "drawdown": D(last["drawdown"]),
            "at": last["at"],
        }
        for hours in (1, 6, 24):
            boundary = last["at"] - hours * 3600
            past = sql.execute(
                "SELECT nav,hold FROM marks WHERE at<=? AND at>=? ORDER BY at DESC LIMIT 1",
                (boundary, boundary - 90),
            ).fetchone()
            metrics[hours] = nav - hold - (D(past["nav"]) - D(past["hold"])) if past else None
    reservations = {}
    if order:
        asset, held = reserve(BASE, QUOTE, order.side, order.remaining, order.price, order.rate)
        reservations[asset] = held
    forecasts = accuracy(
        (row["horizon"], *(D(row[key]) for key in ("expected", "low", "high", "realized")))
        for row in sql.execute("SELECT * FROM forecasts WHERE status='OBSERVED'")
    )
    return dict(
        seed=seed,
        wallet=wallet,
        order=order,
        paused=state is None or bool(state["paused"]),
        metrics=metrics,
        model_fees=modeled,
        actual_fees=dict(actual),
        unverified_actual_fees=unknown,
        reasons=reasons,
        reservations=reservations,
        forecasts=forecasts,
        missing_forecasts=sql.execute("SELECT COUNT(*) FROM forecasts WHERE status='MISSING'").fetchone()[0],
        quantity_coverage=dict(sql.execute("SELECT status,COUNT(*) FROM orders GROUP BY status")),
        history=[
            dict(row)
            for row in sql.execute(
                "SELECT id,side,quantity,remaining,status,reason FROM orders ORDER BY id DESC LIMIT 6"
            )
        ],
        actual_order_counts=dict(sql.execute("SELECT status,count(*) FROM actual_orders GROUP BY status")),
        actual_filled=dict(actual_filled),
        actual_fill_count=sql.execute("SELECT COUNT(*) FROM actual_receipts").fetchone()[0],
    )
