"""Optional public-only stream. One bounded receiver; no credentials or broker.

websockets.sync applies receive backpressure instead of dropping queued deltas.
Every message reaches BookHub before the GUI coalesces its immutable views.
"""
import json
import os
import random
import threading
import time

from coincat_order_book import BookHub,BookInvalid,MAX_PACKET,scheduled_products

URL='wss://advanced-trade-ws.coinbase.com'


def public_connection():
    # The pinned SDK's sync websocket transport doesn't implement HTTP CONNECT.
    # Refuse proxy environments instead of silently bypassing their policy.
    if any(os.environ.get(k) for k in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')):
        raise BookInvalid('PUBLIC_STREAM_PROXY_UNSUPPORTED')
    from websockets.sync.client import connect
    return connect(URL,open_timeout=6,close_timeout=1,max_size=MAX_PACKET,
        compression=None,user_agent_header='CoinCat-public-book/1.03beta')


class BookStream:
    def __init__(self,hub,*,connect=public_connection,clock=time.time,monotonic=time.monotonic):
        if not isinstance(hub,BookHub):raise BookInvalid('BOOK_HUB_REQUIRED')
        self.hub=hub;self.connect=connect;self.clock=clock;self.monotonic=monotonic
        self.stop_event=threading.Event();self.wake=threading.Event();self.lock=threading.RLock()
        self.thread=None;self.connection=None;self.selected=None;self.enabled=False
        self.reason='OFF';self.rotation=0;self.failures=0

    def start(self,selected=None):
        if self.thread is not None and self.thread.is_alive():return False
        self.selected=selected;self.stop_event.clear();self.wake.clear();self.enabled=True;self.failures=0
        self.thread=threading.Thread(target=self._run,name='CoinCat-public-L2',daemon=False)
        self.thread.start();return True

    def select(self,pair):
        with self.lock:
            self.selected=pair
            if self.enabled and pair not in self.hub.products:
                self.hub.begin(self.hub.products);self.hub.invalidate('SUBSCRIPTION_CHANGED');self.wake.set()

    def stop(self):
        self.enabled=False;self.stop_event.set();self.wake.set()
        # Invalidate the generation as well as readiness before any late recv.
        # Retain immutable display rows until a new session starts.
        with self.hub.lock:self.hub.generation+=1;self.hub.invalidate('OFF')
        self.reason='OFF'

    def alive(self):return self.thread is not None and self.thread.is_alive()

    def _run(self):
        while not self.stop_event.is_set() and self.failures<5:
            socket=None
            try:
                with self.lock:products=scheduled_products(self.rotation,self.selected)
                generation=self.hub.begin(products);self.wake.clear();self.reason='CONNECTING'
                socket=self.connect();self.connection=socket;started=self.monotonic()
                for channel in ('level2','heartbeats'):
                    socket.send(json.dumps(dict(type='subscribe',product_ids=list(products),channel=channel)))
                self.reason='OBSERVING';healthy_since=None
                while not self.stop_event.is_set() and not self.wake.is_set():
                    now=self.monotonic()
                    heartbeat=self.hub.heartbeat
                    if now-started>5 and (heartbeat is None or now-heartbeat>5):raise BookInvalid('HEARTBEAT_TIMEOUT')
                    if now-started>=60:
                        self.rotation+=1;break
                    try:packet=socket.recv(timeout=1)
                    except TimeoutError:
                        heartbeat=self.hub.heartbeat
                        if now-started>5 and (heartbeat is None or now-heartbeat>5):raise BookInvalid('HEARTBEAT_TIMEOUT')
                        continue
                    if not isinstance(packet,str):raise BookInvalid('INVALID_PACKET')
                    if self.stop_event.is_set() or self.wake.is_set():break
                    self.hub.apply(packet,generation=generation,at=self.clock(),mono=self.monotonic())
                    if self.hub.heartbeat is not None:
                        if healthy_since is None:healthy_since=self.monotonic()
                        if self.monotonic()-healthy_since>=15:self.failures=0
                self.hub.invalidate('OFF' if self.stop_event.is_set() else 'SUBSCRIPTION_CHANGED')
            except Exception:
                self.failures+=1;self.reason='RESYNCING';self.hub.invalidate('DISCONNECTED')
            finally:
                self.connection=None
                if socket is not None:
                    try:socket.close()
                    except Exception:pass
            if self.stop_event.is_set():break
            if self.failures:
                self.stop_event.wait(min(16,2**(self.failures-1))+random.uniform(0,.25))
        if self.failures>=5:
            self.reason='RECONNECT_EXHAUSTED';self.hub.invalidate('RECONNECT_EXHAUSTED')
        self.enabled=False

    def public(self):
        views=[self.hub.view(p,at=self.clock(),mono=self.monotonic()) for p in self.hub.products]
        return dict(state='OFF' if not self.enabled and self.reason=='OFF' else
            'HEALTHY' if views and all(v.state=='HEALTHY' for v in views) else
            'UNAVAILABLE' if self.reason=='RECONNECT_EXHAUSTED' else 'RESYNCING',
            subscribed=len(views),healthy=sum(v.state=='HEALTHY' for v in views),
            provider='PUBLIC_LEVEL2_OBSERVATION',queue_or_fills_verified=False)
