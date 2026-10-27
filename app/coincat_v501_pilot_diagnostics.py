"""v50.1 redacted go-live transition audit; zero Coinbase calls and zero live writes."""
from __future__ import annotations
from decimal import Decimal,localcontext
from contextlib import closing
import sqlite3

from coincat_unified_fifo_v501 import (install,opening,apply_confirmed_batch,
                                        verify,balance,UnifiedSettlementError)

# Artificial pair fixtures, NOT current Coinbase availability. 12 distinct orders.
TEST_PAIRS=(('BTC-USD','BUY'),('ETH-USDC','SELL'),('SOL-USDT','BUY'),
            ('ETH-BTC','SELL'),('SOL-ETH','BUY'),('ADA-BTC','SELL'),
            ('LINK-ETH','BUY'),('DOT-USDC','SELL'),('AVAX-USDT','BUY'),
            ('ADA-DAI','SELL'),('LINK-SOL','BUY'),('DOGE-USD','SELL'))
MARKS={'USD':'1','USDC':'.999','USDT':'1.001','DAI':'1.0005','BTC':'85000',
       'ETH':'3000','SOL':'150','ADA':'.70','LINK':'18','DOT':'4',
       'AVAX':'30','DOGE':'.15'}


def pilot_rehearsal():
    """12 orders, 24 split fills, 7 distinct quote currencies. No SDK, no orders."""
    checks=[]
    with localcontext() as ctx:
        ctx.prec=120
        for i,(pair,side) in enumerate(TEST_PAIRS):
            base,quote=pair.split('-')
            with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                install(db)
                for asset in (base,quote):
                    opening(db,asset,'1000',performance_usd=str(Decimal(1000)*Decimal(MARKS[asset])))
                price=Decimal(MARKS[base])/Decimal(MARKS[quote]);px=format(price,'f')
                px=Decimal(px)
                sizes=(Decimal('.001'),Decimal('.002'))
                fee_rate=Decimal('.001')
                ts=1770000000+i*100
                fills=[];usd_marks={};fee_ccy={}
                for k,size in enumerate(sizes):
                    tid=f'OFFLINE-v501-{i}-{k}'
                    comm=size*px*fee_rate
                    fills.append(dict(order_id='FAKE-'+str(i),trade_id=tid,product_id=pair,
                                      side=side,price=format(px,'f'),size=format(size,'f'),
                                      commission=format(comm,'f'),at_utc=ts+k))
                    fee_ccy[tid]=quote
                    for asset in (base,quote):
                        if asset!='USD':usd_marks[tid,asset]=(MARKS[asset],ts+k)
                gross=sum((size*px for size in sizes),Decimal(0))
                order=dict(order_id='FAKE-'+str(i),product_id=pair,side=side,
                           status='FILLED',filled_size='0.003',
                           filled_value=format(gross,'f'),
                           total_fees=format(gross*fee_rate,'f'))
                before=balance(db,base),balance(db,quote)
                params=dict(order=order,fills=fills,product_catalog={pair},
                            fee_currencies=fee_ccy,usd_marks=usd_marks,usd_cap='1000')
                out=apply_confirmed_batch(db,**params)
                if out['result']!='APPLIED':raise UnifiedSettlementError('Synthetic order not applied')
                verify(db)
                if apply_confirmed_batch(db,**params)['result']!='REPLAY_NOOP':
                    raise UnifiedSettlementError('Synthetic replay posted twice')
                if db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]!=2:
                    raise UnifiedSettlementError('Synthetic split fill lost')
                if before[0]==balance(db,base) or before[1]==balance(db,quote):
                    raise UnifiedSettlementError('Synthetic wallet balance never changed')
                checks.append((pair,side))
    return {'orders':len(checks),'split_fills':len(checks)*2,
            'quote_assets':len({p.split('-')[1] for p,_ in checks}),
            'replay_noops':len(checks),'pairs':len({p for p,_ in checks})}


def diagnostic_section(app=None):
    lines=[
        'CoinCat v50.5 — UNIFIED SETTLEMENT / 12-TRADE PILOT TRANSITION AUDIT',
        'OFFLINE REHEARSAL ON DISPOSABLE DATA ONLY; NO COINBASE API OR ORDER POST',
        'These checks DO NOT enable a live pilot or prove profitable predictions.',
    ]
    try:
        result=pilot_rehearsal()
        lines.extend((
            '[PASS / SYNTHETIC] 12 independent artificial exchange orders applied.',
            '[PASS / SYNTHETIC] '+str(result['split_fills'])+' quote-denominated split fills processed.',
            '[PASS / SYNTHETIC] '+str(result['quote_assets'])+' quote currencies and '+str(result['pairs'])+' spot-pair fixtures.',
            '[PASS / SYNTHETIC] '+str(result['replay_noops'])+' identical confirmed batch replays did NOT duplicate lots.',
        ))
    except Exception as exc:
        lines.append('[BLOCKED] Isolated unified FIFO rehearsal: '+type(exc).__name__)
    try:
        catalog=getattr(app,'catalog',None) or []
        from coincat_cross_quote import split_spot
        valid=[]
        for pair in catalog:
            try:valid.append(split_spot(pair)[1])
            except (ValueError,TypeError):pass
        lines.extend((
            'Authenticated spot product IDs in current app catalog: '+str(len(valid)),
            'Distinct quote currencies in catalog: '+str(len(set(valid))),
            'Non-USD/USDC quoted catalog products: '+str(sum(q not in ('USD','USDC') for q in valid)),
        ))
    except Exception:
        lines.append('Authenticated catalog availability: NOT VERIFIED')
    lines.extend((
        '[NOT VERIFIED] USD FIFO parity with the existing production enrollment and inventory_lots tables.',
        '[NOT VERIFIED] Coinbase-confirmed fee units, fill-time authenticated USD marks and Windows live SDK.',
        '[NOT VERIFIED] Durable order-post recovery in the actual account, including partial terminal orders.',
        '[NOT VERIFIED] Profitability/forward USD edge from independent future outcomes.',
        '[BLOCKED] 12 REAL ORDER pilot: typed approval alone is NOT sufficient before these checks.',
        'LIVE STATUS: NO NEW CROSS-QUOTE SUBMISSION AUTHORIZATION FROM THIS PATCH.',
        'END v50.2 TRANSITION AUDIT',
    ))
    return '\n'.join(lines)+'\n'
