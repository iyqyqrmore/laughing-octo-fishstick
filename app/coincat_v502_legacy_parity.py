"""Read-only v50 production inventory-to-unified-lots parity rehearsal.

Counts exact quantities and tests in-memory mapping to v50.1-style unified
wallet/lot rows. No mutations to original ledger, no claims of usable tax basis
when quote currency is not independently valued at acquisition time.
"""
from __future__ import annotations
from contextlib import closing
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
import sqlite3
from coincat_unified_fifo_v501 import install,opening,verify,number,UnifiedSettlementError


def audit_rows(db):
    """Read an existing SQLite connection without modifying any of its tables."""
    count=dict(assets=0,matched_exact=0,mismatch=0,no_lots=0,unknown_tax_lots=0,
               requires_quote_usd_proof=0,invalid_values=0,rebuilt_in_memory=0)
    with localcontext() as ctx:
        ctx.prec=120
        active=db.execute("SELECT asset,remaining_qty FROM enrollment WHERE asset NOT IN ('USD','USDC')").fetchall()
        with closing(sqlite3.connect(':memory:')) as oracle:
            install(oracle)
            for asset,qtyraw in active:
                count['assets']+=1
                try:
                    qty=number(qtyraw)
                    lots=db.execute('''SELECT remaining_qty,performance_unit_quote,tax_unit_quote,quote_ccy
                       FROM inventory_lots WHERE asset=? ORDER BY opened_at,lot_id''',(asset,)).fetchall()
                    if not lots:
                        count['no_lots']+=1;continue
                    actual=sum((number(row[0]) for row in lots),Decimal(0))
                    if actual!=qty:count['mismatch']+=1;continue
                    count['matched_exact']+=1
                    if qty==0:continue
                    # The v50.1 oracle is seeded with a collapsed opening lot for
                    # quantity parity only, NEVER presumed FIFO parity or tax proof.
                    quote_gap=any(row[3]!='USD' for row in lots if number(row[0])>0)
                    unknown=any(row[2] is None for row in lots if number(row[0])>0)
                    count['unknown_tax_lots']+=sum(1 for row in lots if number(row[0])>0 and row[2] is None)
                    count['requires_quote_usd_proof']+=int(quote_gap)
                    # USD valuation is deliberately absent: even a USD-like quote
                    # is not enough to prove historical fee / tax basis here.
                    opening(oracle,asset,qty,tax_usd=None,performance_usd=None)
                    count['rebuilt_in_memory']+=1
                except (sqlite3.Error, ValueError, UnifiedSettlementError, InvalidOperation,TypeError):
                    count['invalid_values']+=1
            verify(oracle)
    return count


def parity_report(path):
    lines=[
        'CoinCat v50.5 — HISTORICAL PRODUCTION LOT PARITY / MIGRATION READINESS',
        'READ ONLY actual existing local financial ledger; rebuilds artificial quantities in RAM.',
        'No production writes, no Coinbase requests, no fabricated cost basis, no live posting.',
    ]
    try:
        p=Path(path)
        if not p.is_file():raise OSError('Missing local ledger')
        with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            a=audit_rows(db)
        for k in ('assets','matched_exact','mismatch','no_lots','unknown_tax_lots',
                  'requires_quote_usd_proof','invalid_values','rebuilt_in_memory'):
            lines.append('  '+k+': '+str(a[k]))
        if a['mismatch'] or a['no_lots'] or a['invalid_values']:
            lines.append('[BLOCKED] Some existing production lots are missing, invalid, or fail ZERO-tolerance quantity equality.')
        else:
            lines.append('[PASS / LOCAL-ONLY] All inspected existing lots exactly match enrolled units; no production state was changed.')
        if a['unknown_tax_lots'] or a['requires_quote_usd_proof']:
            lines.append('[NOT VERIFIED] Some historical tax bases and/or quote-to-USD marks need independent records; no values invented.')
        lines.append('[BLOCKED] Production unified FIFO migration/live posting not certified by quantity parity alone.')
    except (OSError,sqlite3.Error,ValueError,TypeError):
        lines.append('[BLOCKED] Unable to audit real financial inventory read-only; do not infer zero balances or safe status.')
    lines.append('END LEGACY PRODUCTION LOT PARITY')
    return '\n'.join(lines)+'\n'
