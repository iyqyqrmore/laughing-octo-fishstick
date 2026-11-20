# Commission accounting

The authenticated Coinbase spot transaction summary supplies the applicable
maker and taker values. Product rules are read separately. A missing or expired
fee check leaves the maker rate unverified and stops new proposals. A rate
change ends the old shadow order after reconciling any evidenced fills.
The app sends no actual orders.

A conditional fill of `q` ETH at `p` BTC per ETH records one modeled
commission `q × p × maker_rate` in BTC. BUY adds `q` ETH and spends gross
BTC plus the fee. SELL removes `q` ETH and adds gross BTC less the fee. Each
partial uses only its own filled quantity. Inventory reflects the fee, so
mark-to-market does not subtract it a second time. An unfilled or canceled
remainder incurs zero execution commission. A later conversion uses its own
then-applicable rate when it fills.

The proportional estimate uses Decimal arithmetic; model commission precision
is independent of exchange price increments. The BTC denomination is an
explicit modeling assumption. Actual Coinbase receipts preserve the provided
commission value, precision and currency evidence. Unknown currency prevents
aggregation of that receipt's commission. Original receipts and conflicting
revisions are retained locally. Actual receipts are separate from shadow
inventory, and importing them never reseeds HOLD. No charge is assigned to
CoinCat from the counterparty or an unexecuted leg.

The fee tool labels current one-leg maker and taker rates independently. Its
two-maker, two-taker, and mixed rate sums are hypothetical research comparisons.
Each sum excludes spread and price changes. These round-trip figures are
informational and excluded from one-leg decisions.

On November 9, the ETH-BTC manual Post Only BUY at 0.028457 BTC/ETH was
reported to fill 0.00496514 ETH after approximately 65 seconds. The order
form showed an estimated 0.50% maker commission and the UI displayed a
rounded fee of 0.000001 BTC. Those fields are execution context and do
not establish the fee's unrounded value, queue position or a profitable
forecast. The user's v1.06 notes reported the 0.50% maker and 0.90% taker
fee verification. v1.07 requires its own current verification.
