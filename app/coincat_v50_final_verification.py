"""CoinCat v50.2: one exportable FINAL settlement/recovery evidence report.

WARNING: offline probes exercise the same cross-fill *read-only validator* and a
separate fake journal. They do NOT implement or certify production multi-asset
FIFO, ambiguous Coinbase POST recovery, or live trading. Never access network.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile

from coincat_cross_settlement import validate_filled_cross_order, SettlementBlocked
from coincat_go_live_readiness import gather_readiness


def _settlement_probe():
    """Deterministic two-fill cross-crypto validator check, no wallet/database writes."""
    ts=1770000000
    base='ETH';quote='BTC';pair='ETH-BTC'
    fills=[
        dict(order_id='FAKE-ORDER',trade_id='FAKE-T1',product_id=pair,side='BUY',
             price='0.03',size='0.001',commission='0.0000001',at_utc=ts),
        dict(order_id='FAKE-ORDER',trade_id='FAKE-T2',product_id=pair,side='BUY',
             price='0.03',size='0.002',commission='0.0000002',at_utc=ts+1)]
    order=dict(order_id='FAKE-ORDER',product_id=pair,side='BUY',status='FILLED',
               filled_size='0.003',filled_value='0.00009',total_fees='0.0000003')
    marks={(f['trade_id'],asset):(value,f['at_utc']) for f in fills
           for asset,value in [('BTC','80000'),('ETH','2400')]}
    params=dict(order=order,fills=fills,available_before={'BTC':'0.1','ETH':'0'},
                fee_currency_by_trade={f['trade_id']:'BTC' for f in fills},
                usd_marks_by_trade=marks,catalog={pair},usd_per_order_cap='100')
    r=validate_filled_cross_order(**params)
    assert r['status']=='ACCOUNTING_PREFLIGHT_ONLY'
    assert r['ready_for_live_post'] is False
    assert r['realized_tax_pnl_usd'] is None
    assert int(r['fill_count'])==2
    assert Decimal(r['verified_units_after']['ETH'])==Decimal('0.003')
    assert Decimal(r['verified_units_after']['BTC'])==Decimal('0.1')-Decimal('0.00009')-Decimal('0.0000003')
    assert Decimal(r['total_fee_usd'])==Decimal('0.0000003')*Decimal('80000')
    # Replay and tiny order-vs-fill differences must fail, even below a token increment.
    for override in (
        {'known_trade_fingerprints':{f['trade_id']:tuple(x['identity']) for f,x in zip(fills,r['fills'])}},
        {'order':dict(order,filled_size='0.003000000000000000000000001')},
        {'order':dict(order,total_fees='0.000000300000000000000000001')},
    ):
        try:
            validate_filled_cross_order(**dict(params,**override))
        except SettlementBlocked:
            pass
        else:
            raise AssertionError('A synthetic duplicate or dust discrepancy was accepted')
    return 'PASS (offline only): 2 split fills; exact quote/base fees; replay blocked; 2 tiny mismatches blocked'


def _recovery_probe():
    """Disposable SQLite journal: stable replay and no partial commit on restart.

    This is intentionally NOT a production Coinbase POST crash/recovery test.
    """
    with tempfile.TemporaryDirectory(prefix='CoinCatV50_REHEARSAL_ONLY_') as tmp:
        db_path=Path(tmp)/'FAKE_RECOVERY.sqlite3'
        with closing(sqlite3.connect(db_path,isolation_level=None)) as db:
            db.execute('CREATE TABLE journal(trade_id TEXT PRIMARY KEY, qty TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO journal VALUES (?,?)',('FAKE-T1','0.001'))
            db.execute('COMMIT')
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO journal VALUES (?,?)',('FAKE-CRASH','0.002'))
            # Closing uncommitted transaction simulates a local interrupted write.
        with closing(sqlite3.connect(db_path,isolation_level=None)) as db:
            assert db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM journal WHERE trade_id=?',('FAKE-CRASH',)).fetchone()[0]==0
            try:
                db.execute('INSERT INTO journal VALUES (?,?)',('FAKE-T1','0.001'))
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError('Fake duplicate journal insertion accepted')
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return 'PASS (offline only): local uncommitted rollback, duplicate refusal, committed write persistence after reopen'


def final_verification_report(app):
    """Sanitized export section. No network or real ledger writes, never raises ready-to-arm."""
    lines=[
        'CoinCat v50.5 — SETTLEMENT + RECOVERY FINAL VERIFICATION',
        'READ ONLY on actual ledger; isolated FAKE-ledger probes; ZERO Coinbase API/SDK/network calls.',
        'NO COINBASE ORDERS / NO ARM / NO PRODUCTION FINANCIAL WRITES',
        'FINAL GO-LIVE VERDICT: BLOCKED — unverified production cross-currency ledger and crash recovery.',
        'No account/order IDs, keys, token holdings, tax amounts or private file paths included.',
        '-'*72,
    ]
    snapshot=gather_readiness(app)
    ledger=snapshot['ledger']
    checks=[
        ('FINANCIAL SQLITE & EXACT QUANTITY',ledger['state'],
          'Local read-only checks: '+ledger['explanation']+'. Lot mismatches: '+str(ledger['lot_mismatch'])+
          '; invalid numeric fields: '+str(ledger['invalid_amounts'])+'.'),
        ('UNRESOLVED ORDER RECEIPTS','PASS' if ledger['state']=='PASS' and ledger['pending']==0 and ledger['orphan']==0 and ledger['duplicate']==0 else 'BLOCKED',
          'Local pending='+str(ledger['pending'])+'; orphan fills='+str(ledger['orphan'])+
          '; duplicates='+str(ledger['duplicate'])+'. Coinbase-side reconciliation NOT tested.'),
    ]
    for name,status,info in checks:
        lines.append('['+status+'] '+name+' — '+info)
    for name,func in [('READ-ONLY CROSS-QUOTE VALIDATOR REHEARSAL',_settlement_probe),
                      ('ISOLATED JOURNAL/RESTART REHEARSAL',_recovery_probe)]:
        try:
            msg=func()
            lines.append('[PASS: SYNTHETIC ONLY] '+name+' — '+msg)
        except Exception as exc:
            # Do not expose exception text, which might contain private identifiers.
            lines.append('[BLOCKED] '+name+' — '+type(exc).__name__+' (investigate locally; no live clearance)')
    lines.extend([
        '[BLOCKED] PRODUCTION MULTI-CURRENCY FIFO WRITES — Cross-currency validator remains preflight-only.',
        '[NOT VERIFIED] ACTUAL COINBASE FEE CURRENCY / PARTIAL FILLS / PAGINATED ORDER HISTORY — no API requests made.',
        '[NOT VERIFIED] PRODUCTION AMBIGUOUS POST / POWER-LOSS / MULTI-LEG RECOVERY — mock journal is not live broker.',
        '[BLOCKED] AUTOMATED PORTFOLIO LOSS FLOOR — production-wide independent control not certified.',
        '[BLOCKED] CROSS-CRYPTO POST — intentionally prohibited by production broker; no test removes guard.',
        'CONCLUSION: DO NOT ARM LIVE for full cross-crypto trading. No test here grants permissions.',
        'END SETTLEMENT / RECOVERY EVIDENCE',
    ])
    from coincat_v501_pilot_diagnostics import diagnostic_section
    from coincat_v502_legacy_parity import parity_report
    from coincat_v502_order_intents import recovery_rehearsal
    try:
        proof=recovery_rehearsal(12)
        extra='[PASS / ARTIFICIAL ONLY] v50.2 durable 12-intent recovery/restart: '+str(proof)+'\n'
    except Exception as exc:
        extra='[BLOCKED] v50.2 durable intent rehearsal failed: '+type(exc).__name__+'\n'
    extra+='[BLOCKED] v50.2 order-intent journal is NOT wired to production Coinbase POST.\n'
    return '\n'.join(lines)+'\n\n'+diagnostic_section(app)+'\n'+parity_report(app.ledger.path)+'\n'+extra
