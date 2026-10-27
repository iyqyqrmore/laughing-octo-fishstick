"""v50.6 authenticated Coinbase read-only order/fill evidence boundary.

SDK read operations only. No credentials, POST/DELETE, account mutations or
unverified fee currency inference. Normalization explicitly requires a later
adapter with independently verified fee units and historical USD FX marks.
"""
from __future__ import annotations
from collections.abc import Mapping
import hashlib,json

class ExchangeEvidenceBlocked(ValueError):pass

def mapping(x):
    if isinstance(x,Mapping):return dict(x)
    if hasattr(x,'to_dict'):
        value=x.to_dict()
        if isinstance(value,Mapping):return dict(value)
    raise ExchangeEvidenceBlocked('Unsupported Coinbase response shape; SDK review required')

def fetch_authenticated_order_and_fills(client,order_id,*,page_limit=100,max_pages=100):
    if not isinstance(order_id,str) or not order_id or len(order_id)>200:
        raise ExchangeEvidenceBlocked('Invalid existing order ID')
    if not 1<=page_limit<=1000 or not 1<=max_pages<=100:
        raise ExchangeEvidenceBlocked('Unsafe pagination policy')
    # Enforce explicit method names in the authenticated Advanced Trade SDK.
    # Never create/preview/post orders in the evidence reader.
    if not callable(getattr(client,'get_order',None)) or not callable(getattr(client,'get_fills',None)):
        raise ExchangeEvidenceBlocked('Authenticated SDK order/fills GET required')
    order_response=mapping(client.get_order(order_id))
    order=mapping(order_response.get('order',order_response))
    if str(order.get('order_id',''))!=order_id:
        raise ExchangeEvidenceBlocked('Order identity not authenticated or disagrees')
    all_rows=[];cursor=None;seen=set();complete=False;pages=0
    for i in range(max_pages):
        args={'order_ids':[order_id],'limit':page_limit}
        if cursor:args['cursor']=cursor
        result=mapping(client.get_fills(**args))
        rows=result.get('fills')
        if not isinstance(rows,list):raise ExchangeEvidenceBlocked('Missing fills list')
        for raw in rows:
            fill=mapping(raw)
            if str(fill.get('order_id',''))!=order_id:
                raise ExchangeEvidenceBlocked('Cross-order fill in authenticated history')
            all_rows.append(fill)
        pages+=1
        new_cursor=result.get('cursor')
        # Coinbase pagination may return cursor even at terminal; has_next is
        # authoritative when supplied. Refuse ambiguous end-of-pages.
        has_next=result.get('has_next')
        if has_next is False or (has_next is None and not new_cursor):
            complete=True;break
        if not isinstance(new_cursor,str) or not new_cursor or new_cursor in seen:
            raise ExchangeEvidenceBlocked('Missing/repeated cursor; incomplete history')
        seen.add(new_cursor);cursor=new_cursor
    if not complete:raise ExchangeEvidenceBlocked('Pagination ceiling reached; incomplete fill history')
    trade_ids=[str(row.get('trade_id','')) for row in all_rows]
    if len(trade_ids)!=len(set(trade_ids)) or any(not x for x in trade_ids):
        raise ExchangeEvidenceBlocked('Duplicate or absent trade identifiers')
    # Deterministic evidence hash only; NEVER mark as production reconciled
    # without complete fee units, product rule and FX evidence.
    payload={'order':order,'fills':sorted(all_rows,key=lambda x:str(x['trade_id']))}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    return {'order':order,'fills':all_rows,'history_complete':True,'pages':pages,
            'evidence_digest':digest,'fee_currency_verified':False,
            'fill_time_usd_fx_verified':False,'live_settlement_authorized':False}


def evidence_rehearsal():
    class FakeClient:
        def __init__(self):self.calls=0
        def get_order(self,oid):return {'order':{'order_id':oid,'status':'FILLED'}}
        def get_fills(self,**kwargs):
            self.calls+=1
            if self.calls==1:return {'fills':[{'order_id':'MOCK1','trade_id':'T1'}], 'cursor':'NEXT','has_next':True}
            return {'fills':[{'order_id':'MOCK1','trade_id':'T2'}], 'has_next':False}
    out=fetch_authenticated_order_and_fills(FakeClient(),'MOCK1')
    assert out['pages']==2 and len(out['fills'])==2
    assert not out['live_settlement_authorized'] and not out['fee_currency_verified']
    return {'mock_pages':2,'mock_fills':2,'actual_sdk_requests':0,'order_post':0}
