"""Private display-only Coinbase portfolio references; never execution funding."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal as D,InvalidOperation,localcontext
import math
import re

from coincat_beta_store import BetaBlocked
from coincat_manual_trade import identity

REFRESH_S=15
MAX_AGE_S=30
MAX_POSITIONS=1000


def display_decimal(value):
    # This endpoint reports float-valued position estimates. Accept their
    # decimal rendering for display only; canonical exact financial math and
    # native account/funding parsers remain unchanged.
    if type(value) not in (str,int,float,D) or type(value) is bool:raise ValueError('Invalid portfolio display value')
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite portfolio display value')
    try:number=D(str(value))
    except InvalidOperation:raise ValueError('Invalid portfolio display value') from None
    if not number.is_finite() or not 0<=number<=D('1e24'):raise ValueError('Invalid portfolio display value')
    return number


def optional_number(value):
    try:return display_decimal(value)
    except (ValueError,TypeError,ArithmeticError):return None


def parse_portfolio(raw,scope,at):
    if type(at) not in (int,float) or not math.isfinite(at) or not 0<at<253402300799:
        raise BetaBlocked('PORTFOLIO_DISPLAY_TIME_UNVERIFIED')
    if not isinstance(raw,dict):raise BetaBlocked('PORTFOLIO_DISPLAY_RESPONSE_UNVERIFIED')
    scope=identity(scope);breakdown=raw.get('breakdown')
    if not isinstance(breakdown,dict) or not isinstance(breakdown.get('portfolio'),dict) or breakdown['portfolio'].get('uuid')!=scope:
        raise BetaBlocked('PORTFOLIO_DISPLAY_SCOPE_UNVERIFIED')
    balances=breakdown.get('portfolio_balances')
    total=balances.get('total_balance') if isinstance(balances,dict) else None
    if not isinstance(total,dict) or total.get('currency')!='USD':raise BetaBlocked('PORTFOLIO_DISPLAY_USD_UNVERIFIED')
    api_total=optional_number(total.get('value'));rows=breakdown.get('spot_positions')
    if not isinstance(rows,list) or len(rows)>MAX_POSITIONS:raise BetaBlocked('PORTFOLIO_DISPLAY_HOLDINGS_UNAVAILABLE')
    holdings={};accounts=set();complete=True
    with localcontext() as context:
        context.prec=80
        for row in rows:
            if not isinstance(row,dict):complete=False;continue
            asset=row.get('asset')
            if not isinstance(asset,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,31}',asset):complete=False;continue
            account=row.get('account_uuid')
            if account is not None:
                account=identity(account)
                if account in accounts:complete=False;continue
                accounts.add(account)
            elif asset in holdings:complete=False;continue
            quantity=optional_number(row.get('total_balance_crypto'));usd=optional_number(row.get('total_balance_fiat'))
            if quantity==0 and usd==0:continue
            complete=complete and quantity is not None and usd is not None
            if asset not in holdings:holdings[asset]=dict(asset=asset,quantity=quantity,usd=usd)
            else:
                previous=holdings[asset]
                previous['quantity']=None if previous['quantity'] is None or quantity is None else previous['quantity']+quantity
                previous['usd']=None if previous['usd'] is None or usd is None else previous['usd']+usd
        positions=sorted(holdings.values(),key=lambda v:(v['usd'] is None,-(v['usd'] or D(0)),v['asset']))
        subtotal=sum((v['usd'] for v in positions if v['usd'] is not None),D(0))
        remainder=None if api_total is None else api_total-subtotal
        tolerance=D('.02')+len(positions)*D('.005')
        if remainder is not None and abs(remainder)>tolerance:complete=False
        if any(breakdown.get(k) for k in ('perp_positions','futures_positions')):complete=False
        priced=any(v['usd'] is not None for v in positions)
        value=api_total if api_total is not None else subtotal if priced else None
        return dict(portfolio=scope,at=float(at),total_usd=value,reported_total_usd=api_total,
            total_source='COINBASE_REPORTED' if api_total is not None else 'PRICED_SUBTOTAL',
            positions=positions,priced_subtotal_usd=subtotal if priced else None,unlisted_difference_usd=remainder,
            complete=complete and api_total is not None)


class PortfolioDisplayReader:
    """One paced GET-only task on the existing worker, below execution/scan work."""
    def __init__(self,reader):self.reader=reader;self.data=None;self.failed=False;self.next_due=0
    def due(self):return self.reader.monotonic()>=self.next_due
    def overdue(self):return self.reader.monotonic()-self.next_due>=REFRESH_S
    def refresh_next(self):self.next_due=0
    def collect(self):
        r=self.reader;self.next_due=r.monotonic()+REFRESH_S;r.begin()
        try:scope=r.scope()
        except (ValueError,TypeError,KeyError,ArithmeticError):
            self.data=None;self.failed=True;return self.snapshot()
        if self.data is not None and self.data['portfolio']!=scope:self.data=None
        try:
            raw=r.call('get_portfolio_breakdown',portfolio_uuid=scope,currency='USD')
            self.data=parse_portfolio(raw,scope,r.clock());self.failed=False
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            if isinstance(exc,BetaBlocked) and str(exc)=='PORTFOLIO_DISPLAY_SCOPE_UNVERIFIED':self.data=None
            self.failed=True
        return self.snapshot()
    def snapshot(self):return dict(data=deepcopy(self.data),failed=self.failed)


def money(value,*,compact=False):
    if value is None:return 'UNKNOWN'
    if compact:
        for magnitude,suffix in ((D('1e12'),'T'),(D('1e9'),'B'),(D('1e6'),'M')):
            if value>=magnitude:return '$'+format(value/magnitude,'.2f')+suffix
    return '$'+format(value,',.2f')


def presentation(snapshot,now,connected):
    snapshot=snapshot or {};data=snapshot.get('data')
    if data is None:
        note='Portfolio unavailable' if snapshot.get('failed') else 'Connect to refresh'
        return dict(title='Total portfolio · USD',amount='—',caption=note,stale=True,
            hover='Selected Coinbase portfolio\n'+note+'.\nHoldings refresh automatically when portfolio data is available.')
    fresh=bool(connected and not snapshot.get('failed') and 0<=now-data['at']<=MAX_AGE_S)
    instant=datetime.fromtimestamp(data['at'],timezone.utc);stamp=instant.strftime('%H:%M:%S UTC')
    subtotal=data['total_source']=='PRICED_SUBTOTAL'
    caption=('Updated ' if fresh else 'Stale · ')+stamp
    if not data['complete']:caption+=' · partial'
    lines=['Selected Coinbase portfolio','Last refresh: '+instant.strftime('%Y-%m-%d %H:%M:%S UTC')+('' if fresh else ' · STALE'),
        ('Priced subtotal: ' if subtotal else 'Reported total: ')+money(data['total_usd']), '']
    for row in data['positions']:
        quantity='units unavailable' if row['quantity'] is None else format(row['quantity'],'.12g')+' '+row['asset']
        lines.append(row['asset']+'   '+quantity+'   ≈ '+money(row['usd']))
    if not data['positions']:lines.append('No spot holdings were returned.')
    if not data['complete']:
        lines+=['','Some holdings or valuations are missing from this breakdown.']
        delta=data['unlisted_difference_usd']
        if delta is not None and delta>D('.02'):lines.append('Other reported value: '+money(delta))
    lines+=['','Reference USD values before sale costs. Reported totals already include held balances.',
        'Other portfolios and balances not shared with CoinCat are excluded.']
    return dict(title='Priced subtotal · USD' if subtotal else 'Total portfolio · USD',
        amount='—' if data['total_usd'] is None else '≈ '+money(data['total_usd'],compact=True),caption=caption,stale=not fresh,hover='\n'.join(lines))
