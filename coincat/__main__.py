"""CoinCat v1.07 Tkinter entry point."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import os
import sqlite3
import time
import tkinter as tk
from tkinter import messagebox, ttk
from queue import Empty

from . import VERSION
from .forecast import NAMES
from .market import BASE, QUOTE, PRODUCT
from .money import D, decimal
from .store import DATA, Store
from .strategy import Candidate, strongest
from .theme import apply_theme, BLUE, GREEN, MUTED, RED
from .worker import Reader

ASSETS = Path(__file__).with_name("assets")
LABELS = {
    "AUTHENTICATED_MAKER_FEE_UNVERIFIED": "Authenticated maker fee unavailable",
    "NO_POSITIVE_RISK_ADJUSTED_ADVANTAGE": "No positive risk-adjusted advantage",
    "TARGET_CONCENTRATION_LIMIT": "Destination concentration exceeds limit",
    "SOURCE_BUDGET_BELOW_NATIVE_MINIMUM": "Source budget below native minimum",
    "PUBLIC_TRADE_COVERAGE_GAP": "Public trade evidence gap",
    "MARKET_OR_RECONCILIATION_UNAVAILABLE": "Market data or reconciliation unavailable",
    "PUBLIC_TRADE_EVIDENCE_UNAVAILABLE": "Public trade evidence unavailable",
    "QUALIFIED_CONDITIONAL": "Qualified under conditional maker assumptions",
}


def label(code):
    return LABELS.get(code, code.replace("_", " ").capitalize())


def dollars(amount):
    return "—" if amount is None else f"{amount:+,.4f} USD"


def native(amount):
    return (
        format(amount, "f").rstrip("0").rstrip(".")
        if amount and amount.as_tuple().exponent < 0
        else format(amount, "f")
    )


@contextmanager
def installation_lock(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "app.lock"
    if path.is_symlink():
        raise ValueError("Application lock is a symbolic link")
    with path.open("a+b") as file:
        if os.name == "nt":
            from msvcrt import locking, LK_NBLCK

            file.seek(0)
            locking(file.fileno(), LK_NBLCK, 1)
        else:
            from fcntl import flock, LOCK_EX, LOCK_NB

            flock(file, LOCK_EX | LOCK_NB)
        yield


def disable_windows_minimize(root):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        root.update_idletasks()
        parent = user32.GetParent
        parent.argtypes = (wintypes.HWND,)
        parent.restype = wintypes.HWND
        hwnd = parent(root.winfo_id()) or root.winfo_id()
        read, write = user32.GetWindowLongW, user32.SetWindowLongW
        read.argtypes = (wintypes.HWND, ctypes.c_int)
        write.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        style = read(hwnd, -16)
        if style:
            write(hwnd, -16, style & ~0x00020000)
            position = user32.SetWindowPos
            position.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            )
            position(hwnd, None, 0, 0, 0, 0, 0x0027)


class Dashboard:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.reader = Reader(store)
        self.choices = {}
        self.horizons = ()
        self.connection = tk.StringVar(value="Waiting for synchronized market data")
        self.portfolio = tk.StringVar()
        self.performance = tk.StringVar()
        self.inventory = tk.StringVar()
        self.orders = tk.StringVar()
        self.fees = tk.StringVar()
        self.outcomes = tk.StringVar()
        self.decision = tk.StringVar()
        self.status = tk.StringVar()
        self.opening = {asset: tk.StringVar() for asset in (BASE, QUOTE)}
        apply_theme(root)
        root.title(f"CoinCat v{VERSION} | Intelligent One-Leg Maker")
        root.geometry("1010x760")
        root.minsize(790, 610)
        self.build()
        self.render()
        disable_windows_minimize(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.reader.thread.start()
        root.after(250, self.refresh)

    def build(self):
        root = self.root
        top = ttk.Frame(root, padding=(17, 12))
        top.pack(fill="x")
        try:
            root.iconbitmap(default=str(ASSETS / "CoinCat50.ico"))
        except tk.TclError:
            pass
        logo = tk.PhotoImage(file=ASSETS / "coincat_logo_transparent.png")
        factor = max(1, max(logo.width(), logo.height()) // 45)
        self.logo = logo.subsample(factor)
        ttk.Label(top, image=self.logo).pack(side="left", padx=(0, 11))
        ttk.Label(top, style="Title.TLabel", text=f"CoinCat v{VERSION}").pack(side="left")
        ttk.Label(top, text="SHADOW ONLY  ·  LIVE TRADING DISABLED", foreground=BLUE).pack(side="right")
        summary = ttk.Frame(root, padding=(17, 4))
        summary.pack(fill="x")
        ttk.Label(
            summary, text="Net modeled portfolio USD advantage vs original HOLD", style="Muted.TLabel"
        ).pack(anchor="w")
        self.headline = ttk.Label(summary, textvariable=self.portfolio, style="Title.TLabel")
        self.headline.pack(anchor="w", pady=(2, 4))
        for variable in (self.performance, self.inventory):
            ttk.Label(summary, textvariable=variable, wraplength=750, justify="left").pack(anchor="w")
        tabs = ttk.Notebook(root)
        tabs.pack(expand=True, fill="both", padx=17, pady=9)
        opportunity = ttk.Frame(tabs, padding=(12, 8))
        evidence = ttk.Frame(tabs, padding=(12, 8))
        tabs.add(opportunity, text="Opportunity")
        tabs.add(evidence, text="Orders and evidence")
        ttk.Label(opportunity, textvariable=self.decision, style="Metric.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        self.candidate_text = tk.StringVar()
        ttk.Label(opportunity, textvariable=self.candidate_text, justify="left", wraplength=745).pack(
            anchor="w"
        )
        self.forecast_text = tk.StringVar()
        ttk.Label(
            opportunity, textvariable=self.forecast_text, style="Muted.TLabel", justify="left", wraplength=745
        ).pack(anchor="w", pady=(9, 0))
        for variable in (self.orders, self.fees, self.outcomes):
            ttk.Label(evidence, textvariable=variable, justify="left", wraplength=745).pack(
                anchor="w", pady=(0, 9)
            )
        controls = ttk.Frame(root, padding=(17, 0, 17, 8))
        controls.pack(fill="x")
        self.seed_row = ttk.Frame(controls)
        self.seed_row.pack(fill="x", pady=(0, 5))
        ttk.Label(self.seed_row, text="Opening HOLD quantities").pack(side="left", padx=(0, 8))
        for asset, variable in self.opening.items():
            ttk.Label(self.seed_row, text=asset).pack(side="left", padx=(4, 3))
            ttk.Entry(self.seed_row, textvariable=variable, width=16).pack(side="left")
        ttk.Button(self.seed_row, text="Freeze opening HOLD", command=self.seed).pack(side="left", padx=7)
        bar = ttk.Frame(controls)
        bar.pack(fill="x")
        self.start = ttk.Button(bar, text="Start shadow", style="Accent.TButton", command=self.resume)
        self.pause = ttk.Button(bar, text="Pause", command=self.pause_shadow)
        self.resolve = ttk.Button(bar, text="Acknowledge unresolved order", command=self.resolve_shadow)
        for button in (self.start, self.pause, self.resolve):
            button.pack(side="left", padx=(0, 7))
        ttk.Label(controls, textvariable=self.connection, foreground=MUTED, wraplength=745).pack(
            anchor="w", pady=(6, 0)
        )
        ttk.Label(controls, textvariable=self.status, foreground=MUTED, wraplength=745).pack(anchor="w")

    def command(self, action):
        try:
            action()
            self.render()
        except (ValueError, ArithmeticError, sqlite3.Error):
            messagebox.showerror(
                "CoinCat", "The action could not be saved. Check portfolio input and shadow state."
            )
        self.reader.wake.set()

    def seed(self):
        if messagebox.askokcancel(
            "Freeze opening HOLD", "Use these actual starting quantities as the immutable shadow benchmark?"
        ):
            self.command(
                lambda: self.store.seed({asset: decimal(var.get()) for asset, var in self.opening.items()})
            )

    def resume(self):
        self.reader.invalidate_fee.set()
        self.command(self.store.resume)

    def pause_shadow(self):
        self.choices = {}
        self.command(lambda: self.store.pause(time.time()))

    def resolve_shadow(self):
        if messagebox.askokcancel(
            "Unresolved shadow order", "Archive the unknown remainder without assuming a simulated fill?"
        ):
            self.command(lambda: self.store.acknowledge(time.time()))

    def refresh(self):
        try:
            update = self.reader.messages.get_nowait()
        except Empty:
            pass
        else:
            self.connection.set(f"{update.message}  ·  {update.fee_status}  ·  {update.forecast_status}")
            self.choices = update.choices
            self.horizons = update.horizons
            try:
                self.render()
            except (ValueError, sqlite3.Error):
                self.status.set("Shadow state unavailable")
        self.root.after(500, self.refresh)

    def render(self):
        state = self.store.view()
        metric = state["metrics"]
        if metric:
            stamp = datetime.fromtimestamp(metric["at"]).strftime("%Y-%m-%d %H:%M:%S")
            self.portfolio.set(f"{dollars(metric['advantage'])}  ({metric['pct']:+.4%})")
            self.headline.configure(
                foreground=GREEN if metric["advantage"] > 0 else RED if metric["advantage"] < 0 else MUTED
            )
            changes = "  ·  ".join(f"{hours}h {dollars(metric[hours])}" for hours in (1, 6, 24))
            self.performance.set(
                f"Modeled {metric['nav']:,.2f} USD  ·  HOLD {metric['hold']:,.2f} USD  ·  "
                f"Drawdown {metric['drawdown']:.2%}\n{changes}  ·  Mark {stamp}"
            )
        else:
            self.portfolio.set("Awaiting synchronized USD marks")
            self.performance.set("")
        self.inventory.set(
            "Inventory  " + "  ·  ".join(f"{native(q)} {asset}" for asset, q in state["wallet"].items())
            if state["wallet"]
            else "Enter opening ETH and BTC quantities to establish HOLD"
        )
        active = state["order"]
        self.status.set("Paused" if state["paused"] else "Shadow research running")
        if state["seed"]:
            self.seed_row.pack_forget()
        self.start.configure(
            state="normal" if state["seed"] and state["paused"] and not active else "disabled"
        )
        self.pause.configure(state="disabled" if state["paused"] else "normal")
        self.resolve.configure(state="normal" if active and active.status == "UNKNOWN" else "disabled")
        self.render_candidates(state)
        self.render_evidence(state)

    def render_candidates(self, state):
        active, best = state["order"], strongest(self.choices)
        decision = "HOLD"
        if active:
            decision = (
                f"{active.status}  ·  SIM-{active.id}  ·  {active.side} {PRODUCT}  ·  "
                f"{NAMES[active.horizon]} at proposal"
            )
        elif best and not state["paused"]:
            decision = f"{best.side} qualifies for shadow proposal"
        self.decision.set(decision)
        rows = []
        for side, entry in self.choices.items():
            if not isinstance(entry, Candidate):
                rows.append(f"{PRODUCT} {side}  ·  {label(entry)}")
                continue
            rows.append(
                f"{PRODUCT} {side} {BASE}  ·  {label(entry.reason)}\n"
                f"Fund {native(entry.budget)} {entry.funding}  ·  Receive {native(entry.destination)} {entry.target}  ·  "
                f"Limit {native(entry.price)} BTC/ETH\n"
                f"Own maker commission {native(entry.fee.amount)} {entry.fee.currency} (estimated)  ·  "
                f"Immediate {dollars(entry.immediate)}  ·  Post-trade vs HOLD {dollars(entry.versus_hold)}\n"
                f"{NAMES[entry.horizon]}  ·  Risk-adjusted change {dollars(entry.advantage)}  ·  "
                + (
                    f"Relative interval width {entry.uncertainty_pct:.2%} ({entry.observations} validation outcomes)"
                    if entry.horizon
                    else "Synchronized USD midpoints"
                )
            )
        self.candidate_text.set("\n\n".join(rows))
        horizons = [
            f"{NAMES[h.horizon]} {h.estimate:+.2%} [{h.lower:+.2%}, {h.upper:+.2%}]" for h in self.horizons
        ]
        self.forecast_text.set(
            "Expected ETH/BTC change and validation bounds\n" + "  ·  ".join(horizons) if horizons else ""
        )

    def render_evidence(self, state):
        held = "  ·  ".join(f"{native(q)} {asset}" for asset, q in state["reservations"].items()) or "None"
        orders = [f"Shadow reservations  {held}"]
        for row in state["history"]:
            total, remaining = D(row["quantity"]), D(row["remaining"])
            orders.append(
                f"SIM-{row['id']}  {row['side']}  {row['status']}  ·  "
                f"Filled {native(total - remaining)} ETH  ·  Remaining {native(remaining)} ETH"
            )
        self.orders.set("\n".join(orders))
        actual = "  ·  ".join(f"{native(q)} {asset}" for asset, q in state["actual_fees"].items()) or "—"
        order_counts = (
            ", ".join(f"{status} {n}" for status, n in state["actual_order_counts"].items())
            or "none imported"
        )
        sizes = "  ·  ".join(
            f"{side} {native(q)} {asset}" for (side, asset), q in state["actual_filled"].items()
        )
        self.fees.set(
            f"Cumulative modeled commission  {native(state['model_fees'])} BTC\n"
            f"Actual order evidence  {order_counts}  ·  Fill receipts {state['actual_fill_count']}\n"
            + (f"Actual filled with verified size units  {sizes}\n" if sizes else "")
            + f"Cumulative actual commission  {actual}  ·  Currency unverified on {state['unverified_actual_fees']} receipts"
        )
        rejects = (
            "  ·  ".join(f"{label(reason)} {count}" for reason, count in state["reasons"].items()) or "—"
        )
        forecasts = (
            "  ·  ".join(
                f"{h} MAE {entry['mae']:.2%} / coverage {entry['interval_coverage']:.0%}"
                for h, entry in state["forecasts"].items()
            )
            or "Pending evidence"
        )
        self.outcomes.set(
            f"Rejected candidates  {rejects}\nProspective forecasts  {forecasts}"
            f"  ·  Missing outcomes {state['missing_forecasts']}"
        )

    def close(self):
        self.reader.stop.set()
        self.reader.wake.set()
        try:
            self.store.pause(time.time(), shutdown=True)
        except (ValueError, sqlite3.Error):
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        with installation_lock(DATA):
            store = Store()
            store.recover(time.time())
            Dashboard(root, store)
            root.mainloop()
    except (ValueError, OSError, sqlite3.Error):
        messagebox.showerror("CoinCat", "The shadow database needs review or CoinCat is already open.")
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
