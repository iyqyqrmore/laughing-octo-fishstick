"""Public all-catalog Advanced Trade ticker telemetry (OBSERVATION ONLY).

Ticker-batch last-trade events (~5s when changed) are not executable bid/ask, an order-book, or a
promise that an illiquid pair updates every few seconds. No database, account
credential, order authorization or broker API is touched here. The eligible
product list comes solely from the authenticated, active spot catalog.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from threading import Event, Lock, Thread
import json, time

PUBLIC_URL = 'wss://advanced-trade-ws.coinbase.com'
PUBLIC_CHANNEL = 'ticker_batch'  # ~5-second change events; no executable bid/ask
MAX_MARKETS = 3500                 # bounded even if Coinbase catalog expands
SUBSCRIBE_BATCH = 40               # tame subscription message size/burst
SUBSCRIBE_GAP_SECONDS = 0.12       # at most ~8 subscription messages/s


def ticker_updates(message):
    """Validate last matched price events; NEVER infer an executable quote."""
    try:
        data = json.loads(message) if isinstance(message, str) else message
        if not isinstance(data, dict) or data.get('channel') not in ('ticker', 'ticker_batch'):
            return []
        output = []
        for event in data.get('events', []):
            if not isinstance(event, dict):
                continue
            for ticker in event.get('tickers', []):
                if not isinstance(ticker, dict):
                    continue
                pair = ticker.get('product_id', '')
                if not isinstance(pair, str) or '-' not in pair:
                    continue
                try:
                    value = Decimal(str(ticker.get('price', '')))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if not value.is_finite() or value <= 0:
                    continue
                output.append((pair, str(value)))
        return output
    except (ValueError, TypeError):
        return []


class PublicTickerTape:
    """One bounded, read-only market stream; no orders and no REST price cache."""
    def __init__(self, connector=None, on_tick=None):
        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._socket = None
        self._connector = connector
        self._on_tick = on_tick
        self._pairs = ()
        self._pair_set = frozenset()
        self._prices = {}
        self._connected = False
        self._error = 'Not started'
        self._ticks = 0
        self._last_message = 0.0
        self._last_heartbeat = 0.0
        self._mono_last_message = 0.0
        self._mono_last_heartbeat = 0.0
        self._started = False
        self._subscribed_requested = 0
        self._truncated = 0

    def set_pairs(self, pairs):
        # Deterministic sorting prevents reconnection churn when a focus cohort
        # changes. The socket restarts only if the AUTHENTICATED catalog changes.
        candidate = sorted(set(p for p in pairs if isinstance(p, str) and '-' in p))
        chosen = tuple(candidate[:MAX_MARKETS])
        with self._lock:
            self._truncated = max(0, len(candidate)-len(chosen))
            if chosen == self._pairs:
                return
            self._pairs = chosen
            self._pair_set = frozenset(chosen)
            self._prices = {p:v for p,v in self._prices.items() if p in chosen}
            self._last_message = 0.0
            self._mono_last_message = 0.0
            self._subscribed_requested = 0
            ws = self._socket
        if ws is not None:
            try: ws.close()
            except Exception: pass

    def status(self, now=None, row_limit=24, search=''):
        now = time.time() if now is None else float(now)
        with self._lock:
            prices = dict(self._prices)
            connected = self._connected
            last = self._last_message
            heartbeat = self._last_heartbeat
            error = self._error
            pairs = tuple(self._pairs)
            ticks = self._ticks
            requested = self._subscribed_requested
            truncated = self._truncated
            mono_last = self._mono_last_message
            mono_heartbeat = self._mono_last_heartbeat
        # Monotonic age avoids negative age caused by wall-clock corrections.
        # Never treat a large mismatch with supplied wall clock as a trade signal.
        mono_now = time.monotonic()
        fresh = 0
        recent = 0
        for price, when in prices.values():
            # Stored per-event monotonic timestamps; older manually fabricated
            # snapshots may contain wall timestamps and should be treated stale.
            age = mono_now-when
            if connected and 0 <= age < 15: fresh += 1
            if 0 <= age < 120: recent += 1
        term = str(search or '').strip().upper()
        # Display recently traded markets first, not the first alphabetically.
        ranked = sorted((p for p in pairs if (not term or term in p)),
                        key=lambda p: (0 if p in prices else 1,
                                      -(prices[p][1] if p in prices else 0),p))
        items = []
        for p in ranked[:max(0, int(row_limit))]:
            quote = prices.get(p)
            age = int(max(0, mono_now-quote[1])) if quote else None
            items.append(dict(pair=p, last=quote[0] if quote else None,
                              age=age, fresh=bool(connected and age is not None and age < 15)))
        hb_age = int(max(0, mono_now-mono_heartbeat)) if mono_heartbeat else None
        return dict(connected=connected, error=error, ticks=ticks, pairs=len(pairs),
                    requested=requested, truncated=truncated,
                    observed=len(prices), recent_120s=recent, fresh=fresh,
                    last_message_age=(int(max(0,mono_now-mono_last)) if mono_last else None),
                    observed_unique_products=len(prices),
                    freshness_definition='changed trades in previous 15 seconds, not subscription coverage',
                    heartbeat_age=hb_age, rows=items, matching=len(ranked))

    def _receive(self, raw):
        ts = time.time()
        mono_ts = time.monotonic()
        values = ticker_updates(raw)
        try: data = json.loads(raw) if isinstance(raw,str) else raw
        except (ValueError, TypeError): data = {}
        if not isinstance(data, dict): data = {}
        accepted=[]
        with self._lock:
            if data.get('channel') == 'heartbeats':
                self._last_heartbeat = ts
                self._mono_last_heartbeat = mono_ts
            if data.get('channel') == 'error' or data.get('type') == 'error':
                # Server-side subscription failures can leave a socket open.
                self._error = 'Exchange subscription error: ' + str(data.get('message','unknown'))[:90]
            if values:
                self._last_message = ts
                self._mono_last_message = mono_ts
            for pair, price in values:
                if pair in self._pair_set:
                    self._prices[pair] = (price, mono_ts)
                    self._ticks += 1
                    accepted.append((pair,price))
        # The callback can only feed an IN-MEMORY scout heuristic; never orders.
        if self._on_tick:
            for pair,price in accepted:
                try: self._on_tick(pair,price,ts)
                except Exception: pass

    def start(self):
        with self._lock:
            if self._started: return
            self._started = True
        self._thread = Thread(target=self._run, name='CoinCatAllSpotPublicTicker', daemon=True)
        self._thread.start()

    def _run(self):
        pause = 1.0
        while not self._stop.is_set():
            with self._lock: pairs = self._pairs
            if not pairs:
                self._stop.wait(2)
                continue
            try:
                if self._connector is None:
                    import websocket  # websocket-client, PUBLIC channel, no CDP key
                    connector = lambda **kw: websocket.WebSocketApp(PUBLIC_URL, **kw)
                else: connector = self._connector
                def on_open(ws):
                    with self._lock:
                        self._connected = True
                        self._error = ''
                        self._subscribed_requested = 0
                    # Keep the connection alive during staggered subscription.
                    ws.send(json.dumps({'type':'subscribe','channel':'heartbeats'}))
                    for start in range(0,len(pairs),SUBSCRIBE_BATCH):
                        if self._stop.is_set(): break
                        with self._lock:
                            if pairs != self._pairs: break
                        batch = pairs[start:start+SUBSCRIBE_BATCH]
                        ws.send(json.dumps({'type':'subscribe','product_ids':list(batch),'channel':PUBLIC_CHANNEL}))
                        with self._lock:
                            self._subscribed_requested += len(batch)
                        if start+SUBSCRIBE_BATCH < len(pairs) and self._stop.wait(SUBSCRIBE_GAP_SECONDS):
                            break
                def on_error(ws,err):
                    with self._lock: self._error = type(err).__name__ + ': ' + str(err)[:100]
                def on_close(ws,*_):
                    with self._lock: self._connected = False
                sock = connector(on_message=lambda ws,msg:self._receive(msg),
                                 on_open=on_open,on_error=on_error,on_close=on_close)
                with self._lock: self._socket = sock
                sock.run_forever(ping_interval=30, ping_timeout=10)
                pause = min(max(2.0,pause*1.8),30.0)
            except Exception as exc:
                with self._lock: self._error = type(exc).__name__ + ': ' + str(exc)[:100]
                pause = min(pause*2,30.0)
            finally:
                with self._lock:
                    self._socket = None
                    self._connected = False
                    self._subscribed_requested = 0
            self._stop.wait(pause)

    def close(self):
        self._stop.set()
        with self._lock: sock = self._socket
        if sock is not None:
            try: sock.close()
            except Exception: pass
