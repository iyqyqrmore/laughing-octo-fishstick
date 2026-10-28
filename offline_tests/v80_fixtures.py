"""Invented market/evidence fixtures. NO observed Coinbase opportunity."""
from copy import deepcopy
from decimal import Decimal as D
from coincat_multicurrency import evaluate_rotation
from coincat_v80_immediate import evaluate

NOW=1800000000


def reference(*,now=NOW,qty='.002',cap='100',increment='.00000001'):
    quotes={'BTC-USD':(D('50000'),D('50000.01'),now),
            'ETH-USD':(D('2600'),D('2600.01'),now),
            'ETH-BTC':(D('.051199'),D('.0512'),now)}
    rules={p:dict(product_id=p,product_type='SPOT',status='online',
        base_increment=increment,base_min_size=increment,quote_min_size='.00000001',quote_increment='.00000001') for p in quotes}
    raw=evaluate_rotation(source='BTC',target='ETH',authorized_qty=qty,verified_available_qty=qty,
        balance_age_s=0,catalog=list(quotes),quotes=quotes,now=now,usd_per_order_cap=cap,
        product_rules=rules,fee_rate='.009',max_legs=1)['routes'][0]
    idea=dict(source='BTC',target='ETH',source_units=D(qty),trigger_pair='ETH-BTC',
        route=raw['route'],shadow_fifo_steps=raw['steps'],
        input_units_planned=raw['input_units_planned'],destination_units_estimate=raw['destination_units_estimate'],
        research_size_cap_usd=D(cap),immediate_change_usd=raw['immediate_change_usd'],
        observed_momentum_pct=D(0),sends_live_orders=False,model_product_rules=rules)
    return idea,quotes,rules


def synthetic_proof(assessment):
    frame=assessment['frame']
    books={p:{'pair':p,'observed_at':raw[2],
        'bids':[{'price':str(raw[0]),'size':'1000000'}],
        'asks':[{'price':str(raw[1]),'size':'1000000'}]} for p,raw in frame['books'].items()}
    return {'origin':'SYNTHETIC_OFFLINE','frame_id':frame['id'],'at':frame['at'],'books':books,
        'previews':[{'origin':'SYNTHETIC_OFFLINE','pair':s['pair'],'side':s['side'],
            'base_quantity':str(s['gross_base_quantity']),
            'fee_amount':str(s['fee_amount_estimate']),
            'fee_currency':s['assumed_fee_currency_for_research'],'at':frame['at']}
            for s in frame['orders']]}


def annotated(*,now=NOW,qty='.002',cap='100'):
    idea,quotes,rules=reference(now=now,qty=qty,cap=cap)
    r=evaluate(idea,quotes,rules,now=now)
    return dict(r['frame']['idea'],model_product_rules=rules,immediate_assessment=r),quotes,rules,synthetic_proof(r)
