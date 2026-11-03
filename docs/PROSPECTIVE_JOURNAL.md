# Prospective experiment journal — source preview

Base: published v100.0 commit 1e0d88e0161c98f3f1328eeb9a40ebffe9826467. The owner
recommended persistent registered experiments before predictive validation or
automated paper execution. This candidate implements that research increment
as a source preview. The owner subsequently explicitly authorized committing
and pushing it. Running-installation changes and environment publication are
outside this delivery. No predictor or trading policy is adopted.

## What is implemented

Research notes has Register hypothetical experiment and View registered experiments.
Connect, Apply and Start the existing read-only study first. Registration requires
an explicit initial ETH what-if slice within the current fresh working proposal,
a source/target linked by an approved actual product, your signal ID, fixed horizon
and chosen entry assumption. Amount and horizon are unset by default, entry is
UNVERIFIED by default, and an acknowledgement is required. No choices in this chat
or real allocations are inferred. Costs freeze the applied taker stress.

For a BTC→SOL hypothesis, an explicit non-ETH source assumption models ETH→BTC
from the entered ETH slice. That frozen SIMULATED_ASSUMPTION is recorded as
provenance. It neither reports an actual BTC holding nor starts a reusable funded
wallet. The proposed BTC→SOL entry may be UNVERIFIED, NO_FILL, PARTIAL_OR_UNCERTAIN_FILL
or explicitly SIMULATED_ASSUMPTION. A quote touch never upgrades that choice.
Every registered case is an independent counterfactual, not a jointly funded or
statistically independent exposure. Do not sum the sizes or outcomes.

Registration stores the wall-clock start, original horizon, signal/uncertainty,
source inventory provenance, exact canonical entry costs, rules, quotes and fee
assumptions before future observations. Backdated registration, duplicate
replacement and unknown inputs fail. No maker/taker fee override or subscription
benefit is assumed. No-fill, unknown and adverse cases remain in the denominator.

Existing scans supply the current pass's observations; no new market, quote
request, polling loop or book-budget increase is added. Cached deferred books
cannot become a newly synchronous decision. The same v100 ForwardStudy and
canonical Decimal receipt own comparisons. This wrapper adds persistence, not
a competing cost model or an order engine.

The first observation at/after the fixed horizon is final inside the existing
30-second horizon observation window. Later favorable quotes cannot replace it.
Missing evidence is UNKNOWN_AT_HORIZON; reconnecting too late is MISSED_HORIZON.
A gap records elapsed unobserved time and keeps the original deadline. Closing an
experiment does not close a position or force liquidation. STOP cancels pending
journal writes; restarting observes or misses the original horizon without reset.

## Records and bounds

A separate file lives at private_data/research_data/CoinCat_Prospective_Experiments.sqlite3.
No financial database/schema/lot/basis/credential is modified. The file contains
private hypothetical native amounts and signals; do not upload it publicly.
The journal refuses an unrelated database, never imports financial records,
executes no persisted Python/pickle, and closes each SQLite handle before returning.

Versioned JSON preserves Decimal and Frame data explicitly. Immutable registration
and append-only events accompany an atomically updated current-state cache.
SQLite transactions roll back cancellation/failure, including final state and
events together. Reopening the journal restores the original signal/horizon and
conditional outcome, with no reinterpretation as settled funds.

Bounds: 32 waiting cases, 256 retained cases, a 32 MiB storage budget and 128 KiB
per encoded record. Historical cases are never automatically removed. Detailed
intermediate history samples at most once per minute plus gaps/quality changes;
after 512 details per case it records explicit truncation, while the latest state
and final outcome still update if storage permits. The storage guard pauses
writing when the budget is reached; SQLite can finish one bounded transaction
across that boundary. Local disk/format errors mark the journal UNAVAILABLE and
leave the existing maker observation loop operating. Exported errors are fixed
classifications, never raw paths or exception strings.

Local View registered experiments works while stopped and shows each signal,
direction, horizon, holding time, state and conditional source-HOLD difference.
It performs a bounded manual read, not additional polling. Public eight-section
diagnostics and monitor v3 contain aggregate counts only. They omit signal names,
experiment IDs, quantities, frozen inputs and native outcomes. Old/extra monitor
fields remain rejected. The old v100.0 monitor v2 is not changed on the PC.

## What the results can establish

The current app provides BBO and account-tier estimates, not sized depth or
verified fee debit currency. Most after-cost results will therefore remain
UNKNOWN, with the original frozen inputs and reasons retained. This is necessary
coverage evidence; this patch cannot establish a profitable predictor from those
inputs. The local synthetic suite separately exercises known positive, adverse,
non-fill, partial, unknown, gap and missed outcomes using labeled toy evidence.

A signal ID here is your manual preregistered directional hypothesis, not a
fitted/validated predictor. Confidence remains UNVALIDATED and public summary
remains NO DEMONSTRATED EDGE. Before any later automated experiment, specify a
reproducible signal rule and held-out protocol, quantify dependency between
samples, and verify cost/liquidity assumptions. Statistical significance, entry
fill modeling and automated paper settlement are separate future work. No 15%
automatic stop, allocation policy or recovery promise is introduced.

## Validation and evidence

The preceding published v100.0 has the owner's Windows result: 112 hashes pass;
251 tests run, 250 pass and one synthetic-symlink capability skip, zero errors or
failures. Its supplied diagnostic snapshot records about 2h10 of retained setups
without reported interruptions. That snapshot does not prove STOP/outage recovery,
an overnight run, all manual UI acceptance or the new candidate's Windows behavior.

Candidate focused/full/extracted validation is recorded in VERIFICATION.txt and
the logs beside its separate candidate ZIP. These are personally executed Linux
tests, not GitHub Actions confirmation or native Windows/account validation.
Protected financial/receipt/transport/lock modules remain byte-identical.
