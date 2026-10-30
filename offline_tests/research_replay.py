"""Deterministic, public-book-only load fixture. No independent market samples.

Nine initial quote products plus ETH-USD and at most six research requests
per turn keep unique GETs <=16. Prices are synthetic and constant. Every
proposal uses the existing canonical full-source ranking/receipts.
"""
from decimal import Decimal as D
from coincat_full_balance import rank_full_balances
from coincat_passive_lab import PassiveLab
from coincat_v80_discovery import select_books

REPLAY_START = 1_800_000_000


def run_replay(*, lab_factory=PassiveLab, planner=select_books, minutes=180, product_count=844):
    lab=lab_factory()
    products=[f'R{i:03d}-USD' for i in range(product_count)]
    catalog=products+['ETH-USD']
    rules={p:dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
        base_min_size='.00000001',quote_min_size='.00000001',quote_increment='.00000001') for p in catalog}
    quotes={};maximum=0;max_pending=0;served={h:0 for h in (300,900,3600)}
    for turn,age in enumerate(range(0,minutes*60+1,12)):
        now=REPLAY_START+age
        groups=lab.quote_groups(now=now,listed=catalog)
        plan=planner(catalog,rules,set(),quotes=quotes,now=now,priority_groups=groups)
        feed=[products[(turn*9+i)%len(products)] for i in range(9)]
        requests=set(feed)|{'ETH-USD'}|set(plan['books'])
        maximum=max(maximum,len(requests))
        assert len(requests)<=16 and plan['endpoint_requests']<=6
        incoming={p:(D(100),D('100.01'),now) for p in requests}
        quotes.update(incoming)
        if hasattr(lab,'record_service'):
            lab.record_service(plan,incoming,{},now=now)
        result=rank_full_balances(balances={'USD':D(1000)},catalog=feed,rules=rules,
            quotes=quotes,fee_rate=D('.009'),now=now,balances_at=now)
        result.update(fetch_ms=3000,quote_errors={})
        lab.observe(result,quotes,now=now)
        max_pending=max(max_pending,len(lab.pending))
    outcomes={h:{'completed':lab.counts[f'{h}_ABOVE_HOLD']+lab.counts[f'{h}_NOT_ABOVE_HOLD'],
                 'missed':lab.counts[f'{h}_MISSED']} for h in (300,900,3600)}
    return {'outcomes':outcomes,'recorded':lab.counts['recorded_proposals'],
            'capacity_deferral_attempts':lab.counts['CAPACITY_DEFERRED'],
            'max_pending':max_pending,'max_unique_gets':maximum,
            'admission':dict(getattr(lab,'admission',{}))}
