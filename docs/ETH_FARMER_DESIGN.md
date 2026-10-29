# ETH Farmer: read-only development increment

Base: `coincat-v91`, commit `752a01096e93e98cc72dc3d9287a338bd55d0c21`.
Work stays on `coincat-eth-farmer-design`; v91 history is preserved. This is a
development overlay, not a numbered v92 release or production execution build.
The October 29 handoff supplies design context. Its proposed financial policies
are not execution authorization. No production settings or datasets are changed.

## Objective and measurement

The eventual goal is more net recoverable ETH than HOLD of the same starting
working holdings, after all required costs. Deposits, withdrawals, manual ETH
buys/sells, transfers and market revaluation are not earned growth. This build
has no reconciled working/manual/protected allocation, starting baseline or
cashflow journal. Settled ETH, protected ETH, actual earned ETH and improvement
versus a cashflow-adjusted starting portfolio therefore remain **UNKNOWN**.
Account AVAILABLE ETH is separately observed, not proof of settlement or
authorization to spend manual holdings. The unconditional broker block remains.

The v91 one-full-available proposal and greatest-positive-USD-W ranking remain
unchanged. Exclusions, product rules, native quantities, residuals, fees once,
30-second quote age, 12-second synchronization and balance freshness remain.
Product maximum failures never trigger fractional fitting.

Two different ETH measurements follow ranking and cannot influence it:

1. **Re-denomination:** predeclare the fresh conservative bid of listed ETH-USD
   as common P. W_ETH = W_USD / P. Add its timestamp to synchronization checks.
   This preserves signs and ordering; it creates neither an edge nor a fill.
   Missing/stale/wide/future/skewed references mean UNKNOWN. There is no assumed
   stablecoin peg or favorable-reference search.
2. **Modeled ETH return:** for each asset, use the same deterministic shortest,
   then lexical, simple listed path (at most two return legs) in HOLD and SWITCH.
   Choose paths without checking profitability. Every leg calls the unchanged
   canonical Decimal receipt with full input, product limits, fee estimate and
   assumed slippage once. Intermediate quantities and rounding dust stay explicit.
   No circular path or profitable fallback is invented. All route/mark/reference
   dependencies synchronize. SWITCH includes the original costed entry, source
   residue and existing target holdings. Return costs are additional required
   legs, not a second charge for entry.

Complete recoverable ETH is UNKNOWN if any relevant quantity is unpriced,
unconverted or product-blocked, including dust. Proceeds subtotals explicitly
exclude retained native quantities and are never called total recoverable ETH.
Secondary USD marks also fail closed on missing assets/skew. Excluded holdings
are outside these account-available-scope totals. Sized depth, actual fee currency
and exchange timing remain unverified even when a top-of-book model is complete.
This increment is not an arbitrage route selector or atomic execution model.

Scanner inputs are frozen with each result. Mixer edits remeasure that snapshot
instead of mixing newer balances with older quotes. STOP retains findings and
rejects queued results using the existing generation guard. A retained snapshot
never becomes a current executable quote.

## Proposed reserve and mixer

The `$10 initial / $20 earned step / $10 harvest` defaults are editable what-if
values, not applied policy. An explicit fixed USD/ETH reference is required
(0 means unset). No market quote silently becomes a financial benchmark. The
calculator divides each USD amount by this fixed reference; this convention is
chosen only for the preview. Actual reserve and earnings stay UNKNOWN.

Earnings are never inferred from account changes or Lab outcomes. The pure
calculator also accepts labelled synthetic scenarios to exercise consumed
milestones, loss/recovery and insufficient settled ETH. It counts only crossings
beyond a supplied consumed high-watermark and never advances state. Replaying or
resetting a scenario is not a second harvest. Insufficient settled ETH stays
pending: no auto-buy, reserve journal, earmarking, transfer or ledger mutation.

Six visible strips preserve the shell and five high-level actions. Each has a
vertical fader, exact Decimal entry, units/range, default/current markers, reset,
pointer/keyboard tooltip, focus access, arrow keys and Home/End. Invalid entries
retain the previous accepted value. Controls are starting reserve, growth step,
harvest, fixed reference, modeled **return-leg** slippage (0–50 bps) and manual
scan interval (5–60 seconds after each pass). The v91 ranking's 15 bps assumption
and hard evidence/freshness constraints cannot be changed. No discretionary
profit floor or portfolio cap is introduced. Only cadence changes an operational
timer. All values are RAM-only and reset at restart; legacy settings are untouched.

Manual/working allocation, exclusions, cost/freshness evidence and execution
block remain visible. No ARM, shadow/GPU mode or automatic optimizer is added.

## Passive settings advisor

Bounded RAM observations and ~180-second notes remain. 5/15/60-minute comparisons
may also be expressed in ETH at the synchronized endpoint reference. These are
re-denominated hypothetical comparisons, not return proceeds, independent samples,
wallet posts or earned ETH. Missing references and missed endpoints have separate
counts. Original USD comparison counts remain distinct.

The advisor is a deterministic text-only rules function with no client, setting
writer, wallet or execution reference. If quote collection takes longer than the
current scan interval, it may suggest a longer named Scan interval, stating
current/suggested seconds, measured observation, PRELIMINARY grade, evidence limits
and load-versus-coverage trade-off. Otherwise its INSUFFICIENT message is:
"No setting change recommended; actual execution economics are not verified."
Every note says "Manual decision only / no setting changed." Correlated positive
reviews never justify performance claims. There is no apply callback or AI gate.

## Diagnostics and deferred decisions

All eight v91 coverage themes remain. ETH status, timestamps, reference price,
synchronization, unknown allocations, proposed values and unconverted-asset counts
are added inside existing sections. Raw balances, modeled wallet quantities,
account IDs, keys, private paths and raw errors remain excluded from exports.

Before persistent financial implementation, the owner must choose and authorize:
initial reserve versus future-first-harvest semantics; reference recording and
changes; reconciled manual/working allocation and external-flow tagging; ETH-funded
closed loops versus other starting assets; execution/multi-leg risk evidence; and
any optional research margin. None blocks this read-only preview, and no answer
is silently applied to holdings.

Actual earned/reserved ETH requires reconciled completed events and a separate
durable journal, distinct from immutable tax lots. Execution additionally requires
candidate-sized depth, verified fees, durable order identities, duplicate prevention,
partial-fill settlement and uncertain/restart recovery. No order, preview, transfer,
auto-ARM or live qualification is authorized by this design or passing tests.

See ETH_DESIGN_VERIFICATION.md for current commands/evidence. Historical v91 release
verification remains in VERIFICATION.txt and is not relabeled as this increment.

The subsequent scheduling/coverage update is documented in QUOTE_COVERAGE.md.
It preserves this ETH measurement policy and proposed reserve semantics while
using the existing GET budget more fully, scheduling due fixed-path observations
and suppressing cadence advice when coverage evidence is incomplete.
