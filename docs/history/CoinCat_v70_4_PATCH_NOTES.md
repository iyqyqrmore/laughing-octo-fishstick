# CoinCat v70.4 — every available holding and immediate reuse

Every positive, approved, available native balance remains funding inventory,
regardless of the position's dollar value or the total wallet size. A newly
received coin becomes fuel for the next decision as soon as processing updates
that wallet. **Real Coinbase order POST remains unconditionally blocked.**

* Use one source-inventory selector for fundable markets, urgent quote selection
  and unchanged-alert deduplication. With SHADOW armed, use the evolving wallet's
  actual cached quantities. Each SHADOW wallet still funds its own canonical
  plan; quote discovery can use their union without adding their money together.
  In account research, use min(enrolled, verified available) for every asset.
* Address the v70.2 diagnostic mark-refresh bottleneck: price a funded route
  before refreshing unrelated holdings. A fully priced Experimental SHADOW
  receipt can proceed while unrelated marks are missing; whole-wallet P&L stays
  explicitly NOT VERIFIED until complete synchronized prices arrive. The route
  book and its source/destination USD paths must be synchronized within 12s.
  Missing source/destination FX still blocks that route. Recheck FX once per
  actual pair, not once per size variant. Broad and urgent decisions use the same
  frozen-book RAM-wallet/P&L consumer. Validated marking requirements remain.
* Fix the validated wallet's newly acquired asset being omitted from urgent
  quote selection. No original-USD bridge, restart, reenrollment or history
  warm-up is needed to discover a direct route funded by an acquired coin.
* Rotate the bounded quote queue across all listed funding alternatives. Reuse
  fresh books instead of repeatedly spending the request budget on the same
  alphabetically first holdings. Deferred routes are counted in diagnostics.
  All positive native positions remain candidates; refreshing every book in
  the same instant is still subject to Coinbase request/freshness limits.
* Include current inventory and target direction in the unchanged-alert key.
  Processed wallet changes can trigger a fresh decision even if the last public
  trade price is unchanged. An unchanged wallet/alert still gets deduplicated.
* Remove the absolute dollar-score hurdle from Experimental SHADOW: accept only
  strictly positive after-cost experimental scores at any size. A small positive
  score below ten cents is no longer rejected solely for its dollar amount.
  This score remains unvalidated and can lose money. Zero/negative scores fail.
  The manual dollar floor is retained for Validated SHADOW and labeled accordingly.
* Preserve exchange minima/increments, available balances, explicit exclusions,
  current fee/quote checks and saved order/exposure/turnover/attempt limits. Fix
  the bridge's explicit exclusions when an excluded asset also has a balance.
  No private financial schemas, lots, credentials or actual data were changed.

Validation: **358 offline tests passed**, including twelve new regressions; complete
18/18 GUI diagnostics and Python 3.11 syntax passed. A synthetic $1.25 wallet
bought BTC, then funded ETH directly from the received BTC on the next decision.
Separate tests keep subminimum orders, exhausted turnover, nonpositive scores
and excluded holdings blocked. Forty tiny positive holdings stayed eligible;
all 25 funding alternatives were reached across bounded quote batches. A
22-source fixture reproduces incomplete unrelated marks without suppressing a
fully priced route or inventing whole-wallet P&L; subsequent full marks restore
an exact same-time HOLD comparison. Unsynchronized trade/FX prices and future
outcomes fail their independent checks.

Use [START_HERE.md](START_HERE.md) for installation and private-data import,
[DECISION_CHAIN_REVIEW.md](DECISION_CHAIN_REVIEW.md) for the math/communication
contract, and [VERIFICATION.txt](VERIFICATION.txt) for evidence. Windows execution,
Coinbase settlement and connected timing still require local verification.
The self-contained folder layout and versionless launchers are retained.
