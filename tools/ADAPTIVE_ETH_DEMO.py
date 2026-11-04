"""Explicit synthetic offline example. No account reads, file writes or network."""
import argparse
from decimal import Decimal as D
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true',required=True,
        help='Acknowledge fictitious prices, sizes, fee units and depth; never real fill evidence')
    parser.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
    from coincat_adaptive_eth import Frame,ResearchFunds,ForwardStudy,scoreboard
    pairs=('ETH-BTC','SOL-BTC','SOL-ETH')
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,
        base_increment='.00000001',quote_increment='.00000001',price_increment='.00000001',
        base_min_size='.00000001',quote_min_size='.00000001') for p in pairs}
    def observation(at,sol_eth=D(1)):
        books={p:(sol_eth if p=='SOL-ETH' else D(1),)*2+(at,) for p in pairs}
        depth={};units={}
        for pair,book in books.items():
            for side in ('BUY','SELL'):
                depth[pair,side]=dict(pair=pair,side=side,observed_at=at,
                    levels=[dict(price=book[0],size=D(100))])
                units[pair,side]=dict(currency=pair.split('-')[1],verified=True,observed_at=at)
        # Zero here is an explicit toy assumption, not a fee fallback or membership benefit.
        return Frame(at,pairs,rules,books,dict(fresh=True,captured_at=at,maker=D(0),taker=D(0)),
                     _depth=depth,_fee_units=units)
    funds=ResearchFunds(D(1));start=observation(1800000000)
    receipt=funds.reserve('explicit-seed-assumption',leg=('ETH-BTC','SELL','ETH','BTC'),
        quantity=D(1),frame=start,slippage_bps=D(0))['receipts'][0]
    funds.assume_fill('explicit-seed-assumption',classification='SIMULATED_ASSUMPTION',
        input_quantity=receipt['input_quantity'],output_quantity=receipt['output_quantity'],
        fee_quantity=receipt['fee_amount_estimate'],fee_currency='BTC')
    study=ForwardStudy()
    study.freeze('btc-sol',funds=funds,leg=('SOL-BTC','BUY','BTC','SOL'),quantity=D(1),frame=start,
        horizon_s=60,signal='DEMONSTRATION_NOT_A_VALIDATED_PREDICTOR',
        exit_condition='COMPARE_AT_FIXED_HORIZON_WITHOUT_CLOSING',
        fill_state='SIMULATED_ASSUMPTION',slippage_bps=D(0))
    outcome=study.observe('btc-sol',observation(1800000060,D('.5')))
    print('CoinCat v1.03beta — SYNTHETIC / SIMULATED_ASSUMPTION ONLY')
    print('Toy prices are not market quotes. Source BTC exists only after an explicit assumed ETH sale.')
    print('Frozen conditional BTC → SOL versus HOLD BTC at 60 seconds:',outcome['outcome'])
    print('No rotation was settled into the separate paper wallet:',funds.inventory())
    print('Separate paper-wallet scoreboard:',scoreboard(funds,start))
    print('Research counts (independent counterfactuals, never pooled wallets):',study.summary())
    print('Live submission blocked. Real-account ETH unobserved; realized earnings NOT ESTABLISHED.')
    return 0


if __name__=='__main__':raise SystemExit(main())
