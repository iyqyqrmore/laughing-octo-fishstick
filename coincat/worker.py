"""One background reader. The Tk view never performs exchange requests."""

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
import sqlite3
import time

from .market import Coinbase, MarketUnavailable
from .observations import Observations
from .shadow import REVIEW_SECONDS, lost_evidence, step

READ_ERRORS = (
    MarketUnavailable,
    KeyError,
    IndexError,
    TypeError,
    ValueError,
    ArithmeticError,
    OSError,
    ImportError,
)


@dataclass
class Update:
    message: str
    choices: dict
    forecast_status: str
    fee_status: str
    horizons: tuple


class Reader:
    def __init__(self, store):
        self.store = store
        self.exchange = Coinbase()
        self.forecasts = Observations(store.path.parent / "market")
        self.messages = Queue(maxsize=1)
        self.stop = Event()
        self.invalidate_fee = Event()
        self.wake = Event()
        self.fees = None
        self.fee_time = 0
        self.thread = Thread(target=self.run, daemon=True, name="CoinCat read-only worker")

    def run(self):
        while not self.stop.is_set():
            started = time.monotonic()
            update = self.poll()
            try:
                self.messages.get_nowait()
            except Empty:
                pass
            self.messages.put_nowait(update)
            self.wake.wait(max(0, REVIEW_SECONDS - (time.monotonic() - started)))
            self.wake.clear()

    def poll(self):
        message, choices, fee_status = "Synchronized market books", {}, "Unverified"
        forecasts = ()
        try:
            now = time.time()
            if self.invalidate_fee.is_set() or not 0 <= now - self.fee_time < 900:
                self.invalidate_fee.clear()
                self.fee_time = now
                try:
                    self.fees = self.exchange.fees() if self.exchange.has_credentials else None
                except READ_ERRORS:
                    self.fees = None
            if self.fees:
                fee_status = f"{self.fees.maker * 100:f}% verified spot maker rate"
            # Reconcile only public trades whose exchange timestamp precedes the mark.
            frame = self.exchange.snapshot()
            forecasts = self.forecasts.supported(frame.at)
            if not self.stop.is_set():
                state = self.store.view()
                trades = None
                if not state["paused"]:
                    try:
                        trades = self.exchange.trades()
                    except READ_ERRORS:
                        message = "Public trade evidence unavailable"
                if not self.stop.is_set():
                    choices = step(
                        self.store,
                        frame,
                        self.fees.maker if self.fees else None,
                        forecasts,
                        trades,
                        now=time.time(),
                    )
            if not self.stop.is_set():
                self.forecasts.obtain(self.exchange, self.store, time.time())
        except READ_ERRORS:
            if not self.stop.is_set():
                try:
                    lost_evidence(self.store, time.time(), "MARKET_OR_RECONCILIATION_UNAVAILABLE")
                except (ValueError, sqlite3.Error):
                    pass
            message = "Market data or reconciliation unavailable"
        except sqlite3.Error:
            message = "SQLite state currently unavailable"
        return Update(message, choices, self.forecasts.status, fee_status, forecasts if choices else ())
