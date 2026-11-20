"""Bounded simulated orders with durable IDs and conservative trade-through fills."""

from .market import BASE, QUOTE
from .money import D, ZERO, native_math, reserve, snap
from .store import active, finish, mark, order_by_id, quantities, record_fill
from .strategy import Candidate, candidate, evaluate, legal_size, strongest

REVIEW_SECONDS = 30
REASSESS_SECONDS = 120
CHILD_SECONDS = 600
CAMPAIGN_SECONDS = 1800
MAX_REPLACEMENTS = 3
TRADE_PARTICIPATION = D(".01")
TRADE_THROUGH_TICKS = 1


def count_reason(sql, reason):
    sql.execute(
        "INSERT INTO rejections VALUES (?,1) ON CONFLICT(reason) DO UPDATE SET count=count+1", (reason,)
    )


def interrupt(sql, order, at, reason):
    if order and order.status == "OPEN":
        finish(sql, order, "UNKNOWN", at, reason)
        sql.execute("UPDATE state SET paused=1")


def lost_evidence(store, at, reason):
    with store.transaction() as sql:
        interrupt(sql, active(sql), at, reason)
        if quantities(sql, "opening"):
            count_reason(sql, reason)


def place(sql, proposal, at, anchor, *, root=None, quantity=None):
    amount = proposal.quantity if quantity is None else quantity
    source_cap = proposal.budget if root is None else root.source_cap
    sql.execute(
        """INSERT INTO orders
        (campaign,side,price,quantity,rate,source_cap,started,anchor,horizon,edge,remaining)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            root.id if root else None,
            proposal.side,
            str(proposal.price),
            str(amount),
            str(proposal.rate),
            str(source_cap),
            at,
            anchor,
            proposal.horizon,
            str(proposal.advantage),
            str(amount),
        ),
    )


@native_math
def fill_covered(sql, order, frame, trades, previous_at, cutoff):
    eligible = [trade for trade in trades if trade.at <= cutoff]
    for trade in eligible:
        if not max(order.started, previous_at) < trade.at:
            continue
        tick = frame.rules.price_step * TRADE_THROUGH_TICKS
        through = (
            trade.price <= order.price - tick if order.side == "BUY" else trade.price >= order.price + tick
        )
        if through:
            size = snap(min(order.remaining, trade.size * TRADE_PARTICIPATION), frame.rules.base_step)
            if size > ZERO:
                order = record_fill(sql, order, trade, size, frame.marks[QUOTE])
                if order.status == "FILLED":
                    break
    return order


@native_math
def unfilled_campaign(sql, root):
    quantity, source = root.quantity, root.source_cap
    for row in sql.execute(
        """SELECT o.side,o.price,o.rate,f.quantity FROM orders o LEFT JOIN fills f
            ON f.order_id=o.id WHERE o.id=? OR o.campaign=?""",
        (root.id, root.id),
    ):
        if row["quantity"] is None:
            continue
        filled = D(row["quantity"])
        quantity -= filled
        source -= reserve(BASE, QUOTE, row["side"], filled, D(row["price"]), D(row["rate"]))[1]
    count = sql.execute("SELECT COUNT(*) FROM orders WHERE campaign=?", (root.id,)).fetchone()[0]
    return count, quantity, source


@native_math
def cancel_or_replace(sql, order, frame, wallet, hold, rate, forecasts, anchor, reason):
    finish(sql, order, "CANCELED", frame.at, reason)
    root = order_by_id(sql, order.campaign) if order.campaign else order
    replacements, remaining, budget = unfilled_campaign(sql, root)
    if (
        replacements >= MAX_REPLACEMENTS
        or frame.at - root.started >= CAMPAIGN_SECONDS
        or not anchor
        or rate != root.rate
    ):
        return
    proposal = candidate(frame, wallet, hold, rate, forecasts, order.side)
    if not isinstance(proposal, Candidate) or not proposal.qualified:
        return
    # A replacement cannot give up price, restore filled quantity, reset age or increase funding.
    improvement = proposal.price <= order.price if order.side == "BUY" else proposal.price >= order.price
    per_base = proposal.budget / proposal.quantity
    quantity = snap(min(remaining, proposal.quantity, budget / per_base), frame.rules.base_step)
    if improvement and legal_size(frame.rules, quantity, proposal.price):
        place(sql, proposal, frame.at, anchor, root=root, quantity=quantity)


def review(sql, order, frame, wallet, hold, rate, forecasts, anchor):
    root = order_by_id(sql, order.campaign) if order.campaign else order
    if rate is None or rate != order.rate or frame.at - root.started >= CAMPAIGN_SECONDS:
        finish(sql, order, "CANCELED", frame.at, "FEE_CHANGED_OR_CAMPAIGN_EXPIRED")
        return
    resting = candidate(
        frame, wallet, hold, rate, forecasts, order.side, resting=(order.price, order.remaining)
    )
    if not isinstance(resting, Candidate) or not resting.qualified:
        finish(sql, order, "CANCELED", frame.at, "RESTING_OPPORTUNITY_NO_LONGER_JUSTIFIED")
        return
    age = frame.at - order.started
    touch = frame.native.bid if order.side == "BUY" else frame.native.ask
    drift = abs(order.price - touch) > 2 * frame.rules.price_step
    if age >= CHILD_SECONDS or (age >= REASSESS_SECONDS and drift):
        cancel_or_replace(
            sql, order, frame, wallet, hold, rate, forecasts, anchor, "CHILD_EXPIRED_OR_LESS_COMPETITIVE"
        )
    elif anchor:
        sql.execute("UPDATE orders SET anchor=? WHERE id=?", (anchor, order.id))


def step(store, frame, rate, forecasts, trades, *, now):
    if not frame.fresh(now):
        lost_evidence(store, now, "STALE_OR_UNSYNCHRONIZED_BOOKS")
        return {}
    with store.transaction() as sql:
        state = sql.execute("SELECT * FROM state").fetchone()
        if not state or frame.native.at <= state["wave"]:
            return {}
        sql.execute("UPDATE state SET wave=?", (frame.native.at,))
        hold, wallet = quantities(sql, "opening"), quantities(sql, "wallet")
        order = active(sql)
        page = [trade for trade in trades if trade.at <= frame.at] if trades is not None else []
        anchor = page[-1].trade_id if page else None
        previous = sql.execute("SELECT MAX(at) FROM marks").fetchone()[0]
        if order and order.status == "OPEN":
            if (
                previous is None
                or frame.at - previous > 2 * REVIEW_SECONDS + 15
                or order.anchor not in {t.trade_id for t in page}
            ):
                interrupt(sql, order, frame.at, "PUBLIC_TRADE_COVERAGE_GAP")
                count_reason(sql, "PUBLIC_TRADE_COVERAGE_GAP")
            else:
                root = order_by_id(sql, order.campaign) if order.campaign else order
                cutoff = min(frame.at, root.started + CAMPAIGN_SECONDS, order.started + CHILD_SECONDS)
                order = fill_covered(sql, order, frame, page, previous, cutoff)
                wallet = quantities(sql, "wallet")
                if order.status == "OPEN":
                    review(sql, order, frame, wallet, hold, rate, forecasts, anchor)
        mark(sql, frame, wallet, hold)
        available = dict(wallet)
        resting = active(sql)
        if resting:
            asset, held = reserve(BASE, QUOTE, resting.side, resting.remaining, resting.price, resting.rate)
            available[asset] -= held
        choices = evaluate(frame, available, hold, rate, forecasts, now=now)
        if not state["paused"] and order is None:
            for entry in choices.values():
                reason = entry.reason if isinstance(entry, Candidate) else entry
                if reason != "QUALIFIED_CONDITIONAL":
                    count_reason(sql, reason)
            proposal = strongest(choices)
            if proposal is not None:
                if anchor is not None:
                    place(sql, proposal, frame.at, anchor)
                else:
                    count_reason(sql, "PUBLIC_TRADE_EVIDENCE_UNAVAILABLE")
        return choices
