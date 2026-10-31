# CoinCat v92 development kickoff — discussion draft

Started October 31, 2026 on local branch `coincat-v92`, based on verified remote
`coincat-eth-farmer-design` commit `e0c9b3596332265fd7a5a51c5309b3d5e95027ce`.
This starts planning for v92; application identity remains 91.0 until a coherent
implementation and release verification exist. Nothing has been committed,
pushed, published, or enabled for trading by this kickoff.

## Code review findings

- `app/coincat_eth_cycles.py` inventories both directions of approved products,
  constructs deterministic ETH funding/return paths, and reports topology only.
  It does not size, price, select, or execute these cycles. A cycle may have five
  legs; products reused on different legs must incur costs on each occurrence.
- `app/coincat_eth_farmer.py` models canonical costed returns into ETH, preserves
  residual assets, and leaves incomplete totals UNKNOWN. Its USD-W / ETH-USD
  re-denomination preserves the USD ranking; it cannot select the best ETH cycle.
  SWITCH models the existing USD winner rather than ranking all ETH-funded cycles.
- `app/coincat_working_allocation.py` separates exact owner authorization from
  snapshot-bound reconciliation. The GUI has no production reconciliation
  provider. Synthetic evidence objects are contracts, not verified settlement.
- `app/coincat_research_admission.py` forecasts all three horizon windows within
  six research books. The latest report still shows late actual collections;
  a capacity forecast is not a deadline guarantee.
- `app/coincat_live.py:LiveBroker.submit` still raises LiveBlocked as its first
  statement. Persistent execution, fill settlement and uncertain-order recovery
  are separate unfinished integration work.

## Proposed next steps for discussion with ChatGPT

- Agree on v92 scope: recommend a read-only ETH-cycle evaluator first, with
  actual order execution deferred to a separately reviewed implementation.
- Specify the ETH objective precisely: compare final net recoverable ETH with
  HOLD of the same authorized working holdings using one synchronized snapshot.
  ETH funds purchases and final proceeds must be ETH; intermediate BTC is not
  completed ETH profit. Do not count deposits or market revaluation as earnings.
- Decide sizing for the new evaluator explicitly: retain full verified working
  source semantics as the proposed default, with exchange-limit failures skipped
  rather than silently fitted. Existing full-account USD research stays labelled.
- Build a pure cycle evaluator using the existing canonical Decimal receipts on
  every funding, swap and return leg. Account for fees, slippage, spread, product
  increments/minima/maxima, existing target holdings and all native residuals.
  Specify shared-prefix/holding treatment so assets and fees cannot be counted twice.
- Add a read-only net-ETH ranking after evaluator validation. Keep USD research
  separate; do not substitute USD re-denomination for an ETH comparison. Reject
  incomplete or unsynchronized comparisons instead of assigning optimistic values.
- Design the verified reconciliation provider and cashflow-adjusted baseline:
  settlement, external/manual activity, unresolved orders, snapshot identity and
  evidence freshness. No balanced worksheet or checkbox can replace this evidence.
- Investigate the five late research collections before changing the scheduler.
  Replay remaining-time windows of 0.32–2.18 seconds and deferral histories;
  distinguish collection latency, retries, cadence and pauses from budget pressure.
- Improve dependency diagnostics: explain the 26 known account books versus the
  16-book pass cap, six catalog-route failures, stale/wide quotes and dust. Keep
  complete account totals UNKNOWN; synchronized asset groups cannot be summed
  across different timestamps into a purported current portfolio total.
- Preserve the mixer and proposed $10/$20/$10 reserve calculator. Discuss fixed
  reference changes, initial reserve versus first harvest, consumed milestones
  and loss/recovery semantics before any durable reserve journal is implemented.
- Validate in stages: offline cycle economics and negative cases, actual Tk/STOP
  behavior, full HTTP-forbidden regression suite, source-manifest/archive checks,
  native Windows verification, then fresh local read-only diagnostics. No offline
  result proves connected liquidity, actual fees, realized profit or execution.
- Keep live orders blocked until durable intents, idempotency, partial fills,
  fee-currency settlement and ambiguous-outcome/restart recovery are verified.
- Resolve the original stuck environment publication independently. A source push,
  saved configuration draft or connected new instance does not prove it finished.

## Latest uploaded evidence

Snapshot October 30, 2026, 4:49:59 p.m. America/Chicago. Resolved admitted endpoint
completion (completed / completed+missed, excluding pending): 413/424 = 97.4%
at five minutes; 346/364 = 95.1% at fifteen; 70/73 = 95.9% at sixty. Pending:
35/95/386. Admission: 459 of 1,572 distinct proposals. These are correlated
hypothetical observations, not trades. Misses: 27 BOOK_WIDE, five collections
finished after deadline. Recorded late decisions had zero competing groups and
zero committed research books, each requiring 2–4 books; sole cause is unproven.
All 1,626 approved directions have bounded ETH topology, with costs/sizing still
unverified. Account quote span 26.29 seconds exceeds 12 seconds. Working allocation
is owner-authorized but unreconciled; all 29 working assets remain model-ineligible.
No private asset quantities are included here.

## Safeguards carried forward

16 total quote books, six research books, 0.2-second GET spacing, server backoff,
0.25% maximum spread, 30-second quote age, 12-second synchronization, existing
0.9% estimated taker fee and 0.15% modeled slippage per leg. No relaxation to
manufacture opportunities. Preserve exclusions, native accounting, private ledger,
backups and the unconditional broker block.

## Kickoff validation

Python 3.11.17 with all twelve hash-locked dependencies installed. Existing source
verification: 108 hashes, zero mismatches. Focused HTTP-forbidden tests covering
ETH cycles, ETH farmer design, working allocation and research scheduler: 82 run,
73 passed, zero assertion failures, nine GUI setup errors caused by no DISPLAY,
zero skips. A supported virtual display could not be installed from the available
package index, so GUI validation remains unresolved. No test was changed or skipped
to conceal those errors. The full suite, native Windows checks and a v92 release
archive were not run or produced. Only these two new planning documents are changed;
they are not part of the existing v91 source manifest. No source-release claim is made.
