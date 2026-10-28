# CoinCat v70.6 — fast scanning with forward-cost selection

This patch addresses modeled fee churn after v70.5. It retains the same fast
stream checks, approved catalog, all available native funding, direct one-order
planner, acquired-coin reuse, self-contained folder and RAM FIFO accounting.
**LIVE order POST remains unconditionally blocked.**

* Stop treating an observed price rise as a forecast that it will repeat.
  Momentum still discovers candidates. A price rise by itself cannot spend
  the experimental wallet. The old score remains an offline replay baseline.
* Keep immediate eligibility when BOTH the actual after-cost wallet receipt and
  the synchronized Snowball liquidation comparison are positive. A merely
  cheaper hypothetical exit cannot justify an immediately losing wallet mark.
  This path needs no training history and has no absolute USD-score floor.
* Learn passively from later public books using the SAME canonical research
  SQLite file. No wallet quantities, keys, financial-ledger access, additional
  requests or second planner are introduced. Learning continues while the
  experiment is OFF and persists across restarts/imports of the research DB.
* Compare the actual destination coin against its source coin. USD momentum
  alone can be misleading when a crypto holding funds the swap. BUY and SELL
  use inverse relative growth on the actual listed conversion pair; a different
  discovery product cannot supply that pair's feature history.
* For the forward-cost path, require at least eight nonoverlapping five-minute
  observations matching the current 30-second feature bucket, in the last six
  hours, with at least 80% observed coverage. Both empirical mean and lower
  quartile must cover the CURRENT receipt's fee, spread, assumed slippage and
  rounding. This is an experimental scenario screen, not a confidence bound,
  validated forecast, recommendation to trade or guarantee of a gain.
* Only already completed outcomes enter a decision. Stale, wide, missing or
  skewed endpoint books cannot label a result. Windows missed by more than 120s
  stay missed. Expired pending windows count against observation coverage.
* Once a scenario posts, a new quote or size cannot reuse the same
  pair/side/context/last-label/fee evidence to charge another modeled fee. Failed
  budgets or no-op receipts do not consume it. A new label, qualifying context,
  fee change or positive immediate receipt can be reconsidered. Newly acquired
  coins remain available for other qualified direct conversions immediately.
* Diagnostics show passive observation counts, eligibility/rejection reasons,
  immediate versus forward-cost conversions, modeled fees, turnover and wallet
  value versus same-time HOLD within the existing 18-section report.

A fresh installation will usually observe rather than convert until sufficient
matching evidence exists: at least 40 minutes for eight uninterrupted windows,
often longer. `OBSERVING_NO_COST_EDGE` is a normal result. This does not stop
scanning or block a qualifying positive immediate receipt. Ten conversions per
hour is capacity only; low funds do not create an edge or waive exchange minima.

Validation uses synthetic prices and account data with HTTP blocked. The causal
two-hour replay shows reduced fees in a reversing-rebound scenario, and also a
losing trend-to-reversal scenario under the new rule. It does not establish
profitability on Coinbase. See DECISION_CHAIN_REVIEW.md and VERIFICATION.txt.

Install using START_HERE.md and import the complete private_data from your
currently active installation. No private records, tax schemas, lot IDs, keys,
saved spending limits or real-order permissions were changed by this patch.
Keep old folders until the existing verified copy/backup/cleanup checks pass.
