# v70.6.1 decision-chain review

The v70.6 selection/math review below remains applicable. This maintenance patch
changes reporting only. A reproducible concurrent SQLite WAL removal during
storage metadata collection formerly raised FileNotFoundError and discarded the
whole combined SHADOW section, including already-rendered experimental P&L.
One diagnostic-only retry handles the transient case. Independently rendered
subsections preserve wallet, learning, route, Snowball and strategy results;
persistent failures mark the parent export INCOMPLETE with a vetted code location.
Raw exception text, paths and variables are omitted. The shared storage functions
and financial/storage gates are unchanged. Disarming preserves RAM results;
re-arming or restarting begins a new modeled session.

The change replaces momentum-only experimental acceptance with a causal,
current-cost scenario screen. The fast discovery/quote workers, canonical
planner, financial arithmetic and segregated RAM FIFO remain the same.

| Stage | Contract | Verification |
| --- | --- | --- |
| Portfolio / fuel | min(enrolled, available) in native units; exclusions and restrictions bind. All positive positions considered, no wallet-dollar cutoff. Acquired SHADOW coins fund its next decision. | Existing tiny-wallet, 40-source, alternate-quote, reuse and late-exclusion tests. |
| AI Lab / decision | Approved listed one-order products, authenticated fees, fresh actual route and FX books. Rank all costed sizes using the same selection rule consumed by movement. | All-funding ranking, pair/direction/context, current-cost and causal SQL tests. |
| Auto Trader / movement | Explicit ARM; RAM wallet only; recheck approvals, current inventory, FX, budgets and evidence idempotency. | Actual fast producer → canonical planner → consumer → FIFO replay, including real learner cold/ready transitions. |
| P&L / diagnostics | Current wallet minus starting HOLD quantities at the same synchronized marks. Fees already change quantities. Missing FX never becomes zero. | Independent receipt/accounting assertions and complete 18-section GUI export. |

## Current-cost selection math

For the actual listed BASE-QUOTE conversion, let r[A,t] be its conservative
same-time USD mark for asset A. Passive public learning records:

```text
R(t) = r[BASE,t] / r[QUOTE,t]
BUY relative_growth  = R(later) / R(entry) - 1
SELL relative_growth = R(entry) / R(later) - 1
```

The actual conversion book and every USD-path book must be fresh (<=30s), narrow
(<=0.25%) and within 12s of each other. WebSocket trades supply the entry feature
bucket only, never an execution price. Use the actual pair's fresh 30-second
feature; an ALT-USD alert does not stand in for ALT-BTC training. Context buckets
are observed percentage changes: below -2, -2 to -0.5, -0.5 to 0.5, 0.5 to 2,
and >=2. SELL uses the exact inverse percentage change before bucketing.

The learner opens one pending window per pair from fetched approved books,
including unselected candidates, independently of ARM or wallet quantities.
Close after 300s only with an actually observed fresh comparable endpoint,
allowing at most 120s delay. Do not overlap the next window with the last close.
A late gap is MISSED, never a later gain. Keep three days of public observations;
query the last six hours and at most 96 rows per pair/side/context lookup. Eight
matching completed nonoverlapping windows and >=80% observed coverage are needed.
Overdue pending windows count as missing even before maintenance processes them.
The latest matched label must be <=720s old; current feature/evidence must be
<=30s old when consumed. Clock rewinds cannot read later labels or open a
window over a future close.

Let I and O be the actual input/output conservative USD values in the canonical
one-order receipt. The receipt already contains current fees, spread, assumed
slippage, native precision and source residuals. For historical gross relative
growth g, the current-source-USD scenario score is:

```text
net_scenario(g) = O * (1 + g) - I
score = min(net_scenario(empirical_mean), net_scenario(empirical_p25))
```

Require BOTH scenarios positive, with no absolute USD-score floor. The lower
quartile is an empirical order statistic, not a confidence bound. It is not the
validated SHADOW held-out P10. Future dollar magnitude also depends on the future
source/USD price: this is a relative-growth scenario in current source-dollar
units, not an absolute future USD prediction. The sign of switch versus source
HOLD follows relative growth; actual wallet P&L still uses actual later marks.
A test where both coins fall against USD checks this distinction: a destination
falling less than the funding coin can improve the relative comparison.

The immediate path needs no training history. Require BOTH the synchronized
Snowball hypothetical liquidation delta and the actual current receipt O-I to
be positive. Score the smaller. A cheaper hypothetical exit cannot turn an
immediately losing wallet receipt into immediate eligibility. Snowball remains
an estimate without depth/partial-fill verification, never a guaranteed arbitrage.

A successful forward-cost fill consumes its pair/side/context/last-label/fee
scenario version. New quotes, UI refreshes and size changes cannot charge another
fee against that same evidence. Failed budgets, blocked quotes and no-op FIFO
receipts do not consume it. New completed labels, qualifying contexts or fee
changes permit reconsideration; positive immediate routes remain separately
eligible. There is no global cooldown preventing a newly acquired asset from
funding another qualified family immediately.

## Receipt and P&L math retained

Let f be the authenticated taker fee estimate, s=0.0015 the slippage stress,
i the base increment, and r[A] the current conservative USD mark per unit.

```text
BUY (source QUOTE):
  budget = min(available_quote, cap_USD / r[QUOTE])
  base_received = floor_to_increment(budget / (ask*(1+s)*(1+f)), i)
  quote_spent = base_received * ask*(1+s)*(1+f)
SELL (source BASE):
  base_spent = floor_to_increment(min(available_base, cap_USD/r[BASE]), i)
  quote_received = base_spent * bid*(1-s)*(1-f)
HOLD_USD(t) = sum(starting_quantity[A] * mark[A,t])
MODEL_USD(t) = sum(current_model_quantity[A] * mark[A,t])
model_vs_HOLD(t) = MODEL_USD(t) - HOLD_USD(t)
```

Residuals stay in the wallet. USDC uses observed USD books, never a presumed peg.
One conversion charges one modeled fee; subtracting the displayed fees again
would double-count them. Exchange minima/maxima and explicit per-order, exposure,
rolling turnover and attempt limits apply before movement. Dollar budgets are
not conversion counts. Small wallets do not waive actual exchange minimums.
Fully priced experimental routes may proceed while unrelated marks are missing;
whole-wallet P&L stays NOT VERIFIED until all marks are complete and synchronized.
Validated SHADOW keeps its manual USD floor and chronological held-out gates.
LIVE submit still raises LiveBlocked as its unconditional first statement.

## Causal synthetic comparison and limits

Run `python -B tools/replay_cost_selection.py`. Each policy starts with synthetic
USD 1,000, uses a USD 10 cap, 0.9% fee, 15 bps slippage and 1 bp spread. Both use
the canonical Decimal planner and in-memory FIFO; features derive from prior
30-second artificial prices. The real passive learner sees outcomes only as the
artificial clock advances. No injected favorable evidence is used in this replay.
Rounded two-hour results on the cloud host:

| Artificial scenario | Old conversions | New conversions | Old vs HOLD USD | New vs HOLD USD |
| --- | ---: | ---: | ---: | ---: |
| Flat | 0 | 0 | 0.00 | 0.00 |
| One jump, then flat | 1 | 0 | -0.11 | 0.00 |
| Repeated reversing rebounds | 101 | 0 | -34.64 | 0.00 |
| Artificial continuous rise | 0 | 16 | 0.00 | +97.50 |
| Rise followed by reversal | 0 | 2 | 0.00 | -11.22 |

The reversing case paid USD 8.92 in old modeled fees versus zero new fees. The
new rule can still LOSE after learning a trend; it does not hedge or reverse
already bought inventory automatically. These chosen artificial paths test
causality, fee churn and limits, not predictive accuracy on markets. They are not
a representative sample or a profit benchmark. The continued-rise result cannot
be extrapolated. Neither policy promises to capture a real opportunity.

Separate capacity/accounting fixtures explicitly inject favorable SYNTHETIC
calibration to isolate small wallets, fast acquired-coin reuse, 12 decisions in
an artificial hour and retention beyond 144 lifetime routes. A constant-price
wallet loses costs in those fixtures, correctly. That calibration is never
shipped as market observations or used by the strategy replay. An independent
actual fast-chain test uses the real SQLite learner, starts cold with zero
conversions, then trains only on later artificial endpoints and posts one
qualified receipt. A refresh without a new outcome posts nothing further.

Single-pair passive learning/lookup was below 1ms median in these replays. A
separate cold-model workload with 804 products and 128 pair lookups measured
about 16ms median / 69ms maximum on this host. These CPU-only observations add
zero exchange requests and exclude Windows/HTTP latency. SQL busy work defers;
the progress handler is cooperative, not forcible cancellation of arbitrary
Python/SQLite/OS work. The existing five-second urgent target, bounded REST
batches, rotating scope and broad-worker checkpoints are retained. No claim
of professional HFT, guaranteed 10/hour, profit or complete opportunity capture.

A fresh installed model needs at least 40 minutes of matching valid windows,
often longer; positive immediate receipts need no such history. Histories in
older formats are not reclassified as these conditioned forward observations.
Use the current START_HERE.md import process, then run Windows verification and
connected read-only diagnostics to assess real observation coverage and timing.
No user financial data, credentials or raw uploaded diagnostics are in this release.
