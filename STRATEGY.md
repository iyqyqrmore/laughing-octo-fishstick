# Intelligent One-Leg Maker

The application evaluates BUY ETH with BTC and SELL ETH for BTC independently.
Each uses the smallest legal base quantity within 10% of available source funds,
including any source-denominated commission. An active order's remaining
quantity reserves only its unfilled source cost. The buy limit rounds down from
the native bid and the sell limit rounds up from the native ask. The exchange's
base and price increments govern a base-sized order. Its base and quote limits
apply to the exact implied gross notional. Shadow proposals are labeled LIMIT
GTC Post Only. Coinbase order endpoints are read-only in this release.

The immediate calculation values both the current and proposed portfolios at
the same synchronized ETH-USD and BTC-USD midpoints. The difference already
includes the proposed current fee via resulting inventory. The dashboard
also shows the proposed portfolio versus the original HOLD quantities. The
qualifying statistic is the improvement the new conversion would add to the
current portfolio, including when the portfolio already trails HOLD. The new
target asset must stay at or below 80% of modeled value. The native spread may
be at most 0.50%. A further 0.05% of destination value is withheld in the
decision as an uncalibrated adverse-execution allowance. It is absent from the
settled fee ledger.

The forecast targets are 5, 15, 30, 120 minutes and 24 hours. A simple
regime-conditioned median estimates ETH/BTC relative changes from closed,
synchronized five-minute USD histories. The regime is the direction of the
last hour. Each model uses chronological training followed by validation over up to 730 days and
requires at least 60 training outcomes and 100 validation outcomes in its
regime, with nonoverlapping target intervals within each split. It must improve
validation MAE over zero change. Empirical lower and upper validation
residuals are used conservatively for BUY and SELL respectively, with a 1%
one-sided tail allocation across ten directional horizon choices. These
empirical intervals can still lose coverage when regimes change or samples
are dependent. Prospective outcomes are tracked, with missing targets visible
in the ledger. Forecasts expire at their own target and use the original
forecast anchor when converting a conservative terminal relative price back
into USD. The projected BTC-USD mark is held flat for relative-value scoring.
An unsupported horizon stays unavailable. An immediate qualifying bid can
stand on its own. HOLD is the decision when no opportunity qualifies.

Only one shadow order may be active. Reviews are scheduled every 30 seconds,
with competitiveness reassessed after 120 seconds, a 600-second child limit,
a 1,800-second campaign limit, and up to three replacements. Replacement
funding, quantity and expiration carry forward from the original campaign.
Prices may only improve for CoinCat. A completed order changes inventory
without starting a new order to reverse it.

An overlapping public trade page is required to evaluate conditional fills.
The order qualifies only on strictly later trade-through by at least one tick,
using at most 1% of printed native base volume per trade, rounded down to
the base increment. The assumed execution price is the resting limit. A quote
touch, unobserved queue, or gap creates zero modeled fees and no invented fill.
Partial fills through the review cutoff are reconciled before cancel/reprice.
Account orders remain independent read-only evidence. Missing shadow evidence
freezes that reservation pending acknowledgment. Closing and crash recovery
keep the final uncertain interval visibly unresolved. The offline candle
replay uses a coarser model documented in the research report.
