"""Read-only, full-ledger and date-filtered verified-fill reports.

No orders, API calls, tax computation, original-basis fabrication or ledger pruning.
Fee-tier estimates and research-only calculated profits are NEVER exported as real fills.
The live broker still supports USD/USDC quotes only. Quote-currency amounts
are explicitly labeled and MUST NOT be interpreted as USD for future pairs.
"""
from __future__ import annotations
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from coincat_live import sql

FIELDS = ['trade_id', 'utc_date', 'pair', 'side', 'base_qty', 'price',
          'quote_currency', 'gross_quote', 'fee_quote', 'fee_currency_evidence', 'fee_evidence_level',
          'performance_realized_quote', 'cost_basis_quote',
          'net_realized_quote', 'basis_provenance', 'order_purpose',
          'tax_cost_verified']


def utc_window(start_date, end_date):
    """Inclusive YYYY-MM-DD UTC dates, with exclusive end-day SQL bound."""
    try:
        start=datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        finish=datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError('Enter dates as YYYY-MM-DD (UTC)') from exc
    if finish < start:
        raise ValueError('End date must be on or after start date')
    return int(start.timestamp()), int((finish+timedelta(days=1)).timestamp())


def confirmed_rows(ledger_path, start_date, end_date):
    """All confirmed Coinbase fill rows in the range; no 2,000-row display cap."""
    start,end=utc_window(start_date,end_date)
    with sql(ledger_path) as con:
        rows=con.execute('''SELECT f.*, COALESCE(o.purpose,'AUTOTRADE') AS order_purpose,
                           o.state AS order_state
                    FROM fills f JOIN orders o ON f.cid=o.cid AND f.order_id=o.order_id
                    WHERE f.at_utc>=? AND f.at_utc<?
                    ORDER BY f.at_utc, f.trade_id''',(start,end)).fetchall()
        # Independently prove every disposed lot came from a confirmed new BUY.
        # Old manually typed opening prices are preserved for review but are not
        # certified tax basis, even when legacy cost_basis_quote is non-NULL.
        disposal_sources={}
        for tid, total, confirmed in con.execute('''
            SELECT d.trade_id,COUNT(*),SUM(CASE WHEN l.source='COINBASE_CONFIRMED_BUY'
                    THEN 1 ELSE 0 END)
            FROM inventory_disposals d JOIN inventory_lots l ON l.lot_id=d.lot_id
            GROUP BY d.trade_id'''):
            disposal_sources[tid]=(int(total),int(confirmed or 0))
    output=[]
    for raw in rows:
        r=dict(raw)
        # Fill records are already confirmed by the exchange reconciler. We do
        # not rename missing original tax cost to an enrollment performance mark.
        pair=str(r['pair']); quote=pair.rsplit('-',1)[-1]
        gross=Decimal(str(r['base_qty']))*Decimal(str(r['price']))
        refs=disposal_sources.get(r['trade_id'])
        verified_tax=bool(r['side']=='SELL' and refs is not None and refs[0]>0
                          and refs[0]==refs[1] and r.get('cost_basis_quote') is not None)
        output.append({
            'trade_id':r['trade_id'],
            'utc_date':datetime.fromtimestamp(int(r['at_utc']),timezone.utc).isoformat(),
            'pair':pair,'side':r['side'], 'base_qty':r['base_qty'],
            'price':r['price'],'quote_currency':quote,'gross_quote':str(gross),
            'fee_quote':r['fee_quote'],
            # The old production schema records a quote fee; historical exports
            # must never claim maker/taker or pair-specific verified fee tier.
            'fee_currency_evidence':quote if r.get('fee_quote') is not None else 'UNKNOWN',
            'fee_evidence_level':'LEGACY_RECONCILED_QUOTE_FEE_ONLY' if r.get('fee_quote') is not None else 'MISSING',
            'performance_realized_quote':r.get('performance_realized_quote'),
            'cost_basis_quote':r.get('cost_basis_quote') if verified_tax else None,
            'net_realized_quote':r.get('net_realized_quote') if verified_tax else None,
            'basis_provenance':r.get('basis_provenance'),
            'order_purpose':r.get('order_purpose'),
            'tax_cost_verified': 'LOCAL BOT BUY LOTS / VERIFY COINBASE' if verified_tax else 'NO / ORIGINAL DOCUMENTS REQUIRED'
        })
    return output


def _excel_cell(value):
    # Excel opens CSV natively. Defuse formula injection from externally sourced
    # product IDs or comments without changing numeric amounts.
    if value is None:return ''
    s=str(value)
    if s.lstrip().startswith(('=', '@', '\t', '\r')):return "'"+s
    if s.lstrip().startswith(('+','-')):
        try:Decimal(s)
        except Exception:return "'"+s
    return s


def export_csv(path, ledger_path, start_date, end_date, *, tax_support=False):
    rows=confirmed_rows(ledger_path,start_date,end_date)
    path=Path(path)
    # Must never remove/overwrite a previous tax backup silently.
    with path.open('x',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore')
        writer.writeheader()
        for row in rows:writer.writerow({key:_excel_cell(row.get(key)) for key in FIELDS})
    return len(rows),path.stat().st_size


def handoff_text(ledger_path,start_date,end_date):
    rows=confirmed_rows(ledger_path,start_date,end_date)
    buys=sum(r['side']=='BUY' for r in rows)
    sells=[r for r in rows if r['side']=='SELL']
    unknown=sum(not r['tax_cost_verified'].startswith('LOCAL BOT BUY LOTS') for r in sells)
    gross_pairs=sorted({r['pair'] for r in rows})
    return (f'CoinCat verified-fill tax-preparation handoff (UTC {start_date} through {end_date})\n'
        f'Confirmed Coinbase fill rows: {len(rows)} (BUY: {buys}, SELL: {len(sells)}).\n'
        f'SELL fills without verified original tax basis: {unknown}.\n'
        f'Exchange spot products: {", ".join(gross_pairs[:30]) if gross_pairs else "none"}'
        f'{" ..." if len(gross_pairs)>30 else ""}.\n'
        'All legacy monetary fields in the fill CSV are denominated in the NAMED QUOTE CURRENCY, '
        'not automatically USD. Original taxable acquisition costs may be UNKNOWN. '
        'Performance marks are NOT tax cost basis; externally executed Coinbase transactions are NOT included. '+'Actual maker/taker status and future crypto-quote fee currencies require authenticated exchange fills. '+'Fee estimates do not belong in tax lots.\n\n'
        'Please help me prepare a checklist of records and questions for US federal and applicable '
        'state cryptocurrency tax reporting, including whether Form 8949, Schedule D, other forms, '
        'and Coinbase statements are relevant. Explain which fields need original acquisition '
        'date/cost, disposal proceeds, and fees; flag missing basis and transfers. If complete '
        'evidence is supplied, explain a transparent tax ESTIMATE with explicit assumptions, tax year, '
        'filing status, income bracket, holding period, and any missing data; do not invent an amount. '
        'Do not file forms, submit returns, or access my Coinbase account. '
        'Ask me for redacted CSV exports and missing details as needed.\n')
