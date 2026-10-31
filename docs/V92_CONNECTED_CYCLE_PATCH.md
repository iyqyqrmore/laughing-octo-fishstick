# v92 native ETH cycle dashboard patch

Successor branch: coincat-v92, based on e0c9b35. Development preview; release
identity remains v91.0 and the preserved checkpoint branch is unchanged. No
reconciliation provider, reserves, order execution or fee policy changes.

## Connected observations

The scanner enumerates bounded simple ETH cycles and rotates coordinated groups
through the existing collection planner. Endpoint observations retain priority.
One cycle group may use the remaining allowance within the existing six research
books and sixteen total books. No additional collector, requests, workers or
changed spacing/backoff are introduced. Valuation and USD research use remaining
slots. Cycle observations can compete for capacity, and deferrals remain visible.

Cycle dependencies are refreshed together rather than reused from prior scans.
Only the current collection's returned quotes enter cycle evaluation; missing
products cannot be supplied by the historical cache. Rules, catalog, exclusions,
proposed ETH amount and quote values are detached from subsequent mutations.
One end-of-collection time is used. Thirty-second freshness, 0.25% spread and
12-second span checks still apply. Local receipt-time alignment is not proof
of simultaneous exchange prices, latency-free execution or available depth.

Funding uses only the proposed WORKING ETH amount from the existing allocation
worksheet, never account-wide fallback, protected/manual ETH or other holdings.
The proposal may be unreconciled: it is explicitly research-only, with execution
eligibility always false. Missing funding or fee-tier evidence remains UNKNOWN.
Only final ETH minus the same starting ETH enters cycle ranking. No USD mark is
required; the existing USD scanner and mixer calculations remain separate.

## Dashboard and diagnostics

The new “ETH Cycles — Research Only” tab shows route, legs, modeled net ETH,
quote age/span and blockers, with at most 250 rows in the view. Complete estimates
are ranked first, including negative outcomes. The best negative estimate is
also shown. Unconverted non-ETH residue remains UNKNOWN; product-size failures
are BLOCKED. No smaller order is fitted to obtain a result.

A per-scan opportunity funnel shows discovered (within the bounded enumeration),
observed (all cycle books returned), validated (funding/cost inputs, approved
products and quote quality/span passed), costed (complete residue-free native
result), positive, and execution-evidence count. These are snapshot counts, not
session-unique opportunities or fills. Search truncation is explicit. Sized
depth and independently verified fees are unavailable in this collector, so
execution evidence remains zero; insufficient liquidity is not inferred from
missing depth. Top-of-book gains stay modeled and unverified.

The public cycle projection is included inside IMMEDIATE RESULT, preserving all
eight export sections. It exports routes, status/reason codes, scheduling and
funnel counts; no native amounts, receipts or best-negative ETH quantity. Private
GUI values are not copied into public diagnostics. Export itself makes no calls.

Cancellation is checked during cycle evaluation and before cycle state/cursors,
research service counters, caches or quote recording are committed. Existing GUI
generation checks reject queued pre-STOP results and preserve displayed findings.
Mixer changes do not reprice cycle results against a newer snapshot.

## Validation and use

Run the source verifier and the full offline runner with Python 3.11 and the
hash-locked dependencies. Linux Tk testing requires a real or virtual display.
Native Windows/Tk and read-only connected performance still require local checks.
Use a separate source folder; retain private_data and private_backups and do not
overlay the running v91 installation. Do not run fresh-data setup against existing
records. The source-only archive excludes credentials, data, caches and reports.

Checkout verification: **189 discovered / 189 distinct / 189 run**, zero
failures, errors, skips or expected failures, with HTTP forbidden. Python 3.11.17,
SQLite 3.53.1, Tk/Tcl 9.0, Linux virtual display. All actual Tk tests executed,
resolving the earlier display-only setup errors. The existing three-hour
synthetic admission replay and 16-book maxima remain unchanged. An independent
source archive checksum accompanies the artifact. No positive market opportunity is required
for software acceptance. Prolonged read-only observation is subsequent work;
no live market run, real fill, realized profit or Windows result is claimed here.
