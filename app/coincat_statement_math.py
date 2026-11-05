"""Owner CSV native-note reconstruction. Never fee authority, import or funding."""
import csv
from copy import deepcopy
from collections import Counter
from datetime import datetime,timezone
from decimal import localcontext
from pathlib import Path
import re

from coincat_beta_store import BetaBlocked
from coincat_fill_units import normalize_fill
from coincat_manual_trade import explicit_fee_currency,explicit_size_flag,order_report
from coincat_order_book import utc_stamp
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
        timestamp=None
        raw_time=row.get('Timestamp')
        if raw_time:
            try:
                value=datetime.fromisoformat(raw_time.replace(' UTC','+00:00').replace('Z','+00:00'))
                if value.tzinfo is None:raise ValueError()
                timestamp=value.astimezone(timezone.utc).timestamp()
            except (ValueError,TypeError,OverflowError):raise BetaBlocked('STATEMENT_TIMESTAMP_NOT_UTC_VERIFIABLE') from None
        return dict(source='OWNER_STATEMENT_RECONSTRUCTION_NOT_API_VERIFICATION',pair=pair,side=side,timestamp=timestamp,
            base_qty=size,price=price,gross_quote=receipt['quote_qty'],statement_quote_total=net,
            implied_quote_deduction=deduction,implied_fee_fraction=deduction/gross,implied_fee_percent=deduction/gross*100,
            usd_fee_consistent=usd_consistent,fee_currency='DERIVED_NOTE_DIFFERENCE_NOT_REPORTED_API_COMMISSION',
            account_reconciliation='UNKNOWN',liquidity='UNKNOWN',order_identifier_join='NOT_PROVEN',
            future_fee_authority=False)


def corroborate(record,statement):
    """Appendable report revision; raw API fills and API fee units stay intact.

    This is a unique native-fields/time match, not an identifier join or account
    reconciliation. Ambiguous or conflicting observations never become exact.
    """
    result=deepcopy(record);fills=result['fills'];previous=result['report']
    # A new cross-check cannot keep an old CSV-derived certainty if the current
    # dataset makes that match ambiguous. Reproject the unchanged API evidence.
    report=order_report(result['order'],fills,portfolio=previous['portfolio'],complete=record.get('complete') is True,
        source=previous.get('source','VERIFIED_EXCHANGE_HISTORICAL_READ'));result['report']=report
    if (not record.get('complete') or report.get('coverage')!='COMPLETE_AS_REPORTED' or
            report.get('state')=='HISTORY_INCOMPLETE' or not fills):
        return result
    used=set();matches=[]
    for raw in fills:
        try:
            explicit_size_flag(raw.get('size_in_quote'))
            with localcontext() as context:
                context.prec=120;native=normalize_fill(raw)
            stamp=utc_stamp(raw.get('trade_time'));currency=explicit_fee_currency(raw)
            quote=report['pair'].split('-')[1]
            if currency is not None and currency!=quote:raise BetaBlocked('STATEMENT_CONFLICTS_WITH_REPORTED_FEE_ASSET')
            candidates=[(i,r) for i,r in enumerate(statement['reports']) if r.get('timestamp') is not None and
                int(r['timestamp'])==int(stamp) and r['pair']==report['pair'] and r['side']==report['side'] and
                r['base_qty']==native['base_qty'] and r['price']==exact(raw['price'])]
            if len(candidates)!=1 or candidates[0][0] in used:raise BetaBlocked('STATEMENT_MATCH_AMBIGUOUS_OR_ABSENT')
            index,row=candidates[0]
            if row['implied_quote_deduction']!=exact(raw['commission']) or row['gross_quote']!=native['quote_qty']:
                raise BetaBlocked('STATEMENT_AND_API_NATIVE_TOTALS_CONFLICT')
            used.add(index);matches.append(row)
        except (ValueError,TypeError,KeyError,ArithmeticError):
            report['statement_corroboration']='UNRESOLVED_NO_UNIQUE_CONSISTENT_NATIVE_MATCH'
            return result
    with localcontext() as context:
        context.prec=120
        base=sum((r['base_qty'] for r in matches),exact(0))
        gross=sum((r['gross_quote'] for r in matches),exact(0))
        fee=sum((r['implied_quote_deduction'] for r in matches),exact(0))
        if (base,gross,fee)!=(report['base_qty'],report['gross_quote'],report['fee_amount']):
            report['statement_corroboration']='UNRESOLVED_AGGREGATE_CONFLICT';return result
        report.update(native_settlement='STATEMENT_CORROBORATED_NATIVE_FLOW',
            statement_corroboration='UNIQUE_NATIVE_FIELDS_AND_UTC_SECOND_MATCH',
            statement_identifier_join='NOT_PROVEN_FIELD_MATCH_ONLY',statement_rows=len(matches),
            base_change=base if report['side']=='BUY' else -base,
            quote_change=-(gross+fee) if report['side']=='BUY' else gross-fee,
            reason='OWNER_STATEMENT_CORROBORATES_NATIVE_FLOW_API_FEE_UNITS_UNCHANGED')
    return result


def corroborate_many(records,statement):
    """A single statement row cannot corroborate multiple exchange fills."""
    counts=Counter();seen=set()
    with localcontext() as context:
        context.prec=120
        for record in records:
            for raw in record['fills']:
                try:
                    identity=(raw['retail_portfolio_id'],raw['order_id'],raw['trade_id'])
                    if identity in seen:continue
                    seen.add(identity);explicit_size_flag(raw.get('size_in_quote'));native=normalize_fill(raw)
                    counts[(raw['product_id'],raw['side'],native['base_qty'],exact(raw['price']),int(utc_stamp(raw['trade_time'])))]+=1
                except (ValueError,TypeError,KeyError,ArithmeticError):continue
        unique=dict(statement,reports=[r for r in statement['reports'] if r.get('timestamp') is not None and
            counts[(r['pair'],r['side'],r['base_qty'],r['price'],int(r['timestamp']))]<=1])
        return [corroborate(record,unique) for record in records]


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
