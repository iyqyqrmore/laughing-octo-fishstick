# CoinCat v70.3 — faster one-order decisions and consistent accounting

The portfolio, canonical planner, isolated SHADOW wallet and P&L now share
explicit approval, currency-unit, budget and market-observation contracts.
The self-contained private_data/private_backups layout from v70.2 is retained.
**LIVE Coinbase order POST remains unconditionally blocked.**

* Apply Coinbase eligibility/restrictions, numeric product rules, online status
  and explicit asset exclusions before selecting trade books or computing routes.
  Sources must be enrolled and available; destinations may be any approved spot
  asset. Stablecoin and crypto quotes remain eligible when actually listed.
  No fabricated reverse product, bridge or multi-order funding basket enters the
  active one-order handoff. Excluded assets already held can still require
  separate valuation books; those books never create trade candidates.
* Validate books and compute each currency's USD path once per decision. Cache
  evidence once per source/target, rather than every size variant. Empty threshold
  evidence returns immediately. Journal a fast quote batch in one research DB
  transaction. Urgent decisions defer the optional background SELL advisory;
  required funding, fee, product and freshness checks remain. Existing checkpoints
  let urgent work run during broader research.
* Rank all costed proposals before clipping, using the same provisional score in
  the planner and experimental consumer. Score actual net destination receipts,
  retain rounding residuals, and invert falling-base relative changes correctly
  when studying the quote asset. Momentum remains an unvalidated assumption.
* Remove the experimental 15-minute family cooldown and pending-outcome lock.
  Suppress repeated consumption of the same route/quote observation. Fresh
  decisions proceed while earlier outcomes are measured. Completed outcome
  storage no longer creates a lifetime 144-route stop; missed 5/15/60-minute
  windows are not substituted with arbitrarily late observations.
* Correct SELL budgets to price BASE units and BUY budgets to price QUOTE units.
  Both sides count toward one-order conversion turnover. Attempts remain counts;
  wallet dollars no longer cap them. Honor saved daily turnover separately from
  available fuel, so capital can be recycled within explicit limits. Apply active
  SHADOW budgets before sizing, then recheck before movement. No defaults or saved
  operator limits are automatically increased.
* Freeze urgent decision books through the RAM wallet handoff; recheck approvals,
  inventory and budgets. A FIFO replay/no-op does not count as a new conversion.
  Do not overwrite held-wallet valuation rates based on candidate selection.
* Refresh experimental P&L after urgent decisions and refresh its age while idle.
  Show rolling-hour modeled conversions separately from real orders. Report
  exploratory routes accurately and distinguish urgent/broad-scan freshness.
  The common Snowball panel keeps the newest decision's evidence. GPU example
  collection is limited to the current approved product scope.

Validation: **346 offline tests passed**, including 16 new chain tests, a
12-conversion synthetic hourly replay, 150 sequential synthetic conversions,
exact receipt/FIFO comparisons and complete 18/18 GUI diagnostics. The same
profiled synthetic workload of 804 products, 23 funding assets and 207 size
checks fell from **7.710s to 0.263s** on this cloud CPython 3.11 host. That measures
planner work, not Coinbase latency or actual execution speed.

Ten actual trades/hour cannot be established by these tests. A saved limit of
12 conversions/24h cannot permit 10/hour all day: that needs capacity for at least
240/24h and sufficient turnover, as well as qualifying opportunities. No quota
forces a trade. Default limits remain unchanged.

See [DECISION_CHAIN_REVIEW.md](DECISION_CHAIN_REVIEW.md) for math and limitations,
[VERIFICATION.txt](VERIFICATION.txt) for evidence, and [START_HERE.md](START_HERE.md)
for installation. The user's actual databases, tax lots and credentials were not
accessed or changed. Windows/DPAPI/CUDA and connected Coinbase timing still need
local verification. Historical release notes are under docs/history.
