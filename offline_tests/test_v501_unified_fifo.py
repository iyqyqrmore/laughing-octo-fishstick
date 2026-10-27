"""CoinCat v50.1 isolated 12-order unified FIFO audit, absolutely no exchange calls."""
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
import unittest
from decimal import Decimal,localcontext
from coincat_unified_fifo_v501 import install,opening,apply_confirmed_batch,balance,verify,UnifiedSettlementError

PAIRS=('BTC-USD','ETH-USDC','SOL-USDT','ETH-BTC','SOL-ETH','ADA-BTC',
       'LINK-ETH','DOT-USDC','AVAX-USDT','ADA-DAI','LINK-SOL','DOGE-USD')
MARKS={'USD':'1','USDC':'.999','USDT':'1.001','BTC':'85000','ETH':'3000',
       'SOL':'150','DAI':'1.001','ADA':'.7','LINK':'18','DOT':'4','AVAX':'30','DOGE':'.15'}

def evidence(pair,side,index,*,fee_asset=None):
    base,quote=pair.split('-')
    with localcontext() as ctx:
        ctx.prec=120
        price=Decimal(MARKS[base])/Decimal(MARKS[quote])
        size1=Decimal('.001');size2=Decimal('.002')
        # decimal precision may be repeating: reuse exact normalized price text
        price=Decimal(format(price,'f'))
        gross=(size1+size2)*price
        fee=gross*Decimal('.001')
        oid=f'FAKE-O-{index}'
        ts=1770000000+10*index
        fills=[];fx={};fee_units={}
        for k,size in enumerate((size1,size2)):
            tid=f'FAKE-T-{index}-{k}'
            fqty=size*price*Decimal('.001')
            fills.append(dict(order_id=oid,trade_id=tid,product_id=pair,side=side,
                              size=format(size,'f'),price=format(price,'f'),
                              commission=format(fqty,'f'),at_utc=ts+k))
            fee_units[tid]=fee_asset or quote
            for ccy in (base,quote,fee_asset or quote):
                if ccy!='USD':fx[tid,ccy]=(MARKS[ccy],ts+k)
        order=dict(order_id=oid,product_id=pair,side=side,status='FILLED',
             filled_size='0.003',filled_value=format(gross,'f'),total_fees=format(fee,'f'))
        return order,fills,fx,fee_units

class UnifiedFIFOTwelveOrderTests(unittest.TestCase):
    def test_twelve_pairs_buys_and_sells(self):
        with localcontext() as ctx:
            ctx.prec=120
            for side in ('BUY','SELL'):
                for n,pair in enumerate(PAIRS):
                    with self.subTest(side=side,pair=pair):
                        base,quote=pair.split('-')
                        with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                            install(db)
                            for asset in (base,quote):
                                opening(db,asset,'1000',tax_usd=None,
                                        performance_usd=str(Decimal(1000)*Decimal(MARKS[asset])))
                            order,fills,fx,fee=evidence(pair,side,n)
                            before={base:balance(db,base),quote:balance(db,quote)}
                            r=apply_confirmed_batch(db,order=order,fills=fills,
                                product_catalog=set(PAIRS),fee_currencies=fee,
                                usd_marks=fx,usd_cap='1000')
                            self.assertEqual(r['result'],'APPLIED')
                            verify(db)
                            self.assertEqual(db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],2)
                            from coincat_fill_units import normalize_fill
                            q=sum((normalize_fill(x)['base_qty'] for x in fills),Decimal(0))
                            fee_sum=sum((Decimal(x['commission']) for x in fills),Decimal(0))
                            px=Decimal(fills[0]['price'])
                            self.assertEqual(balance(db,base),before[base]+(q if side=='BUY' else -q))
                            self.assertEqual(balance(db,quote),before[quote]+(-q*px-fee_sum if side=='BUY' else q*px-fee_sum))
                            # Unknown historic purchase price stays unknown for that first disposal.
                            d=db.execute('SELECT tax_pnl_usd FROM unified_v501_disposals LIMIT 1').fetchone()
                            self.assertIsNone(d[0])
    def test_duplicate_fill_replay_cannot_add_lots(self):
        with localcontext() as ctx:
            ctx.prec=120
            with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                install(db)
                opening(db,'ETH','1',performance_usd='3000')
                opening(db,'BTC','1',performance_usd='85000')
                order,fills,marks,fee=evidence('ETH-BTC','BUY',2)
                args=dict(order=order,fills=fills,product_catalog=set(PAIRS),fee_currencies=fee,
                         usd_marks=marks,usd_cap='1000')
                apply_confirmed_batch(db,**args)
                prior=db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]
                self.assertEqual(apply_confirmed_batch(db,**args)['result'],'REPLAY_NOOP')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],prior)
                verify(db)
    def test_tiny_mismatch_rolls_back(self):
        with localcontext() as ctx:
            ctx.prec=120
            with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                install(db)
                opening(db,'ETH','1',performance_usd='3000')
                opening(db,'BTC','1',performance_usd='85000')
                order,fills,marks,fee=evidence('ETH-BTC','BUY',2)
                order['filled_size']='0.00300000000000000000001'
                with self.assertRaises(UnifiedSettlementError):
                    apply_confirmed_batch(db,order=order,fills=fills,
                        product_catalog=set(PAIRS),fee_currencies=fee,usd_marks=marks,usd_cap='1000')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],0)
                verify(db)
    def test_partial_acquisition_dust_preserved(self):
        with localcontext() as ctx:
            ctx.prec=120
            with closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                install(db)
                opening(db,'BTC','0.000000000000000000000000003',tax_usd=None)
                self.assertEqual(balance(db,'BTC'),Decimal('3E-27'))
                verify(db)
    def test_failed_mid_batch_atomic_recovery(self):
        with localcontext() as ctx:
            ctx.prec=120
            with tempfile.TemporaryDirectory() as folder:
                p=Path(folder)/'FAKE_COINCAT_SETTLEMENT.db'
                with closing(sqlite3.connect(p,isolation_level=None)) as db:
                    install(db);opening(db,'BTC','1');opening(db,'ETH','1')
                    order,fills,marks,fees=evidence('ETH-BTC','BUY',0)
                    # First fill ID pre-populated with wrong evidence; no application permitted.
                    db.execute('''INSERT INTO unified_v501_fills VALUES (?,?,?,?,?,?,?,?,?,?)''',
                               (fills[0]['trade_id'],order['order_id'],order['product_id'],'BUY',
                                '.001','.03','0','BTC','0','WRONG_FINGERPRINT'))
                    with self.assertRaises(UnifiedSettlementError):
                        apply_confirmed_batch(db,order=order,fills=fills,
                            product_catalog={'ETH-BTC'},fee_currencies=fees,usd_marks=marks,
                            usd_cap='1000')
                    self.assertEqual(balance(db,'BTC'),Decimal(1))
                    self.assertEqual(balance(db,'ETH'),Decimal(1))
                with closing(sqlite3.connect(p,isolation_level=None)) as db:
                    verify(db)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],1)

if __name__=='__main__':unittest.main()
