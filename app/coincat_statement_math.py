"""Owner CSV native-note reconstruction. Never fee authority, import or funding."""
import csv
from decimal import localcontext
from pathlib import Path
import re

from coincat_beta_store import BetaBlocked
from coincat_fill_units import normalize_fill
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS

NOTE=re.compile(r'(Sold|Bought) ([0-9]+(?:\.[0-9]+)?) ([A-Z0-9]{1,16}) for ([0-9]+(?:\.[0-9]+)?) ([A-Z0-9]{1,16}) on ([A-Z0-9-]{3,33}) at ([0-9]+(?:\.[0-9]+)?) ([A-Z0-9]{1,16})/([A-Z0-9]{1,16})')


def reconstruct(row):
    match=NOTE.fullmatch(row.get('Notes',''))
    if not match:raise BetaBlocked('STATEMENT_NATIVE_NOTE_NOT_RECOGNIZED')
    verb,size,base,net,quote,pair,price,quote_again,base_again=match.groups()
    if pair not in WATCH_PAIRS or pair!=base+'-'+quote or base!=base_again or quote!=quote_again:
        raise BetaBlocked('STATEMENT_NATIVE_PRODUCT_CONFLICT')
    side='SELL' if verb=='Sold' else 'BUY'
    if row.get('Asset')!=base or row.get('Transaction Type')!=('Advanced Trade Sell' if side=='SELL' else 'Advanced Trade Buy'):
        raise BetaBlocked('STATEMENT_NATIVE_SIDE_CONFLICT')
    with localcontext() as context:
        context.prec=120
        size,net,price=map(exact,(size,net,price));signed=exact(row.get('Quantity Transacted'))
        if size<=0 or price<=0 or signed!=(-size if side=='SELL' else size):raise BetaBlocked('STATEMENT_NATIVE_SIZE_CONFLICT')
        gross=size*price;deduction=gross-net if side=='SELL' else net-gross
        if deduction<0 or deduction>=gross:raise BetaBlocked('STATEMENT_NATIVE_NOTE_CONFLICT')
        receipt=normalize_fill(dict(price=str(price),size=str(size),size_in_quote=False,commission=str(deduction)))
        usd_consistent=None
        if row.get('Price Currency')=='USD':
            def usd(raw):return exact(raw.removeprefix('$').replace(',',''))
            try:usd_consistent=deduction/price*usd(row['Price at Transaction'])==usd(row['Fees and/or Spread'])
            except (ValueError,TypeError,KeyError,ArithmeticError):pass
        return dict(source='OWNER_STATEMENT_RECONSTRUCTION_NOT_API_VERIFICATION',pair=pair,side=side,
            base_qty=size,price=price,gross_quote=receipt['quote_qty'],statement_quote_total=net,
            implied_quote_deduction=deduction,implied_fee_fraction=deduction/gross,implied_fee_percent=deduction/gross*100,
            usd_fee_consistent=usd_consistent,fee_currency='DERIVED_NOTE_DIFFERENCE_NOT_REPORTED_API_COMMISSION',
            account_reconciliation='UNKNOWN',liquidity='UNKNOWN',order_identifier_join='NOT_PROVEN',
            future_fee_authority=False)


def read_statement(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1048576:raise BetaBlocked('STATEMENT_PATH_OR_SIZE_REJECTED')
    rows=list(csv.reader(path.read_text(encoding='utf-8-sig').splitlines()))
    index=next((i for i,r in enumerate(rows[:20]) if r[:3]==['ID','Timestamp','Transaction Type']),None)
    if index is None:raise BetaBlocked('STATEMENT_LAYOUT_NOT_RECOGNIZED')
    columns=rows[index]
    if len(columns)!=len(set(columns)) or len(rows)>4096:raise BetaBlocked('STATEMENT_COLUMNS_OR_ROWS_REJECTED')
    reports=[];unresolved=0
    for values in rows[index+1:]:
        if not values:continue
        if len(values)!=len(columns):raise BetaBlocked('STATEMENT_ROW_WIDTH_CONFLICT')
        row=dict(zip(columns,values))
        if row.get('Transaction Type') not in ('Advanced Trade Sell','Advanced Trade Buy'):continue
        try:reports.append(reconstruct(row))
        except (ValueError,TypeError,ArithmeticError):unresolved+=1
    return dict(source='OWNER_CSV_NOT_EXCHANGE_API',reports=reports,unresolved_trade_rows=unresolved,
        records_written=0,fee_settings_changed=False)
