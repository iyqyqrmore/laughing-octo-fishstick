"""Read-only statement/API fee audit. Evidence never becomes trading settings."""
from datetime import date,datetime,time as day_time,timedelta,timezone
from decimal import Decimal as D,localcontext
from pathlib import Path
import csv
import time

from coincat_beta_store import BetaBlocked,digest
from coincat_fill_units import normalize_fill
from coincat_manual_trade import HistoryReader,ReadOnlyAPI,identity,explicit_size_flag,explicit_fee_currency,order_report
from coincat_order_book import utc_stamp
from coincat_statement_math import reconstruct
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS


def day_bounds(day,zone='America/Chicago'):
    """Modern US Central midnight boundaries, also works without Windows tzdata."""
    d=date.fromisoformat(day)
    if zone not in ('America/Chicago','UTC') or not 2007<=d.year<=2099:raise BetaBlocked('AUDIT_DAY_OR_ZONE_UNSUPPORTED')
    def midnight(v):
        spring=date(v.year,3,8);spring+=timedelta(days=(6-spring.weekday())%7)
        fall=date(v.year,11,1);fall+=timedelta(days=(6-fall.weekday())%7)
        offset=0 if zone=='UTC' else -5 if spring<v<=fall else -6
        return datetime.combine(v,day_time(),timezone(timedelta(hours=offset))).timestamp()
    return midnight(d),midnight(d+timedelta(days=1))


def statement_day(path,day,zone='America/Chicago'):
    start,end=day_bounds(day,zone);path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1048576:raise BetaBlocked('STATEMENT_PATH_OR_SIZE_REJECTED')
    rows=list(csv.reader(path.read_text(encoding='utf-8-sig').splitlines()))
    if len(rows)>4096:raise BetaBlocked('STATEMENT_ROW_BOUND')
    header=next((i for i,r in enumerate(rows[:20]) if r[:3]==['ID','Timestamp','Transaction Type']),None)
    if header is None or len(rows[header])!=len(set(rows[header])):raise BetaBlocked('STATEMENT_LAYOUT_NOT_RECOGNIZED')
    result=[];unresolved=[];other=0
    for values in rows[header+1:]:
        if not values:continue
        if len(values)!=len(rows[header]):raise BetaBlocked('STATEMENT_ROW_WIDTH_CONFLICT')
        row=dict(zip(rows[header],values))
        try:stamp=utc_stamp(row.get('Timestamp','').replace(' UTC','+00:00'))
        except ValueError:raise BetaBlocked('STATEMENT_TIMESTAMP_UNVERIFIED') from None
        if not start<=stamp<end:continue
        if row.get('Transaction Type') not in ('Advanced Trade Buy','Advanced Trade Sell'):other+=1;continue
        try:result.append(reconstruct(row))
        except (ValueError,TypeError,ArithmeticError):unresolved.append('UNRECOGNIZED_OR_CONFLICTING_NATIVE_TRADE_NOTE')
    return dict(reports=result,unresolved=unresolved,other_day_activity=other,day=day,zone=zone)


def audit_day(records,statement,*,api_coverage='PROVIDED_RECORDS_ONLY'):
    start,end=day_bounds(statement['day'],statement['zone']);api=[];seen={};issues=[]
    for record in records:
        o=record['order'];report=order_report(o,record['fills'],portfolio=o['retail_portfolio_id'],complete=record.get('complete') is True)
        for raw in record['fills']:
            try:
                stamp=utc_stamp(raw['trade_time'])
                if not start<=stamp<end:continue
                key=(identity(raw['order_id']),str(raw['trade_id']))
                if key in seen:
                    if seen[key]!=digest(raw):issues.append('CONFLICTING_API_FILL_REVISION')
                    continue
                seen[key]=digest(raw);explicit_size_flag(raw.get('size_in_quote'))
                with localcontext() as context:
                    context.prec=120;n=normalize_fill(raw)
                try:currency=explicit_fee_currency(raw)
                except ValueError:currency=None
                api.append(dict(raw=raw,order=o,native=n,currency=currency,stamp=stamp,
                    complete=report['coverage']=='COMPLETE_AS_REPORTED' and report['state']!='HISTORY_INCOMPLETE',
                    order_fills=len(record['fills'])))
            except (ValueError,TypeError,KeyError,ArithmeticError):issues.append('API_FILL_NATIVE_EVIDENCE_INVALID')
    rows=[];used=set();native_changes={}
    with localcontext() as context:
        context.prec=120
        for index,r in enumerate(statement['reports']):
            base,quote=r['pair'].split('-')
            native_changes[base]=native_changes.get(base,D(0))+(r['base_qty'] if r['side']=='BUY' else -r['base_qty'])
            native_changes[quote]=native_changes.get(quote,D(0))+(r['statement_quote_total'] if r['side']=='SELL' else -r['statement_quote_total'])
            match=[(i,a) for i,a in enumerate(api) if a['raw'].get('product_id')==r['pair'] and a['raw'].get('side')==r['side'] and
                a['native']['base_qty']==r['base_qty'] and a['native']['price']==r['price'] and int(a['stamp'])==int(r['timestamp'])]
            duplicates=sum(x['pair']==r['pair'] and x['side']==r['side'] and x['base_qty']==r['base_qty'] and x['price']==r['price'] and
                int(x['timestamp'])==int(r['timestamp']) for x in statement['reports'])
            out=dict(row=index+1,utc=datetime.fromtimestamp(r['timestamp'],timezone.utc).isoformat(),pair=r['pair'],side=r['side'],
                quantity=r['base_qty'],price=r['price'],gross_quote=r['gross_quote'],statement_net_quote=r['statement_quote_total'],
                csv_derived_quote_deduction=r['implied_quote_deduction'],csv_derived_fee_percent=r['implied_fee_percent'],
                usd_fee_consistent=r['usd_fee_consistent'],liquidity='UNKNOWN',api_commission=None,api_fee_currency='UNKNOWN',
                api_fee_fraction=None,api_after_fees_matches=None,status='CSV_ONLY_API_EVIDENCE_MISSING')
            if len(match)==1 and duplicates==1 and match[0][0] not in used:
                i,a=match[0];used.add(i);raw=a['raw'];fee=exact(raw['commission'])
                liquidity=raw.get('liquidity_indicator');out.update(api_commission=fee,api_fee_currency=a['currency'] or 'UNKNOWN',
                    liquidity='MAKER_REPORTED' if liquidity in ('M','MAKER') else 'TAKER_REPORTED' if liquidity in ('T','TAKER') else 'UNKNOWN',
                    status='API_CSV_NATIVE_MATCH' if a['complete'] and fee==r['implied_quote_deduction'] and
                        a['currency'] in (None,quote) and r['usd_fee_consistent'] is not False else 'UNRESOLVED_API_CSV_DIFFERENCE')
                if a['currency']==quote:out['api_fee_fraction']=fee/a['native']['quote_qty']
                elif a['currency']==base:out['api_fee_fraction']=fee/a['native']['base_qty']
                if a['order_fills']==1 and a['order'].get('total_value_after_fees') not in (None,''):
                    out['api_after_fees_matches']=exact(a['order']['total_value_after_fees'])==r['statement_quote_total']
                    if not out['api_after_fees_matches']:out['status']='UNRESOLVED_API_AFTER_FEE_DIFFERENCE'
            elif match:out['status']='AMBIGUOUS_NATIVE_FIELDS_TIME_MATCH'
            rows.append(out)
    matched=sum(r['status']=='API_CSV_NATIVE_MATCH' for r in rows)
    complete=bool(rows) and api_coverage=='HISTORY_EXHAUSTED_AS_REPORTED' and matched==len(rows) and len(used)==len(api) and not issues and not statement['unresolved']
    return dict(classification='READ_ONLY_HISTORICAL_FEE_AUDIT_NOT_FEE_AUTHORITY',day=statement['day'],zone=statement['zone'],
        rows=rows,csv_trade_rows=len(rows)+len(statement['unresolved']),api_fills=len(api),matched=matched,
        unmatched_api_fills=len(api)-len(used),unresolved_csv_rows=len(statement['unresolved']),issues=issues,
        api_coverage=api_coverage,coverage='COMPLETE_AS_REPORTED' if complete else 'PARTIAL_EVIDENCE',
        api_fee_currency_confirmed=sum(r['api_fee_currency']!='UNKNOWN' for r in rows),
        liquidity_confirmed=sum(r['liquidity']!='UNKNOWN' for r in rows),
        csv_trade_only_native_changes=native_changes,other_day_activity_not_reconciled=statement['other_day_activity'],
        account_reconciliation='UNKNOWN_NO_COMPLETE_OPENING_CLOSING_ACCOUNT_RECONCILIATION',future_fee_authority=False,
        identifier_join='UNIQUE_NATIVE_FIELDS_AND_UTC_SECOND_NOT_CSV_ORDER_ID')


def collect_day(client,day,zone='America/Chicago',*,cancel=None,clock=time.time,monotonic=time.monotonic,budget=None):
    """GET-only, scope-checked cursor sweep, then full order/fill receipts.

    No order-creation window: GTC orders created earlier can fill on this day.
    A bounded/incomplete history never becomes a claimed complete audit.
    """
    start,end=day_bounds(day,zone);reader=HistoryReader(ReadOnlyAPI(client),cancel=cancel,clock=clock,monotonic=monotonic)
    original=reader.read
    def paced(name,**kwargs):
        if budget is not None:budget.acquire(reader.started+120)
        return original(name,**kwargs)
    reader.read=paced;portfolio=reader.scope();cursor=None;seen=set();found={};complete=False;reason='BOUNDED_HISTORY_INCOMPLETE'
    try:
        for _ in range(16):
            args=dict(product_ids=list(WATCH_PAIRS),retail_portfolio_id=portfolio,limit=100)
            if cursor:args['cursor']=cursor
            page=reader.read('get_fills',**args);fills=page.get('fills')
            if not isinstance(fills,list) or len(fills)>512:raise BetaBlocked('AUDIT_FILL_PAGE_INVALID')
            for f in fills:
                if f.get('product_id') not in WATCH_PAIRS or f.get('retail_portfolio_id')!=portfolio:raise BetaBlocked('AUDIT_FILL_SCOPE_CONFLICT')
                if start<=utc_stamp(f.get('trade_time'))<end:found[identity(f['order_id'])]=True
            nxt=page.get('cursor')
            if page.get('has_next') is False or (page.get('has_next') is None and not nxt):complete=True;break
            if not isinstance(nxt,str) or not nxt or nxt in seen:break
            seen.add(nxt);cursor=nxt
        records=[]
        for oid in found:
            record=reader.one(oid);records.append(record)
            if not record['complete']:complete=False
    except (ValueError,TypeError,KeyError,ArithmeticError):
        complete=False;records=locals().get('records',[]);reason='READ_INTERRUPTED_OR_EVIDENCE_INCOMPLETE'
    return dict(records=records,portfolio=portfolio,complete=complete,at=clock(),
        coverage='HISTORY_EXHAUSTED_AS_REPORTED' if complete else reason)
