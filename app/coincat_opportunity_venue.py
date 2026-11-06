"""Conservative public-trade-through queue assumptions, never exchange fills."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal as D
import hashlib
import re

from coincat_assumed_math import rounded,fee_rate
from coincat_beta_store import BetaBlocked,digest
from coincat_execution_limits import native_math
from coincat_order_services import ticket_values
from coincat_portfolio_policy import valid_book
from coincat_shadow_source import ShadowMarketSource
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS

def parse_trades(raw,pair,at):
    rows=raw.get('trades') if isinstance(raw,dict) else None
    if pair not in WATCH_PAIRS or not isinstance(rows,list) or len(rows)>100:raise BetaBlocked('PUBLIC_TRADE_BATCH_UNVERIFIED')
    result={}
    for row in rows:
        if not isinstance(row,dict) or row.get('product_id')!=pair:raise BetaBlocked('PUBLIC_TRADE_PRODUCT_UNVERIFIED')
        ref=row.get('trade_id');price,size=exact(row.get('price')),exact(row.get('size'))
        if not isinstance(ref,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ref) or not 0<price<=D('1e12') or not 0<size<=D('1e18'):
            raise BetaBlocked('PUBLIC_TRADE_NATIVE_VALUES_UNVERIFIED')
        try:
            stamp=datetime.fromisoformat(row['time'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            when=stamp.timestamp()
            if not 0<when<=at:raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):raise BetaBlocked('PUBLIC_TRADE_TIME_UNVERIFIED') from None
        value=dict(id=ref,price=price,size=size,at=when)
        if ref in result and result[ref]!=value:raise BetaBlocked('PUBLIC_TRADE_ID_CONFLICT')
        result[ref]=value
    return dict(pair=pair,at=at,prints=sorted(result.values(),key=lambda p:(p['at'],p['id'])),
        source='COINBASE_AUTH_MARKET_TRADES',aggressor_side='NOT_INFERRED')

class OpportunitySource:
    """Shares the existing sixteen-call paced wave; at most one extra native GET."""
    def __init__(self,reader,base=None):self.reader=reader;self.base=base or ShadowMarketSource(reader)
    def collect(self,pair=None):
        frame=self.base.collect();frame['market_trades']=None;frame['trade_status']='NO_ACTIVE_ORDER'
        if pair is not None and frame.get('state')=='OBSERVED':
            if pair not in WATCH_PAIRS:raise BetaBlocked('OPPORTUNITY_TRADE_SCOPE_REJECTED')
            try:
                raw=self.reader.call('get_market_trades',product_id=pair,limit=100)
                frame['market_trades']=parse_trades(raw,pair,self.reader.clock());frame['trade_status']='OBSERVED_PUBLIC_TRADES'
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                frame['trade_status']=str(exc) if isinstance(exc,BetaBlocked) else 'PUBLIC_TRADES_UNAVAILABLE'
        frame['at']=self.reader.clock();return frame

@native_math
def queue_ahead(order,book,config):
    levels=book.get('bids' if order['side']=='BUY' else 'asks')
    if not isinstance(levels,(list,tuple)) or not levels:raise BetaBlocked('VISIBLE_QUEUE_DEPTH_UNAVAILABLE')
    ahead=sum((exact(q) for p,q in levels if (exact(p)>=order['price'] if order['side']=='BUY' else exact(p)<=order['price'])),D(0))
    return (ahead+order['size'])*config.queue_multiple

def anchors(batch):return {p['id']:digest(p) for p in batch['prints']}

@native_math
def accept(order,frame,config,now):
    book=valid_book(frame,order['pair'],admission=False)
    ticket_values(order,frame['rules'][order['pair']],book)
    batch=frame.get('market_trades')
    if batch is None or batch['pair']!=order['pair']:raise BetaBlocked('WAIT_FOR_PUBLIC_TRADE_ANCHOR')
    order.update(state='OPEN',accepted_at=now)
    order['venue']=dict(seen=anchors(batch),queue_left=queue_ahead(order,book,config),through_count=0,
        first_through_at=None,last_through_at=None,data_state='QUEUE_IS_A_DECLARED_ASSUMPTION')

@native_math
def modeled_fill(order,frame,config,now):
    """Strict trade prices + continuity + volume + rest; touching quotes is inert."""
    if config.provider=='NO_FILL_OBSERVATION_V1':return None
    batch=frame.get('market_trades');meta=order.get('venue')
    if batch is None or meta is None or batch.get('pair')!=order['pair'] or not 0<=now-batch['at']<=30:
        if meta is not None:meta['data_state']='PUBLIC_TRADE_EVIDENCE_UNAVAILABLE'
        return None
    valid_book(frame,order['pair'],admission=False);seen=anchors(batch)
    old=meta['seen']
    if any(seen[k]!=old[k] for k in old.keys()&seen.keys()):raise BetaBlocked('PUBLIC_TRADE_REPEATED_ID_CHANGED')
    if old and seen and not old.keys()&seen.keys():
        meta.update(seen=seen,queue_left=queue_ahead(order,frame['books'][order['pair']],config),through_count=0,
            first_through_at=None,last_through_at=None,data_state='TRADE_WINDOW_GAP_NO_FILL')
        return None
    if not old:
        meta['seen']=seen;meta['data_state']='NEW_TRADE_ANCHOR_NO_BACKFILL';return None
    cutoff=order.get('cancel_requested_at',now)
    fresh=[p for p in batch['prints'] if p['id'] not in old and order['accepted_at']<p['at']<=min(now,cutoff)]
    meta['seen']=seen
    through=[p for p in fresh if (p['price']<order['price'] if order['side']=='BUY' else p['price']>order['price'])]
    if not through:meta['data_state']='NO_STRICT_TRADE_THROUGH';return None
    if meta['first_through_at'] is None:meta['first_through_at']=through[0]['at']
    meta['last_through_at']=through[-1]['at'];meta['through_count']+=len(through)
    volume=sum((p['size'] for p in through),D(0))*config.participation
    before=meta['queue_left'];meta['queue_left']=max(D(0),before-volume)
    surplus=max(D(0),volume-before)
    meta['data_state']='CONDITIONAL_TRADE_THROUGH_QUEUE_MODEL'
    if (now-order['accepted_at']<config.minimum_rest_s or meta['through_count']<3 or
            meta['last_through_at']-meta['first_through_at']<10 or surplus<=0):return None
    inc=exact(order['rules']['base_increment']);remaining=order['size']-order['filled']
    cap=max(inc,rounded(order['size']*config.partial_fraction,inc))
    size=rounded(min(remaining,surplus,cap),inc)
    if size<=0:return None
    rate=fee_rate(frame,'MAKER')
    ref=hashlib.sha256((order['reference']+'|'+','.join(p['id'] for p in through)).encode()).hexdigest()
    return dict(trade_id='MODEL-'+ref,product_id=order['pair'],side=order['side'],size=size,price=order['price'],
        size_in_quote=False,commission=size*order['price']*rate,fee_currency=order['pair'].split('-')[1],
        liquidity_indicator='M',classification='MODELED_PUBLIC_TRADE_THROUGH_NOT_EXCHANGE_FILL',
        evidence=dict(public_ids=[p['id'] for p in through],queue_before=before,participation=config.participation,
            prints=deepcopy(through),rest_s=now-order['accepted_at'],observed_at=batch['at'],fee_rate=rate))
