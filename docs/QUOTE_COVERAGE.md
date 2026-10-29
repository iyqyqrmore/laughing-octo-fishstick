# Quote coverage and research deadlines

Read-only follow-up to ETH Farmer commit `6bff164`. The owner requested this
update and a commit after reviewing a v91 diagnostic with only 2 of 844 eligible
directions priced, 833 missing/stale/wide conversion books and many missed
research endpoints. That report is evidence of incomplete observation, not
proof that the whole market offered no positive estimates.

## Scheduling changes

The old discovery selector stopped at three directions even with request space
left. It now selects complete route/mark dependency groups until the unchanged
**16-book collection limit** is full. BUY and SELL directions share product
requests. Quotes at most six seconds old may be reused, allowing room for the
existing six-second collection deadline within the twelve-second frame span.
Reused endpoint quotes must additionally be at or after their horizon.

Structural shortest/lexical USD paths are prepared once per pass without looking
at profitability. A direct listed USD mark is requested before an incidental
indirect cached path. The unchanged canonical planner still chooses consistent
observed marks, performs economic calculations and rejects circular/stale/skewed
frames. No profitable alternative-path search or price-guard relaxation is added.
Fair rotation resumes at the first budget-deferred direction; complete shared
dependencies are deduplicated. Existing exclusions and disabled products apply
to both routes and dependencies.

Due 5/15/60-minute observations receive at most **six** of those sixteen GET
slots, ordered by earliest expiry and deduplicated by their public mark books.
At full budget at least ten slots remain available for discovery. This is a
fixed deadline rule, independent of profit, quantities and advisor text. It
does not select a trade or modify settings. Expired/future observations do not
consume the deadline share. Pending observations and notes remain bounded RAM.

Each proposal freezes source/destination mark paths before its horizon. A future
comparison uses those exact paths, quotes observed no earlier than the horizon,
the existing 30-second age limit, twelve-second synchronization and 120-second
observation window. No favorable replacement path, future extrapolation, extra
entry fee or simulated wallet is introduced. Missing/wide/stale/skewed endpoints
remain unknown while pending, then expire as missed with a cause, never a loss.
ETH re-denomination remains separately unpriced when its reference is unavailable.

The public transport is unchanged: four collection workers, at least 0.2 seconds
between GET starts, a six-second batch deadline, existing unfinished-request
guard and full server Retry-After backoff. One scan performs one collection;
there is no second research request pool or faster retry loop.

## Coverage and UI

The scanner remembers the last public observation per currently listed product
for diagnosis. It supplies only age-valid books to the unchanged pricing path;
the diagnostic cache never makes stale data usable. Conversion-book counts now
separate UNOBSERVED, STALE, WIDE, INVALID, FUTURE and FRESH. Frame/product rejection
counts remain distinct. Both caches are bounded by the current product catalog.

Three counts have different meanings: directions priced **now**, distinct current
eligible directions priced in the **last five minutes**, and those ever priced
in this **session**. Historical counts never supply quotes or justify a current
decision. The UI scopes Best/HOLD to the currently priced subset and leaves all
unpriced directions UNKNOWN. Diagnostics expose request/endpoint allocation,
fetch duration, reuse, quota deferrals, missing mark paths, sample completions
and missed-endpoint causes within the same eight sections. No raw account or
proposal quantities, keys, identifiers, private paths or uploaded reports are
exported. The passive advisor calls attention to incomplete coverage without
recommending faster requests or looser freshness based on coverage counts alone.
Coverage messages are compact and empty mixer error labels take no space;
validation errors remain visible. The minimum 1040x800 layout retains a usable
wallet table with the expanded coverage information.

## Synthetic evidence and limits

The focused tests compare three versus sixteen first-pass directions in the same
simple USD-funded fixture, while retaining the sixteen-GET limit. In a separate
844-direction fixture with eight simulated seconds between scans, the updated
scanner observed all 844 over 62 passes / 488 simulated seconds. Only 64 remained
currently priced at the end. These are controlled synthetic results, not an
exchange benchmark, guarantee of coverage, measured network speed or trading
latency. Shared/missing paths, slow responses, rate limits, manual cadence,
pending research and actual product rules change real results.

Bounded REST collection cannot make hundreds of independent books simultaneously
fresh under these limits. The update improves use of the existing budget and
reports remaining gaps; it does not guarantee complete live coverage or every
research endpoint. A larger transport redesign would need separate scope and
validation. Production broker/FIFO/state/import/key modules, dependency locks,
fees, slippage assumptions, financial schemas and trade authorization are unchanged.
All tests use disposable synthetic state with HTTP forbidden. Windows/DPAPI,
connected account behavior, depth, fee currency, fills, recovery and profit are
not validated by this patch.

From the prepared environment:

```sh
cd /workspace/laughing-octo-fishstick
.venv/bin/python -B VERIFY_SOURCE.py
PATH=/workspace/.local/usr/bin:$PATH xvfb-run -a .venv/bin/python -B tools/RUN_OFFLINE_TESTS.py
git diff --check
```

Observed Linux validation: **120 discovered / 120 distinct / 120 run**, with
0 failures, 0 errors, 0 skips and 0 expected failures. All 101 existing cases
remain; 19 new cases cover request capacity/reuse, exclusions, exact endpoint
timing/paths, quota fairness, missed causes, STOP, coverage history, transport
backoff and actual Tk/export behavior. The focused deadline fixture completes
six due observations in the next pass versus zero when serving only the next
discovery page, using the same sixteen-book limit.

All seven protected financial/key modules still match v91 byte for byte. Twelve
files were additionally compared with the preceding ETH commit, including the
unchanged canonical ranking, receipt, frame, transport and dependency lock.
`git diff --check` and all 93 source-manifest entries pass. A regenerated
94-file source ZIP and independent checksum accompany the update; private data,
backups, credentials, uploaded diagnostics, environments, logs and bytecode are
excluded. The original ETH design evidence describes its earlier 101-test
snapshot, not this follow-up.
