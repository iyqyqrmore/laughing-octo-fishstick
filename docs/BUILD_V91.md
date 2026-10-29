# v91.0 simplification

Requested policy: ranking #2, greatest positive immediate after-cost USD wallet
advantage versus HOLD, sized at the entire verified AVAILABLE source balance.
The existing Decimal native receipt is the one source of fees, sizing and
rounding. No percentage reserve, portfolio/day cap, fraction grid, profit floor
or future forecast gate is imposed by this scanner. Exchange product limits and
existing exclusions remain meaningful. Cash/stablecoin holdings can fund actual
listed direct products; no mandatory USD bridge or assumed stablecoin peg.

The owner explicitly requested removing redundant modes and shadow experiments.
The default application was replaced with one read-only scanner and a passive
AI Lab. Legacy modes, neural/GPU jobs, budget advisers, shadow wallets and old
verification buttons were retired instead of hidden behind new UI controls.
The database schemas, private records and protected financial core were not
rewritten. Core financial/recovery tests were retained; fresh-data/key-signing
cases from mixed retired suites were carried forward unchanged.

The report now has eight active sections: connection, policy, coverage,
immediate result, cost evidence, passive AI Lab, local records and execution.
No actual order, API identifier, raw exception or private balance is exported.

Available quantity comes from fresh Coinbase AVAILABLE balances. Historical
approved quantities and tax lots are not reset to match that snapshot; only the
scanner's proposals use the owner-requested full available amounts. Existing
exclusions are respected. This does not certify a future full-balance financial
settlement against an older local authorization or lot inventory.

The app makes no order calls. Enabling actual automatic swaps is unfinished:
production intents, fill/fee-currency settlement, restart recovery, duplicate
prevention and uncertain-order handling need integration and separate validation.
No cloud trade or authenticated order-preview request was made for this build.

AI Lab reports observed facts about every 180 seconds. At most one proposal per
direction per five-minute window is retained for later 5/15/60-minute public
price comparisons, with a bounded 512-entry RAM queue. Pending, deferred and
missed counts remain visible; outcomes are correlated and hypothetical, not
trades or profit. The input record is fixed before the observation horizon.

Remaining libraries were kept at their v90.1 versions and hash locked. Twelve
runtime dependencies replace twenty-five; unused matplotlib/numpy/plotting
packages and websocket-client are absent from the fresh test environment.
The official Coinbase SDK still requires its own websockets dependency.

Install/test in a separate source folder; never overwrite the running instance
or discard private_data/private_backups. Windows/DPAPI, real account semantics,
exchange fills and actual profitability remain unverified by cloud tests.
