"""v50.2 durable order-intent and ambiguous-POST recovery foundation.

No Coinbase SDK, no POST methods, no app integration, no permissions granted.
Only tests write a disposable SQLite DB. LIVE readiness is always false.
A future production adapter MUST reconcile Coinbase evidence before settlement.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone

class RecoveryBlocked(ValueError):pass

STATES=('STAGED','SUBMISSION_MAY_HAVE_OCCURRED','UNKNOWN','ACKNOWLEDGED',
        'PARTIAL','EXCHANGE_FILLED','CANCELLED_REVIEW','SETTLED')

def install(db):
    db.execute('''CREATE TABLE IF NOT EXISTS unified_v502_intents (
       client_order_id TEXT PRIMARY KEY, product_id TEXT NOT NULL,
       side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
       state TEXT NOT NULL, may_have_posted INTEGER NOT NULL DEFAULT 0,
       exchange_order_id TEXT, evidence_digest TEXT, attempts INTEGER NOT NULL DEFAULT 0,
       created_utc INTEGER NOT NULL, updated_utc INTEGER NOT NULL)''')

def _now():return int(datetime.now(timezone.utc).timestamp())

def stage(db,*,client_order_id,product_id,side):
    if not isinstance(client_order_id,str) or not (6<=len(client_order_id)<=128) or not client_order_id.isascii():
        raise RecoveryBlocked('Missing immutable client order ID')
    if not isinstance(product_id,str) or '-' not in product_id or len(product_id)>64:
        raise RecoveryBlocked('Invalid product')
    if side not in ('BUY','SELL'):raise RecoveryBlocked('Invalid side')
    now=_now()
    db.execute('''INSERT INTO unified_v502_intents(client_order_id,product_id,side,state,created_utc,updated_utc)
               VALUES (?,?,?,?,?,?)''',(client_order_id,product_id,side,'STAGED',now,now))

def claim_single_possible_post(db, client_order_id):
    """Durably claim right for exactly ONE POST attempt; never POST here.

    Mark possible submission BEFORE any real network call. If process dies,
    caller must use authenticated lookup only, NEVER retry on same client ID.
    """
    db.execute('SAVEPOINT v502_post_claim')
    try:
        cur=db.execute('''UPDATE unified_v502_intents SET state='SUBMISSION_MAY_HAVE_OCCURRED',
            may_have_posted=1,attempts=1,updated_utc=? WHERE client_order_id=?
            AND state='STAGED' AND may_have_posted=0 AND attempts=0''',(_now(),client_order_id))
        if cur.rowcount!=1:raise RecoveryBlocked('Already posted/uncertain/missing: READ-ONLY RECONCILIATION REQUIRED')
        db.execute('RELEASE v502_post_claim')
    except BaseException:
        db.execute('ROLLBACK TO v502_post_claim');db.execute('RELEASE v502_post_claim');raise
    return 'ONE_POST_ATTEMPT_CLAIMED_NEVER_RETRY'

def mark_unknown(db, client_order_id):
    cur=db.execute('''UPDATE unified_v502_intents SET state='UNKNOWN',updated_utc=?
                   WHERE client_order_id=? AND may_have_posted=1
                   AND state='SUBMISSION_MAY_HAVE_OCCURRED' ''',(_now(),client_order_id))
    if cur.rowcount!=1:raise RecoveryBlocked('Cannot mark unknown from current state')

def reconcile_readonly_evidence(db,*,client_order_id,exchange_order_id,status,
                                paginated_fills_complete=False,evidence_digest=None):
    """Record already-authenticated evidence only; never blindly settle or repost."""
    r=db.execute('SELECT state,exchange_order_id,may_have_posted FROM unified_v502_intents WHERE client_order_id=?',
                 (client_order_id,)).fetchone()
    if not r or not r[2]:raise RecoveryBlocked('No durable attempted submission')
    if status not in ('OPEN','PARTIAL','FILLED','CANCELLED'):
        raise RecoveryBlocked('Missing exact recognized exchange order status')
    if not isinstance(exchange_order_id,str) or not exchange_order_id.strip():
        raise RecoveryBlocked('No authenticated exchange order ID')
    if r[1] is not None and r[1]!=exchange_order_id:
        raise RecoveryBlocked('Conflicting exchange order ID')
    if r[0]=='SETTLED':raise RecoveryBlocked('Already settled; do not replay')
    if status=='FILLED' and not paginated_fills_complete:
        raise RecoveryBlocked('Complete verified fills required before FILLED')
    if status=='PARTIAL': next_state='PARTIAL'
    elif status=='FILLED':next_state='EXCHANGE_FILLED'
    elif status=='CANCELLED':next_state='CANCELLED_REVIEW'
    else:next_state='ACKNOWLEDGED'
    # Conflict between former confirmed status and a later contradictory one.
    if r[0] in ('EXCHANGE_FILLED','CANCELLED_REVIEW') and next_state!=r[0]:
        raise RecoveryBlocked('Conflicting terminal evidence')
    if not isinstance(evidence_digest,str) or len(evidence_digest)<16:
        raise RecoveryBlocked('Missing independent fingerprint of exchange evidence')
    db.execute('''UPDATE unified_v502_intents SET state=?,exchange_order_id=?,evidence_digest=?,updated_utc=?
               WHERE client_order_id=?''',(next_state,exchange_order_id,evidence_digest,_now(),client_order_id))
    return next_state

def request_settlement(db, client_order_id):
    """Do NOT perform settlement: record that a production adapter is missing."""
    r=db.execute('SELECT state FROM unified_v502_intents WHERE client_order_id=?',(client_order_id,)).fetchone()
    if r is None or r[0]!='EXCHANGE_FILLED':raise RecoveryBlocked('Not proven fully filled')
    raise RecoveryBlocked('BLOCKED: v50.2 journal is not attached to canonical production FIFO')

def recovery_rehearsal(n=12):
    """12 synthetic order IDs, temporary SQLite disk, crash/reopen and duplicates."""
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from contextlib import closing
    if type(n) is not int or n<1 or n>100:raise RecoveryBlocked('Invalid count')
    checks={'staged':0,'claimed':0,'no_retry':0,'reopen':0,'verified_full':0,'blocked_settlement':0}
    with TemporaryDirectory(prefix='CoinCat_V502_OFFLINE_RECOVERY_') as td:
        file=Path(td)/'FAKE_ORDER_JOURNAL.sqlite3'
        with closing(sqlite3.connect(file,isolation_level=None)) as db:
            install(db)
            for i in range(n):
                stage(db,client_order_id=f'FAKE-V502-{i:04d}',product_id='ETH-BTC',side='BUY')
                checks['staged']+=1
                claim_single_possible_post(db,f'FAKE-V502-{i:04d}')
                checks['claimed']+=1
                mark_unknown(db,f'FAKE-V502-{i:04d}')
        with closing(sqlite3.connect(file,isolation_level=None)) as db:
            for i in range(n):
                cid=f'FAKE-V502-{i:04d}'
                if db.execute('SELECT state FROM unified_v502_intents WHERE client_order_id=?',(cid,)).fetchone()[0]!='UNKNOWN':
                    raise RecoveryBlocked('Unknown state not durable across restart')
                checks['reopen']+=1
                try:claim_single_possible_post(db,cid)
                except RecoveryBlocked:checks['no_retry']+=1
                else:raise RecoveryBlocked('Double POST right granted')
                reconcile_readonly_evidence(db,client_order_id=cid,
                    exchange_order_id=f'FAKE-EXCHANGE-{i:04d}',status='FILLED',
                    paginated_fills_complete=True,evidence_digest=f'FAKE_HASH_{i:04d}_ABCDE123456')
                checks['verified_full']+=1
                try:request_settlement(db,cid)
                except RecoveryBlocked:checks['blocked_settlement']+=1
                else:raise RecoveryBlocked('Unverified financial posting allowed')
    return checks
