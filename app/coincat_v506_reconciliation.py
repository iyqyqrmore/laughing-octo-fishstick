"""v50.6 single-database intent + FIFO settlement fault-injection rehearsal.

The atomic transaction here is deliberately available to disposable DBs only.
Production financial DB migration and independently normalized Coinbase fee/FX
are NOT certified; no Coinbase client is imported, no order POST exists.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal,localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,sqlite3
from coincat_v502_order_intents import install as install_intents,stage,claim_single_possible_post,mark_unknown,reconcile_readonly_evidence,RecoveryBlocked
from coincat_unified_fifo_v501 import install as install_fifo,opening,apply_confirmed_batch,verify,UnifiedSettlementError
from coincat_v501_pilot_diagnostics import TEST_PAIRS,MARKS

class IntegrationBlocked(ValueError):pass

def _assert_disposable(db):
    sources=db.execute('PRAGMA database_list').fetchall()
    if len(sources)!=1:raise IntegrationBlocked('Attached/external databases prohibited')
    path=sources[0][2]
    if path and 'CoinCat_V506_FAKE_' not in path:
        raise IntegrationBlocked('Cannot mutate real or unknown financial database')

def _settle_fake_verified(db,*,client_id,order,fills,fee_currencies,usd_marks):
    """Production-like transaction ordering, but FAKE database ONLY."""
    _assert_disposable(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        intent=db.execute('''SELECT state,exchange_order_id,evidence_digest FROM unified_v502_intents
                WHERE client_order_id=?''',(client_id,)).fetchone()
        if not intent or intent[0]!='EXCHANGE_FILLED' or intent[1]!=order['order_id'] or not intent[2]:
            raise IntegrationBlocked('Durable journal must contain matching complete confirmed evidence')
        result=apply_confirmed_batch(db,order=order,fills=fills,
                product_catalog={order['product_id']},fee_currencies=fee_currencies,
                usd_marks=usd_marks,usd_cap='1000000')
        if result['result'] not in ('APPLIED','REPLAY_NOOP'):
            raise IntegrationBlocked('Unaccounted fill settlement status')
        cur=db.execute('''UPDATE unified_v502_intents SET state='SETTLED' WHERE client_order_id=?
                        AND state='EXCHANGE_FILLED' ''',(client_id,))
        if cur.rowcount!=1:raise IntegrationBlocked('Journal update failed')
        verify(db)
        db.execute('COMMIT')
        return result
    except BaseException:
        db.execute('ROLLBACK');raise

def integrated_12_order_rehearsal():
    """Durable journal → evidence → multi-asset FIFO → crash/restart test."""
    checks={'fake_orders':0,'fake_split_fills':0,'fee_quote_assets':set(),
            'recovered_after_restart':0,'atomic_settlements':0,
            'duplicate_post_claim_refusals':0,'double_settlement_refusals':0,
            'crash_rollbacks':0,'production_writes':0,'coinbase_posts':0}
    with localcontext() as ctx:
        ctx.prec=120
        with TemporaryDirectory(prefix='CoinCat_V506_FAKE_') as temp:
            path=Path(temp)/'CoinCat_V506_FAKE_JOURNAL.sqlite3'
            with closing(sqlite3.connect(path,isolation_level=None)) as db:
                install_intents(db);install_fifo(db)
                for asset,value in MARKS.items():
                    opening(db,asset,'1000',tax_usd=None,performance_usd=str(Decimal(1000)*Decimal(value)))
                for i,(pair,side) in enumerate(TEST_PAIRS):
                    cid=f'FAKE-V506-CID-{i:02d}'
                    stage(db,client_order_id=cid,product_id=pair,side=side)
                    claim_single_possible_post(db,cid)
                    mark_unknown(db,cid)
                    checks['fake_orders']+=1
                verify(db)
            with closing(sqlite3.connect(path,isolation_level=None)) as db:
                for i,(pair,side) in enumerate(TEST_PAIRS):
                    cid=f'FAKE-V506-CID-{i:02d}'
                    if db.execute('SELECT state FROM unified_v502_intents WHERE client_order_id=?',(cid,)).fetchone()[0]!='UNKNOWN':
                        raise IntegrationBlocked('Uncertain status lost across reopen')
                    checks['recovered_after_restart']+=1
                    try:claim_single_possible_post(db,cid)
                    except RecoveryBlocked:checks['duplicate_post_claim_refusals']+=1
                    else:raise IntegrationBlocked('Double POST claim enabled')
                    base,quote=pair.split('-');px=Decimal(MARKS[base])/Decimal(MARKS[quote]);
                    price=format(px,'f');px=Decimal(price)
                    oid=f'FAKE-EXCH-{i:02d}'
                    rows=[];marks={};fees={};ts=1770000000+i*100
                    for k,qty in enumerate((Decimal('0.001'),Decimal('0.002'))):
                        tid=f'FAKE-V506-T-{i}-{k}'
                        commission=qty*px*Decimal('0.001')
                        rows.append({'order_id':oid,'trade_id':tid,'product_id':pair,'side':side,
                              'price':price,'size':format(qty,'f'),
                              'commission':format(commission,'f'),'at_utc':ts+k})
                        fees[tid]=quote
                        for asset in (base,quote):
                            if asset!='USD':marks[(tid,asset)]=(MARKS[asset],ts+k)
                        checks['fee_quote_assets'].add(quote)
                    gross=Decimal('0.003')*px
                    order={'order_id':oid,'product_id':pair,'side':side,'status':'FILLED',
                           'filled_size':'0.003','filled_value':format(gross,'f'),
                           'total_fees':format(gross*Decimal('0.001'),'f')}
                    digest=hashlib.sha256((cid+oid+str(i)).encode()).hexdigest()
                    reconcile_readonly_evidence(db,client_order_id=cid,exchange_order_id=oid,
                       status='FILLED',paginated_fills_complete=True,evidence_digest=digest)
                    # Inject a failure before any committed FIFO writes for one order.
                    if i==0:
                        before=db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]
                        db.execute('BEGIN IMMEDIATE')
                        db.execute('INSERT INTO unified_v501_fills VALUES (?,?,?,?,?,?,?,?,?,?)',
                            ('FAKE-CRASH',oid,pair,side,'0','0','0',quote,'0','fake'))
                        db.execute('ROLLBACK')
                        if db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]!=before:
                            raise IntegrationBlocked('Local crash rollback failed')
                        checks['crash_rollbacks']+=1
                    result=_settle_fake_verified(db,client_id=cid,order=order,fills=rows,
                                                  fee_currencies=fees,usd_marks=marks)
                    if result['result']!='APPLIED':raise IntegrationBlocked('Fake batch not applied')
                    checks['atomic_settlements']+=1
                    checks['fake_split_fills']+=len(rows)
                    try:_settle_fake_verified(db,client_id=cid,order=order,fills=rows,
                                                  fee_currencies=fees,usd_marks=marks)
                    except IntegrationBlocked:checks['double_settlement_refusals']+=1
                    else:raise IntegrationBlocked('Second settlement allowed')
                verify(db)
                if db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]!=24:
                    raise IntegrationBlocked('Missing or duplicated FIFO fills')
                if db.execute("SELECT COUNT(*) FROM unified_v502_intents WHERE state='SETTLED'").fetchone()[0]!=12:
                    raise IntegrationBlocked('Journal/FIFO settle count differs')
            with closing(sqlite3.connect(path,isolation_level=None)) as db:
                assert db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0]==24
                assert db.execute("SELECT COUNT(*) FROM unified_v502_intents WHERE state='SETTLED'").fetchone()[0]==12
    checks['fee_quote_assets']=len(checks['fee_quote_assets'])
    return checks
