"""CoinCat v50.2 go-live EVIDENCE audit.

Snapshot of authenticated *previously fetched* in-memory observations and a
read-only SQLite financial database. It performs NO network requests, creates
NO database or tables, and DOES NOT authorize/order/arm anything. It intentionally
leaves unproven production capabilities BLOCKED even when all observations pass.
This is a support diagnostics artifact, not a live trading permission oracle.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
import time
from coincat_v90_telemetry import age_detail, utc


_STATUSES = ('PASS', 'BLOCKED', 'NOT VERIFIED', 'INFO')
_FINAL_REQUIRED = frozenset((
    'Authenticated spot catalog', 'Fresh Coinbase market/portfolio data',
    'Fully USD-valued enrolled portfolio', 'Ledger integrity and quantity audit',
    'No unresolved orders or mismatched fills', 'Risk, limits and STOP controls',
    'Portfolio loss floor protection',
    'Production cross-currency FIFO settlement', 'Coinbase fee and fill reconciliation',
    'Durable ambiguous-POST and crash recovery', 'Live SDK preview/product-rule verification',
    'After-cost USD advantage validation', 'Supervised multi-currency live pilot',
))


def _decimal(value):
    # Floats are forbidden: no precision loss or silent rounding in an audit.
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError('not an exact decimal encoding')
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('not an exact decimal encoding') from None
    if not x.is_finite():
        raise ValueError('non-finite financial value')
    return x


def _elapsed(clock, ts, limit):
    try:
        stamp = float(ts)
        if not stamp or not (clock >= stamp):
            return None
        age = clock - stamp
        return age if age <= limit else None
    except (ValueError, TypeError, OverflowError):
        return None


def _check_database(path):
    """No SQLite state creation, no writes; no financial names/amounts returned."""
    result = dict(state='BLOCKED', explanation='Local financial ledger unavailable',
                  order_count=None, fill_count=None, unknown_basis=None,
                  pending=None, orphan=None, lot_mismatch=None, duplicate=None,
                  audited_assets=None, invalid_amounts=None, fees_checked=None,
                  receipt_audit_count=None, cross_audit_count=None,
                  cross_production=False, emergency_stop=None, schema_error=False)
    try:
        p = Path(path)
        if not p.is_file():
            return result
        with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            try:
                integrity = db.execute('PRAGMA quick_check(1)').fetchone()[0]
            except sqlite3.DatabaseError:
                result['explanation']='SQLite integrity check unavailable'
                return result
            if integrity != 'ok':
                result['explanation']='Financial SQLite integrity check FAILED'
                return result
            required = {'orders','fills','enrollment','inventory_lots','risk','inventory_disposals'}
            names = {row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            if not required <= names:
                result['explanation']='Financial SQLite tables missing; no zero counts inferred'
                result['schema_error']=True
                return result
            orders = db.execute('SELECT cid,state FROM orders').fetchall()
            fills = db.execute('SELECT trade_id,cid,base_qty,price,fee_quote FROM fills').fetchall()
            enrolled = db.execute('SELECT asset,remaining_qty,basis_unit_quote FROM enrollment').fetchall()
            lot_rows = db.execute('SELECT asset,remaining_qty,initial_qty,tax_unit_quote FROM inventory_lots').fetchall()
            disposals = db.execute('SELECT trade_id,lot_id,used_qty FROM inventory_disposals').fetchall()
            settings = {r['key']:r['value'] for r in db.execute('SELECT key,value FROM risk')}
            result['emergency_stop']=settings.get('halted','0')=='1'
            result['order_count']=len(orders)
            result['fill_count']=len(fills)
            result['pending']=sum(r['state'] not in ('FILLED','COMPLETED','REJECTED','CANCELLED','EXPIRED','FAILED') for r in orders)
            order_ids={r['cid'] for r in orders}
            result['orphan']=sum(r['cid'] not in order_ids for r in fills)
            # Count database-level duplicate ids if an older schema is corrupt.
            result['duplicate']=len(fills)-len({r['trade_id'] for r in fills})
            bad = 0
            for r in fills:
                try:
                    if (_decimal(r['base_qty'])<=0 or _decimal(r['price'])<=0
                        or _decimal(r['fee_quote'])<0):bad+=1
                except ValueError:bad+=1
            result['fees_checked']=len(fills)
            quantities=defaultdict(lambda: Decimal(0))
            lot_assets=set()
            for r in lot_rows:
                lot_assets.add(r['asset'])
                try:
                    qty=_decimal(r['remaining_qty']);initial=_decimal(r['initial_qty'])
                    if qty<0 or initial<0 or qty>initial:bad+=1
                    else:quantities[r['asset']]+=qty
                    if r['tax_unit_quote'] is not None and _decimal(r['tax_unit_quote'])<0:bad+=1
                except ValueError:bad+=1
            # USD and USDC account balances do not use acquired crypto inventory lots.
            # For a new noncash asset without a lot, it is a mismatch, not zero proof.
            mismatches=0;checked=0
            for r in enrolled:
                if r['asset'] in ('USD','USDC'):continue
                try:
                    qty=_decimal(r['remaining_qty'])
                    if qty<0:bad+=1;continue
                    checked+=1
                    if qty!=quantities[r['asset']]:mismatches+=1
                    if r['basis_unit_quote'] is not None and _decimal(r['basis_unit_quote'])<0:bad+=1
                except ValueError:bad+=1
            for r in disposals:
                try:
                    if _decimal(r['used_qty'])<=0:bad+=1
                except ValueError:bad+=1
            result.update(lot_mismatch=mismatches,audited_assets=checked,
                          invalid_amounts=bad,
                          unknown_basis=sum(r['tax_unit_quote'] is None for r in lot_rows),
                          cross_audit_count=db.execute('SELECT count(*) FROM cross_verified_fill_audit').fetchone()[0]
                            if 'cross_verified_fill_audit' in names else None)
            # No inference that a read-only cross-fill *audit* is executable settlement.
            if bad or mismatches or result['pending'] or result['orphan'] or result['duplicate']:
                result.update(state='BLOCKED',explanation='Unresolved orders, mismatched lots, or invalid ledger data')
            else:
                result.update(state='PASS',explanation='SQLite integrity, amounts, exact inventory quantities and order references passed (LOCAL ONLY)')
    except (sqlite3.Error, ValueError, TypeError, OSError, KeyError):
        result.update(state='BLOCKED',explanation='SQLite read/query failed; missing data cannot be treated as zero')
    return result


def gather_readiness(app, *, wall=None, mono=None):
    """Return sanitized, deterministic structured statuses; never fetch Coinbase."""
    wall = float(time.time() if wall is None else wall)
    mono = float(time.monotonic() if mono is None else mono)
    freshness={'snapshot_utc':utc(wall),
        'balances':age_detail(mono,getattr(app,'_last_portfolio_sync_monotonic',None),300),
        'broad_scan':age_detail(mono,getattr(app,'_last_scan_at',None),180),
        'portfolio_prices':age_detail(wall,getattr(app,'_portfolio_quote_at',None),300),
        'ui_poll':age_detail(mono,getattr(app,'_last_poll_heartbeat',None),15),
        'ui_tick':age_detail(mono,getattr(app,'_last_tick_heartbeat',None),15)}
    checks=[]
    def add(title,status,detail):
        if status not in _STATUSES:raise ValueError('Unknown status')
        checks.append((title,status,detail))

    broker=getattr(app,'broker',None)
    catalog=getattr(app,'catalog',None) or []
    cat_recent=_elapsed(wall,getattr(app,'catalog_at',0),7200)
    add('Authenticated spot catalog', 'PASS' if broker is not None and catalog and cat_recent is not None else 'BLOCKED',
        f'Current verified catalog entries: {len(catalog)}; freshness within 7200 seconds: {cat_recent is not None}. '
        'Every order must still revalidate its actual product.')

    ba=_elapsed(mono,getattr(app,'_last_portfolio_sync_monotonic',0),300)
    sa=_elapsed(mono,getattr(app,'_last_scan_at',0),180)
    pa=_elapsed(wall,getattr(app,'_portfolio_quote_at',0),300)
    poll=_elapsed(mono,getattr(app,'_last_poll_heartbeat',0),15)
    tick=_elapsed(mono,getattr(app,'_last_tick_heartbeat',0),15)
    busy=any(bool(getattr(app,name,False)) for name in ('worker_busy','_scan_processing','_portfolio_sync_running','_history_in_progress','_connection_in_progress'))
    all_fresh=bool(broker and all(x is not None for x in (ba,sa,pa,poll,tick)) and not busy
                   and not getattr(app,'_fill_sync_faulted',False))
    add('Fresh Coinbase market/portfolio data','PASS' if all_fresh else 'BLOCKED',
        'Balances <300s: '+str(ba is not None)+'; scan <180s: '+str(sa is not None)+
        '; pricing <300s: '+str(pa is not None)+'; UI callbacks <15s: '+str(poll is not None and tick is not None)+
        '; background idle: '+str(not busy)+'; fill-sync fault: '+str(bool(getattr(app,'_fill_sync_faulted',False))))

    coverage=getattr(app,'_portfolio_coverage',None) or {}
    # Coverage may include private token identifiers; include counts ONLY.
    held=coverage.get('held_count');priced=coverage.get('priced_count')
    complete=(coverage.get('complete') is True and held is not None and priced is not None
              and held==priced and held>0 and pa is not None and ba is not None)
    add('Fully USD-valued enrolled portfolio','PASS' if complete else 'BLOCKED',
        f'Currencies priced / held: {priced if isinstance(priced,int) else "UNVERIFIED"}/'
        f'{held if isinstance(held,int) else "UNVERIFIED"}; fresh authenticated USD books: {pa is not None}. '
        'Approval requires exact eligible, available, enrolled quantities as well as valid marks.')

    ledger=getattr(app,'ledger',None)
    db=_check_database(getattr(ledger,'path',None)) if ledger is not None else _check_database(None)
    ledger_ok=db['state']=='PASS'
    add('Ledger integrity and quantity audit','PASS' if ledger_ok else 'BLOCKED',
        f'SQLite/Decimal scan: {db["state"]}; noncash enrolled assets compared: '
        f'{db["audited_assets"] if db["audited_assets"] is not None else "UNVERIFIED"}; '
        f'exact lot quantity mismatches: {db["lot_mismatch"] if db["lot_mismatch"] is not None else "UNVERIFIED"}; '
        f'invalid financial values: {db["invalid_amounts"] if db["invalid_amounts"] is not None else "UNVERIFIED"}. '
        +db['explanation'])
    order_ok=(ledger_ok and db['pending']==0 and db['orphan']==0 and db['duplicate']==0)
    add('No unresolved orders or mismatched fills','PASS' if order_ok else 'BLOCKED',
        f'Pending/uncertain orders: {db["pending"] if db["pending"] is not None else "UNVERIFIED"}; '
        f'orphan fills: {db["orphan"] if db["orphan"] is not None else "UNVERIFIED"}; '
        'confirmed Coinbase-side order/fill agreement: NOT VERIFIED BY THIS SNAPSHOT.')

    riskfields=all(hasattr(broker,attr) for attr in ('per_order_max','daily_buy_cap','exposure_cap','max_orders_day','disarm','risk_check','submit')) if broker else False
    limits_ok=False
    if riskfields:
        try:
            limits_ok=all(_decimal(getattr(broker,attr))>0 for attr in ('per_order_max','daily_buy_cap','exposure_cap')) and int(broker.max_orders_day)>0
        except (ValueError,TypeError,AttributeError):limits_ok=False
    controls=(limits_ok and db['emergency_stop'] is False and not bool(getattr(broker,'armed',False)))
    add('Risk, limits and STOP controls','PASS' if controls else 'BLOCKED',
        'Separate manual ARM and emergency STOP exist: '+str(riskfields)+
        '; positive manual caps: '+str(limits_ok)+
        '; STOP latched: '+str(db['emergency_stop'])+
        '; app armed at audit: '+str(bool(getattr(broker,'armed',False)))+'. '
        'Functional fail-closed/crash evidence is separate from presence checks.')

    add('Portfolio loss floor protection','BLOCKED',
        'A production-wide enrolled-portfolio USD loss floor and independent fail-closed monitoring '
        'are not currently certified. Research/GUI budgets are not a substitute.')

    # These are deliberate release-control gates. A future production feature is
    # NOT licensed by current good telemetry, synthetic tests or a green LED.
    add('Production cross-currency FIFO settlement','BLOCKED',
        'Old dollar-quoted historical journal retained for reconciliation; active all-spot POST disabled. '
        'No verified atomic multi-currency asset/fee USD FIFO financial writes. Synthetic 640 fills do NOT satisfy this gate.')
    add('Coinbase fee and fill reconciliation','NOT VERIFIED',
        f'Local fee rows checked for nonnegative exact decimals: '
        f'{db["fees_checked"] if db["fees_checked"] is not None else "UNVERIFIED"}. '
        'Actual exchange fee currency, order totals, maker/taker, pagination and USD FX at fill time '
        'must independently agree with Coinbase. Not tested on this export.')
    add('Durable ambiguous-POST and crash recovery','NOT VERIFIED',
        'Historical dollar-quoted records have recovery routines, but offline isolated crash-injection '+
        'and real multi-currency durable idempotence/partial fill recovery have NOT passed production certification.')
    add('Live SDK preview/product-rule verification','NOT VERIFIED',
        'This button makes ZERO Coinbase requests. Authenticated independent SDK product increments, '
        'minima, order previews, permissions and pagination must be tested read-only before authorization.')
    add('After-cost USD advantage validation','NOT VERIFIED',
        'Current research proposals and synthetic wallet marks are NOT independently validated '
        'positive expected forward USD value after actual spread, fees, FX and slippage. Reject negative-edge executions.')
    add('Supervised multi-currency live pilot','BLOCKED',
        'No approved, one-order cross-crypto production pilot with verified exchange fill, recovery and FIFO. '
        'Live crypto-quoted submissions remain blocked. No orders were submitted for this report.')

    required={row[0] for row in checks}
    assert _FINAL_REQUIRED<=required
    passed=sum(status=='PASS' for _,status,_ in checks)
    blocked=sum(status=='BLOCKED' for _,status,_ in checks)
    unverified=sum(status=='NOT VERIFIED' for _,status,_ in checks)
    return dict(checks=checks,freshness=freshness,pass_count=passed,blocked_count=blocked,
                unverified_count=unverified,ledger=db,complete=len(checks)==len(_FINAL_REQUIRED),
                overall='NOT APPROVED',audited_at=datetime.fromtimestamp(wall,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))


def readiness_report(app, *, wall=None, mono=None):
    """Plain text, redacted, no filenames, no account balances or order IDs."""
    snapshot=gather_readiness(app,wall=wall,mono=mono)
    out=[
        'GO-LIVE EVIDENCE AUDIT — v50.5',
        'Freshness observation: '+str(snapshot['freshness']),
        'Each section is a separate timed observation; stale heartbeats do not alone diagnose a persistent GUI freeze.',
        'Read-only LOCAL snapshot; NO NEW Coinbase requests, NO orders, NO ARM, NO ledger writes.',
        'This report cannot independently verify market eligibility, exchange fees or production live execution.',
        'OVERALL: NOT APPROVED — multi-currency live order submission remains BLOCKED',
        f'GATE COUNTS: PASS={snapshot["pass_count"]}; BLOCKED={snapshot["blocked_count"]}; NOT VERIFIED={snapshot["unverified_count"]}',
        'PASS on data checks is NOT trading approval; all live-order production safeguards still apply.',
        'Raw private balances, keys, order IDs, asset names and transaction amounts are intentionally omitted.',
        '-'*76,
    ]
    for number,(name,state,detail) in enumerate(snapshot['checks'],1):
        out.append(f'{number:02d}. [{state}] {name}')
        out.append('    '+detail)
    out.extend([
        '-'*76,
        'INDEPENDENT EVIDENCE REQUIRED FOR ANY LATER GO-LIVE REVIEW:',
        'Verified actual production multi-currency FIFO and USD valuation, not just shadow/synthetic tests.',
        'Exchange fees, fill pagination, quantity increments, permissions and SDK previews independently checked.',
        'Crash-injection, ambiguous-POST recovery, partial fills, restart/idempotence and STOP fail-closed.',
        'Positive after-cost expected USD advantage validated before one explicitly authorized bounded real pilot.',
        'Operator must retain custody of approval. This report never unlocks or automatically arms orders.',
        'END GO-LIVE EVIDENCE AUDIT',
    ])
    return '\n'.join(out)+'\n'
