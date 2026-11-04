"""Bounded Decimal Advanced Trade L2 observations; no execution capabilities.

The wire schema is the official SDK's l2_data / new_quantity schema. Sizes are
absolute levels, never assumed traded volume. Connection-channel sequence scope
is explicit; a discontinuity forces a new connection and snapshot, not repair.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime,timezone
from decimal import Decimal as D,ROUND_FLOOR,ROUND_CEILING
import json
import math
import threading
import time

from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,ETH_PAIRS

MAX_PACKET=8*1024*1024
MAX_LEVELS=16384
MAX_UPDATES=65536


class BookInvalid(ValueError):pass


def utc_stamp(raw):
    if not isinstance(raw,str) or len(raw)>64:raise BookInvalid('BOOK_TIMESTAMP_MISSING')
    try:
        value=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError()
        stamp=value.timestamp()
        if not math.isfinite(stamp):raise ValueError()
        return stamp
    except (ValueError,OverflowError):raise BookInvalid('BOOK_TIMESTAMP_INVALID') from None


@dataclass(frozen=True)
class BookView:
    pair:str
    generation:int
    version:int
    bids:tuple
    asks:tuple
    observed_at:float|None
    received_at:float|None
    state:str
    reason:str
    truncated:bool=False

    def depth(self,side):
        if self.state!='HEALTHY':raise BookInvalid('BOOK_NOT_HEALTHY')
        levels=self.asks if side=='BUY' else self.bids
        return dict(pair=self.pair,side=side,observed_at=self.observed_at,
            levels=[dict(price=p,size=q) for p,q in levels[:128]],
            generation=self.generation,version=self.version,source='ADVANCED_TRADE_LEVEL2_ABSOLUTE')


def display_levels(view,*,tick,multiple=1,quote_amount=False,limit=16):
    """Bucket outward; accumulate from best before reversing displayed asks."""
    step=exact(tick)
    if step<=0 or type(multiple) is not int or multiple not in (1,2,5,10,25,50,100):raise BookInvalid('INVALID_DISPLAY_GROUP')
    if type(quote_amount) is not bool or type(limit) is not int or not 1<=limit<=64:raise BookInvalid('INVALID_DISPLAY_LIMIT')
    step*=multiple;result={}
    for side,levels,up in (('bids',view.bids,False),('asks',view.asks,True)):
        grouped={}
        for price,size in levels:
            bucket=(price/step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*step
            # Quote notional uses each ACTUAL native level price, not its bucket.
            grouped[bucket]=grouped.get(bucket,D(0))+(price*size if quote_amount else size)
        running=D(0);rows=[]
        for price in sorted(grouped,reverse=not up)[:limit]:
            running+=grouped[price];rows.append((price,grouped[price],running))
        result[side]=tuple(reversed(rows)) if up else tuple(rows)
    return result


def scheduled_products(sequence=0,selected=None):
    crosses=[p for p in WATCH_PAIRS if p not in ETH_PAIRS]
    preferred=selected if selected in crosses else crosses[sequence%len(crosses)]
    other=next(p for p in crosses[sequence%len(crosses):]+crosses[:sequence%len(crosses)] if p!=preferred)
    return tuple(ETH_PAIRS)+(preferred,other)


class BookHub:
    def __init__(self,*,max_levels=MAX_LEVELS):
        if type(max_levels) is not int or not 2<=max_levels<=MAX_LEVELS:raise BookInvalid('INVALID_BOOK_BOUND')
        self.max_levels=max_levels;self.lock=threading.RLock();self.generation=0;self.products=()
        self.books={};self.sequence=None;self.last_digest=None;self.heartbeat=None;self.reason='OFF'

    def begin(self,products):
        if not isinstance(products,(tuple,list)) or len(products)>6 or len(set(products))!=len(products) or not set(products)<=set(WATCH_PAIRS):
            raise BookInvalid('BOOK_SUBSCRIPTION_SCOPE_INVALID')
        with self.lock:
            self.generation+=1;self.products=tuple(products);self.books={};self.sequence=None;self.last_digest=None
            self.heartbeat=None;self.reason='AWAIT_SNAPSHOT'
            return self.generation

    def invalidate(self,reason='DISCONNECTED'):
        allowed={'DISCONNECTED','SEQUENCE_GAP','INVALID_PACKET','CROSSED_BOOK','BOOK_BOUND_EXCEEDED',
            'HEARTBEAT_TIMEOUT','OFF','RECONNECT_EXHAUSTED','SUBSCRIPTION_CHANGED','AWAIT_SNAPSHOT'}
        with self.lock:
            self.reason=reason if reason in allowed else 'INVALID_PACKET'
            for book in self.books.values():book['valid']=False

    def apply(self,raw,*,generation,at=None,mono=None):
        at=time.time() if at is None else at;mono=time.monotonic() if mono is None else mono
        with self.lock:
            if generation!=self.generation:return False
            try:
                if isinstance(raw,str):
                    if len(raw.encode())>MAX_PACKET:raise BookInvalid('BOOK_BOUND_EXCEEDED')
                    def reject(value):raise BookInvalid('INVALID_PACKET')
                    data=json.loads(raw,parse_float=D,parse_constant=reject)
                else:data=deepcopy(raw)
                if not isinstance(data,dict):raise BookInvalid('INVALID_PACKET')
                channel=data.get('channel')
                if channel=='subscriptions':return False
                if channel=='heartbeats':
                    events=data.get('events')
                    if not isinstance(events,list) or not 1<=len(events)<=64:raise BookInvalid('INVALID_PACKET')
                    if not 0<=at-utc_stamp(data.get('timestamp'))<=5:raise BookInvalid('HEARTBEAT_TIMEOUT')
                    for event in events:
                        # current_time may be a server-language diagnostic clock;
                        # the protocol's RFC3339 envelope timestamp is authority.
                        if not isinstance(event.get('current_time'),str) or not 1<=len(event['current_time'])<=160:raise BookInvalid('INVALID_PACKET')
                        counter=event.get('heartbeat_counter')
                        if type(counter) not in (str,int) or not str(counter).isdigit() or len(str(counter))>24:
                            raise BookInvalid('INVALID_PACKET')
                    self.heartbeat=mono;return True
                if channel!='l2_data':raise BookInvalid('INVALID_PACKET')
                sequence=data.get('sequence_num')
                if type(sequence) is not int or sequence<0:raise BookInvalid('INVALID_PACKET')
                fingerprint=json.dumps(data,sort_keys=True,default=str)
                if self.sequence is not None:
                    if sequence==self.sequence and fingerprint==self.last_digest:return False
                    if sequence!=self.sequence+1:raise BookInvalid('SEQUENCE_GAP')
                events=data.get('events')
                if not isinstance(events,list) or not 1<=len(events)<=64:raise BookInvalid('INVALID_PACKET')
                staged=dict(self.books)
                for event in events:
                    pair=event.get('product_id')
                    if pair not in self.products or event.get('type') not in ('snapshot','update'):raise BookInvalid('INVALID_PACKET')
                    snapshot=event['type']=='snapshot';updates=event.get('updates')
                    snapshot_at=utc_stamp(data.get('timestamp')) if snapshot else None
                    if snapshot and not 0<=at-snapshot_at<=30:raise BookInvalid('INVALID_PACKET')
                    if not isinstance(updates,list) or len(updates)>MAX_UPDATES:raise BookInvalid('BOOK_BOUND_EXCEEDED')
                    prior=staged.get(pair)
                    if not snapshot and (not prior or not prior['valid']):raise BookInvalid('AWAIT_SNAPSHOT')
                    book=dict(bids={},asks={},at=None,received=None,version=0,valid=True) if snapshot else deepcopy(prior)
                    times=[]
                    for update in updates:
                        side=update.get('side')
                        if side not in ('bid','offer','ask'):raise BookInvalid('INVALID_PACKET')
                        price,size=exact(update.get('price_level')),exact(update.get('new_quantity'))
                        if not D('1e-24')<=price<=D('1e12') or not 0<=size<=D('1e18'):raise BookInvalid('INVALID_PACKET')
                        stamp=utc_stamp(update.get('event_time') or data.get('timestamp'))
                        if stamp>at or (not snapshot and at-stamp>30):raise BookInvalid('INVALID_PACKET')
                        levels=book['bids' if side=='bid' else 'asks']
                        if size:levels[price]=size
                        else:levels.pop(price,None)
                        times.append(stamp)
                    if not book['bids'] or not book['asks']:raise BookInvalid('AWAIT_SNAPSHOT')
                    if max(book['bids'])>=min(book['asks']):raise BookInvalid('CROSSED_BOOK')
                    if max(len(book['bids']),len(book['asks']))>self.max_levels:raise BookInvalid('BOOK_BOUND_EXCEEDED')
                    if times:
                        # Snapshot levels can have old last-change times. A
                        # freshly timestamped complete snapshot is current state.
                        newest=snapshot_at if snapshot else max(times)
                        if book['at'] is not None and newest<book['at']:raise BookInvalid('INVALID_PACKET')
                        book.update(at=newest,received=mono)
                    book['version']=(prior['version'] if prior else 0)+1
                    staged[pair]=book
                self.books=staged;self.sequence=sequence;self.last_digest=fingerprint;self.reason='OBSERVING'
                return True
            except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError,RecursionError) as error:
                reason=str(error) if isinstance(error,BookInvalid) else 'INVALID_PACKET'
                self.invalidate(reason);raise BookInvalid(reason if reason in ('SEQUENCE_GAP','CROSSED_BOOK','BOOK_BOUND_EXCEEDED','AWAIT_SNAPSHOT') else 'INVALID_PACKET') from None

    def view(self,pair,*,at=None,mono=None,limit=128):
        at=time.time() if at is None else at;mono=time.monotonic() if mono is None else mono
        if pair not in WATCH_PAIRS or type(limit) is not int or not 1<=limit<=128:raise BookInvalid('BOOK_VIEW_SCOPE_INVALID')
        with self.lock:
            book=self.books.get(pair)
            state='RESYNCING';reason=self.reason
            if book and book['valid']:
                if self.heartbeat is None or not 0<=mono-self.heartbeat<=5:state='STALE';reason='HEARTBEAT_TIMEOUT'
                elif book['at'] is None or not 0<=at-book['at']<=30:state='STALE';reason='PRODUCT_EVIDENCE_OLDER_THAN_30S'
                else:state='HEALTHY';reason='VISIBLE_LEVEL2_NOT_QUEUE_OR_FILL_EVIDENCE'
            return BookView(pair,self.generation,0 if not book else book['version'],
                () if not book else tuple(sorted(book['bids'].items(),reverse=True)[:limit]),
                () if not book else tuple(sorted(book['asks'].items())[:limit]),
                None if not book else book['at'],None if not book else book['received'],state,reason,
                bool(book and max(len(book['bids']),len(book['asks']))>limit))
