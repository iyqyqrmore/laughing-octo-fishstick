# CoinCat v90.1 reporting patch

Baseline: clean v90.0 commit b32a539c29bb5b1b9e8ffb61e25c5cc7f5340597.
This patch incorporates the prior pre-consumer rejection audit and measures the
existing urgent discovery workflow without changing pricing or execution policy.

## What to test

Extract the complete source ZIP into a separate folder. Preserve the working
installation, private_data and private_backups. Run 02_SETUP_COINCAT.bat and
03_VERIFY_COINCAT.bat; expect CoinCat v90.1 and 449 distinct offline tests.
Native Windows execution still needs PC-side verification. Permanent fresh data
requires the existing explicit confirmation and an empty destination.

Connect locally, leave real trading disarmed, and manually start Experimental
SHADOW if desired. After 30–60 minutes, STOP Experimental and export the complete
diagnostic while the app remains open. All 18 sections should complete.

- Discovery cycles have unique IDs, start and completion times. The consumer
  retains the originating cycle and its own later evaluation time.
- SAME_CYCLE_REEVALUATED_AT_CONSUMER identifies origin, not identical prices or
  economics. DIFFERENT_CYCLES means the latest discovery and consumer snapshots
  must not be compared as if they were one observation. UNLINKED is explicit
  when either origin has not been observed.
- For the latest handoff and the complete manually armed session, submitted
  sizes equal pre-consumer rejected sizes plus reviewed sizes. Session totals
  reset only on a new ARM, remain after STOP, and are lost on app exit.
- A zero-observation session is labeled NOT_OBSERVED. Counts are repeated sizes,
  never independent opportunities, executions, or proof of profit.

## Coverage definitions

Each product/BUY-or-SELL direction in the last observed eligible funding scope
has separate last-selected, last-evaluated and last-complete times. Selection
alone does not establish an evaluation. A pricing evaluator must actually run;
a complete frame must calculate modeled W and L, even when negative.

All evaluated sizes are measured before the display shortlist is clipped.
Distinct direction counts are deduplicated; event counts include repeat cycles.
The exported rolling 60-second view includes never-selected, never-evaluated,
never-complete, recently-complete and overdue-complete counts, plus counts by
market quote currency. Recent + overdue + never-complete equals eligible.
It does not claim full-catalog coverage or a measured fill rate.

The scope has its own observation timestamp and age. Removing a direction drops
its record and window events; re-entry begins a new eligibility interval. The
direction records live in RAM independently of ARM, so discovery can continue
after the consumer stops. This is not a durable candidate audit trail.

Window events are bounded to 8,192 entries. A truncated window is explicitly
flagged and its event-drop count reported. Expired events are removed after
60 seconds. No candles, missing frames or missed opportunities are reconstructed.

Open **Immediate opportunity details** for a local list of each eligible product
and direction, its evaluation ages and latest outcome. Shared diagnostics export
aggregate coverage only; they do not add private funding quantities.

## Separate populations and policy labels

`selected_without_costed_receipt` counts selected directions that did not reach
a costed planner receipt. It is separate from `unpriced_routes`, which counts
costed routes that the immediate evaluator could not price. The four mutually
exclusive costed-route outcomes sum to `distinct_routes`; separate size-state
counts sum to `size_trials`. When sizes disagree, a route is positive if any
size is positive, otherwise zero if any is zero, otherwise negative if any is
negative, otherwise unpriced. Individual size results remain unchanged.

Archived advisory Snowball comparisons, legacy advisory BUY signals and
Validated-track dollar floors are labeled separately. Primary Experimental
continues to require both W>0 and L>0 without an absolute dollar floor.
Readiness and health sections have independent timestamps and exact heartbeat
ages, preserving stale, missing and clock-conflicting observations. One stale
snapshot alone does not diagnose a persistent GUI freeze.

## Boundaries and next work

Complete modeled pricing does not verify exchange quote-event time, sized depth,
fee currency, executable previews, fills or profitability. Local request and
evaluation timestamps remain local observations. LIVE stays unconditionally
blocked; normal UI synthetic qualification remains disabled.

Alternative USD-path retry still needs a separate consistent pre-profitability
selection policy and adversarial HOLD/SWITCH tests. Candidate-sized depth,
authenticated fee-preview semantics and durable manual-experiment accounting,
uncertain-order recovery and duplicate prevention remain separate work. The
public references in ENGINEERING_REFERENCES.md inform these requirements;
no external bot libraries or strategies are installed or copied.
