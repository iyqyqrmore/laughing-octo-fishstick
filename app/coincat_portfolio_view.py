"""RAM-only reference valuation of the watched basket, never trading profit."""
from decimal import Decimal as D,localcontext
from coincat_v701_quotes import valid_book
from coincat_watchlist import WATCH_ASSETS
from coincat_working_allocation import quantity


class PortfolioView:
    def __init__(self):self.baseline=None;self.baseline_at=None

    def measure(self,balances,account_at,books,now,*,reset=False):
        fresh=account_at is not None and 0<=now-account_at<=120
        quantities={asset:quantity(raw) for asset,raw in balances.items()}
        outside=tuple(sorted(a for a,q in quantities.items() if q>0 and a not in WATCH_ASSETS))
        missing=[];value=D(0)
        with localcontext() as context:
            context.prec=60
            for asset in WATCH_ASSETS:
                amount=quantities.get(asset,D(0))
                if not amount:continue
                if asset=='ETH':value+=amount;continue
                pair='ETH-BTC' if asset=='BTC' else asset+'-ETH'
                quote=valid_book(books.get(pair),now,30,D('.0025'))
                if quote is None:missing.append(asset);continue
                midpoint=(quote[0]+quote[1])/2
                value+=amount/midpoint if asset=='BTC' else amount*midpoint
        complete=fresh and not missing
        current=value if complete else None
        if reset:self.baseline=None;self.baseline_at=None
        if current is not None and self.baseline is None:
            self.baseline=current;self.baseline_at=now
        return dict(eth_held=quantities.get('ETH',D(0)) if fresh else None,
            watched_value_eth=current,change_eth=None if current is None or self.baseline is None else current-self.baseline,
            baseline_at=self.baseline_at,missing_assets=tuple(missing),outside_assets=outside,
            account_fresh=fresh,valuation='MIDPOINT_REFERENCE_BEFORE_EXIT_FEES',
            flow_adjusted=False,trading_profit='UNVERIFIED')
