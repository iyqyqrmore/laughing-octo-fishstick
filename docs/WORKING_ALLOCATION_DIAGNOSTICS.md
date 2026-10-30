# Working allocation and ETH conversion diagnostics

Focused read-only follow-up to `99e929e630d38a31850039fff644a25588311f5f` on
`coincat-eth-farmer-design`. The original immediate USD-W ranking still models
full AVAILABLE source balances. This patch does not enable ETH-profit selection,
order execution, previews, transfers, automatic reserves or financial writes.

## Local working-fund worksheet

The **Working allocation** tab offers exact native-unit entries for a selected
asset's working, manual and protected amounts. Protected amounts must be ETH.
Existing ledger exclusions assign the entire available asset to EXCLUDED and
cannot be overridden here. Any remaining quantity is UNASSIGNED, never silently
working or manual. All buckets are disjoint and cannot exceed AVAILABLE. Invalid
edits retain the preceding draft. No fractional order-fitting policy is introduced.
The worksheet scrolls at the existing minimum window size, with a separate
scrollbar for the asset list so every holding remains accessible.

Use Apply selected draft to record each row in RAM. A separate owner checkbox
and Record draft authorization action authorize the exact working proposal.
Checking the checkbox alone grants nothing; unchecking revokes authorization.
Edits, changed available native balances or changed exclusions invalidate it.
Clear draft and application restart discard the entire proposal/authorization.
No draft, private quantity, authorization or setting is saved to disk.

A balanced worksheet and owner approval do **not** establish reconciliation.
The application supplies no verified reconciliation provider, so all GUI drafts
remain ineligible for future execution. The pure contract additionally requires:

- Complete accounting of available quantities, including explicit manual,
  protected and excluded buckets; no unknown remainder.
- Owner authorization bound to the exact draft and available-balance contents.
- Verified settled-funds and external-flow evidence bound to that draft and
  the particular balance snapshot, with no unresolved orders.
- Fresh balance and reconciliation observations (120 seconds), with no future
  timestamps. Evidence references remain private and are never exported.

Synthetic callers can test this contract using `ReconciliationEvidence`; such
objects are fixture attestations, not independently verified production evidence.
A future reconciler must actually verify settlement, manual activity, deposits,
withdrawals and uncertain order outcomes. New snapshot evidence is required even
when net balances happen to be unchanged. No current execution code consumes
this model and `live_order_permission` always remains false.

Only those explicit working native quantities can enter the separate working-ETH
model. Manual, protected, excluded and unassigned funds cannot enter it. If the
contract fails, working ETH stays UNKNOWN; it never falls back to the account
total. Account-available ETH remains separately labelled. The proposed $10/$20/$10
reserve calculator does not populate protected ETH, infer earnings or earmark funds.
The existing USD scanner remains an account-available research view, not a claim
that all its hypothetical source quantities belong to CoinCat.

## Individual conversion evidence

The **ETH conversion blockers** tab and diagnostics list public asset symbols,
routes and controlled reason codes, without native amounts. Structural analysis
uses the supplied authenticated product catalog and the existing two-leg bound.
It distinguishes a missing bounded route, unapproved/restricted product, missing
verified product rules, and missing bounded USD mark/reference dependencies.
An absent catalog product is not proof of delisting or a regional restriction;
the broker may already have filtered it. Reasons report only available evidence.

For modeled conversions, every original holding has its actual observed route
and any verified blockers: unobserved, wide, stale, invalid or future quotes;
base/quote minimum or maximum; precision below the increment; canonical rounding
residue; unclassified canonical rejection; stale balances; missing ETH reference;
or account-wide price skew. Multiple violated constraints remain visible. Residue
asset symbols identify intermediate dust without exposing its quantity. An
independent frozen last-observed quote cache explains stale quotes even after
they have left the pricing cache; it can never supply a price to the model. These
are last-observed conditions, not proof of current market conditions. An
unconverted native-asset bucket count can differ from the number of original
holdings with blockers. Unknown inputs remain explicitly unverified.

The canonical Decimal receipt still owns amounts, costs, increments and residuals.
Diagnostic arithmetic only explains its failures; it never produces a smaller
replacement order or raises an amount to an exchange minimum. Incomplete or skewed
measurements never become complete ETH totals. Spread stays 0.25%, quote age 30s,
and synchronization 12s. Fee/slippage estimates and profitability requirements
remain unchanged; a synchronized asset group alone proves no executable ETH edge.

The previous report contained aggregate counts for six unsupported assets and
27 unconverted native buckets, without identities/quantities or full dependency
traces. Their individual historic causes cannot be recovered from those counts.
The new build must observe a local snapshot to produce the detailed evidence.

## Observation deadlines, within the existing scheduler

Admission forecasting is unchanged: all three future jobs must fit its conservative
calendar. It is an estimate, not the same guarantee as actual shared-budget packing.
Actual selection now protects the earliest individual deadline when another
estimated service period plus a full six-second collection might not fit. Outside
that last conservative turn, the previous aging EDF order remains. The manual
cadence is passed to selection; no cadence, request limit or quality rule changes.

Each due job records its own deadline window, required and additional books,
research books already committed, competing groups and estimated remaining time.
Reasons distinguish the six-book limit, a lower overall budget, dependencies that
cannot fit together, competing groups, less than a collection window remaining,
and no conservative retry window. Actual collection finishing after the deadline
is recorded separately. Cached/shared books remain deduplicated; job counts are
not HTTP request counts. Each pass still requests at most 16 books, at most six
for research, with unchanged spacing, workers, collection deadline and backoff.

On expiry, the latest capacity-related evidence is exported as one record per
miss, without observation IDs, routes or quantities. The RAM ring retains 256
records and reports how many older records were dropped. Per-observation deferral
counts and expiry/service gaps accompany horizon-level counters. The latest
observed blocker is not asserted to be the sole cause: a pause, outage or later
quality failure can also intervene. STOP discards scheduling changes before these
records or counters are committed, as before.

The uploaded report's six 15-minute and two hourly capacity misses have no
per-job histories. No exact retrospective replay or sole-cause claim is possible.
The new eight-episode synthetic fixture uses the same horizon mix: an observation
has 10 seconds left while another horizon has aging priority and 120 seconds left.
Both complete over two 12-second turns, each requiring five books, without any
new admissions. Exact previous source (`99e929e`, SHA-256 recorded in
`offline_tests/deadline_contention_baseline.json`) misses all eight urgent jobs;
the patch completes all eight and all eight competitors, still at five GETs/turn.
This demonstrates a specific avoidable starvation case, not elimination of the
historic misses or guaranteed live completion.

The existing three-hour healthy replay retains 1469/0, 1387/0 and 1012/0 completed/
missed results at 5/15/60 minutes, with 1524 admissions and 6585 refusals. Pending
and refused jobs are excluded from those completion denominators. These are
correlated constant-price synthetic observations, not fills or independent samples.
Live acceptance remains approximately 90%+ across all horizons with market-data
rules intact, and evidence for every remaining capacity miss. That needs a new
connected local report; offline tests cannot certify it.

## Verification and boundaries

Run the full HTTP-forbidden suite with pinned Python 3.11 and hash-locked packages:

```sh
cd /workspace/laughing-octo-fishstick
.venv/bin/python -B VERIFY_SOURCE.py
PATH=/workspace/.local/usr/bin:$PATH xvfb-run -a .venv/bin/python -B tools/RUN_OFFLINE_TESTS.py
git diff --check
```

Actual Tk tests cover exact draft entries, explicit authorization/revocation,
invalid edits, balance-change invalidation and quantity-safe exports. Financial
records and the native full-source ranking are unchanged by draft edits. Retained
broker/FIFO/quantity/recovery, STOP, SDK signing, mixer, reserve and passive-advisor
checks remain required. Export still has all eight sections. No quantities,
account IDs, keys, private paths, observation IDs, authorization fingerprints or
settlement/cashflow references are added to diagnostic exports.

Source-only packaging uses the regenerated manifest and independent ZIP checksum.
Observed full validation: **164 discovered / 164 distinct / 164 run**, with zero
failures, errors, skips or expected failures. This retains the previous 141 cases
and adds 23 deadline, allocation, conversion and actual-GUI cases. Two existing
assertions were updated to require the new deadline-window fields and exact
allocation controls; financial assertions were not weakened. Sixteen protected,
economic, control, admission and transport files match `99e929e` byte for byte;
the reserve class/calculator source segments also remain unchanged.

Private datasets/backups, uploaded reports, credentials, environments and logs
are excluded. Windows/DPAPI, production reconciliation, live scheduling, depth,
fee currency, fills, restart recovery and profit remain unverified. The ETH-profit
selector remains disabled and the production broker's first-statement block stays.
