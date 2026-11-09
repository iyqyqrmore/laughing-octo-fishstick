# CoinCat v1.05 decision and authority chain

`coincat_start → coincat_launcher → SpotApp` starts Manual Spot and one isolated `IntelligentTrader`. No legacy automatic controller is initialized. Authentication creates an SDK client through a pure factory; it does not import the old beta dispatcher.

The one worker prioritizes owned manual reconciliation, then bounded intelligent scans, portfolio/manual display and lower-priority historical backfill. Native rules/fee priming is separate from a combined decision frame. Each scan uses at most sixteen paced GETs within six seconds: scope, maker tier/account if due, seven native books, five USD references and public trades only for the active native pair. Historical pages use separate bounded jobs. No deferred/cached pricebooks become newly executable quotes.

`ForecastHistory → DIRECT_24H_ANALOG_V1` supplies direct 24h means, covariance/error estimates and provenance. `IntelligentPolicy` evaluates all fourteen native directions, sizes finite unreserved funds, models one entry commission, compares projected portfolios and ranks only positive risk-adjusted incremental advantage. A missing pair rejects that pair; full valid-hour coverage still requires all seven books and five synchronized USD references.

`MakerShadowTrader` manages a single local conditional order, reservations, partials, finite root budgets/expiry, explicit unknown reconciliation and canonical native settlement. `TrialStore/TrialClock` preserve original HOLD and 168 valid hours. No shadow component holds a manual authorization or dispatches an SDK write.

Manual orders follow a separate `ManualExecution → LimitOrderServices` path. Default live block, explicit click nonce, account permissions, caps, freshness, native rules, cancellation/reconciliation and unknown-POST lock remain unchanged. Switching manual block OFF never creates automatic shadow authority.

`intelligent_public → monitor capture → strict validator → read-only localhost helper` exports fixed facts/counts. Detailed portfolios, forecasts, native fees, trial/order IDs and receipts remain private. Old snapshots are historical; old record viewers never resume controllers.

See [retirement map](docs/V1_05_RETIREMENT.md) and [policy details](docs/INTELLIGENT_TRADER_V1_05.md).
