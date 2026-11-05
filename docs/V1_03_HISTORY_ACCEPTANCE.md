# Archived acceptance evidence before v1.04

These are historical results and boundaries. Current acceptance is in
VERIFICATION.txt and docs/V1_04_RESUMABLE_TRIAL.md.

```text
COINCAT v1.03beta — IMPORTED HISTORY REPORTING FOLLOW-UP
Source base: published 5342a3fb512a87b7ef910b40df95ceaa591b9021.

CONFIRMED REPORTING GAP
The manual workspace retained imported Coinbase orders in its read-only
history store, but supplied only current-session execution counters to its
monitor wrapper. The wrapper left beta.manual at its default UNOBSERVED/zero
projection. The diagnostic history section contained static text, and the
browser replaced its read-only history line with current execution status.
Thus a filled historical order could be absent from both reports even after
a successful read. The zero current-session execution count remains correct
for an order placed externally; imported history needs its own visible count.

REPAIR
Cache read-only history status at startup and after imports/CSV cross-checks;
pass it through the existing strict beta.manual schema. Diagnostics now label
the current CoinCat session and imported history separately. The browser has
a dedicated Imported Coinbase history panel. Filled-order counts do not
depend on settlement certainty. Explicit API native flow and uniquely
CSV-corroborated native flow both count as known arithmetic; imported records
never receive execution credit, paper capital or authority to place orders.
No public schema fields, monetary exports or raw records are added.

EXECUTED FOCUSED CHECKS
Ten isolated manual-window/history checks pass with HTTP/WebSocket forbidden
before discovery: 5.762s on Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0;
6.442s on supplementary Linux Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6.
The full source run discovers/runs 488 distinct tests in 52.136s with zero
failures/errors/skips/expected failures and HTTP/WebSocket forbidden.
The new regression imports one synthetic filled order without fee units,
checks both diagnostic and monitor show imported filled=1 with current
execution=0, re-reads without count inflation, then cross-checks a synthetic
CSV and verifies known-flow=1/unknown=0 while execution stays zero. Original
API fills and unreported fee currencies remain intact. Private IDs, native
prices, proceeds and paths do not enter the exported summaries.

Node DOM checks exercise the actual monitor script/markup: imported filled
orders with unresolved settlement, CSV-known arithmetic without execution
credit, stale-capture labeling, legacy v3 compatibility, missing snapshots and
helper-failure clearing. Full 488-case source and extracted-package results
are retained with external release artifacts. The focused launcher runs ten
checks and explicitly does not replace the full verifier. There remain 158
hashed source files. Restart the updated app and helper, carry over verified
private history, and create fresh exports after completed imports.

BOUNDARIES
Only read-only history counting, cached/public projections, report/monitor
labels and associated verification/release documentation change. Order
submission, fee calculations, balances, limits, financial/FIFO/key/import/
lock modules, datasets and dependencies are not changed. No cloud account
request or real trade is performed. Native Windows rerun and connected
execution acceptance remain local checks.

The following is historical evidence for the previous source candidate.

COINCAT v1.03beta — WINDOWS RESIZE VERIFICATION FOLLOW-UP
Source base: published 2e9fa6959abee08f07dbdb4bec2221cbffcd679b.

OWNER-SUPPLIED WINDOWS RESULT FOR THE PREVIOUS CANDIDATE
157 source hashes matched. Windows Python 3.11.9 / SQLite 3.45.1 /
Tk-Tcl 8.6 discovered and ran 486 tests in 1682.733s. One resize test
reported five subtest failures; there were zero errors and one host-symlink
capability skip. This is FAILED acceptance, not a Windows pass.

CAUSE AND REPRODUCTION
The test requested 1040x780 immediately after 1450x920, but processed only
Tk idle work. Win32 native resize/configure messages require event dispatch.
The reported child right edges still corresponded to the larger layout.
A controlled 50ms native-resize delay on Tk 8.6 reproduces all five failures:
after idle-only processing the actual width is still 1450; child right edges
are 1130/1298/1411/1411/1419 against a requested 1040 boundary. After native
events settle, actual width is 1040 and edges are 720/888/1001/1001/1009.

The fixture now requires the exact requested native width and height and
stable child geometry before applying the same mapped/width/right/bottom
assertions. Failure to reach the requested size fails with actual size and
Tk scaling. No tolerance, minimum size increase, platform skip or fit-assertion
suppression is added. The delayed-configure regression independently checks
the final actual size and all five child bounds.

EXECUTED FOCUSED CHECKS
Nine isolated manual-window checks pass with HTTP/WebSocket forbidden before
discovery: 4.761s on Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0;
5.533s on supplementary Linux Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6.
The complete source run discovers and runs 487 distinct tests in 47.600s,
zero failures/errors/skips/expected failures, with HTTP/WebSocket forbidden.
An additional resize probe checks 1450x920 and 1040x780 at Tk scaling
1.333333, 1.666667 and 2.0; all tested right/bottom bounds fit after native
event dispatch. These are Linux probes, not native Windows acceptance.

QUICK WINDOWS RECHECK
After setup, tools/VERIFY_MANUAL_WINDOW.bat verifies all 158 source hashes
and runs only these nine checks in disposable state. It explicitly labels
its result FOCUSED, not full acceptance. 03_VERIFY_COINCAT.bat still runs
the entire 487-case isolated suite. Full checkout and fresh source-ZIP
extraction results are retained with the external release artifacts.

BOUNDARIES
All 85 tracked application/artwork/dependency files retain the previous
candidate's bytes. Only the verification fixture/runner, quick-check
launcher, release documentation and source manifest/package metadata change.
No fees, spending caps, live gates, trading, key/financial code, diagnostics,
monitor, private records or account state are changed by this follow-up.
No real exchange request or PC installation is performed here. A new native
Windows run is required; connected order acceptance remains unverified.

The following is historical evidence for the previous source candidate.

COINCAT v1.03beta — MANUAL SPOT SOURCE CANDIDATE
Base: published e5966cdad17208fa9b5bce758c3a3820599f9175.

FINAL SOURCE CHECKS
486 discovered/distinct/run, zero failures/errors/skips/expected failures in
49.346s on Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0. HTTP/WebSocket
forbidden before discovery and throughout execution. This retains all 451
previous cases and adds 35 manual lifecycle/native evidence/Tk cases. A few
subsequent display-only label/input refinements are also covered by the final
freshly extracted package run, recorded with the external release artifacts.

Coverage: fourteen native directions, manual marketable LIMIT BUY at ASK,
Post Only crossing rejection, exact native rules, funds/fee buffer/caps,
no research/forecast admission prerequisites, finite preview, exactly-once
dispatch, unknown POST recovery, cancel/fill races, partial remaining drafts,
restart/expiry/session archive, STOP/shutdown, CSV corroboration/ambiguity,
strict public fields, actual Tk controls and minimum-window layout. Source
boundary verifier checks both the retained automatic maker adapter and the
new default-ON manual LIMIT/explicit-click/ambiguous-create boundaries.

Supplementary Linux Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6 exercised the
35-case manual/UI suite in 5.162s with zero failures/errors/skips. The package
results are retained outside the checkout. Actual Tk 8.6 screenshots were
inspected at 1450x920 and 1040x780 using clearly labeled synthetic data.

LOCAL MONITOR
Actual localhost protocol: unauthorized GET 401, authorized GET status 200,
POST 405, /stop 404. Node DOM checks passed for the current manual provider,
hidden legacy panels, stale-gate clearing, old-v3 compatibility, missing data
and missing helper response. The extension accepts controlled enums/counts
only; amounts, settings, IDs, keys, private paths and raw errors are rejected.
No helper command or trading channel exists.

PRIVATE STATEMENT READ
The supplied small ETH-BTC sale's native arithmetic was read locally:
.005 * .030268 = .000151340 BTC gross; implied deduction .0000007567 BTC
(0.5%); net .0001505833 BTC. USD fee arithmetic is consistent. This does not
claim a live API read, an order-ID join or account reconciliation. The CSV's
private IDs/path/contents are excluded from the repository and package.

BOUNDARIES
Financial/FIFO/tax, key/DPAPI, import, lock, canonical receipt libraries,
dependency locks and original artwork remain byte-identical to the baseline.
The default manual client does not initialize the older automatic controllers
or open the financial ledger. Its identity journal is separate. No cloud
Coinbase order, transfer, account connection or PC installation was performed.
No Coinbase credentials or network access are configured here. Native Windows,
current connected preview/create/fill/cancel behavior, DPAPI and actual account
settlement still require the explicit local sequence in START_HERE.md.
Offline tests do not prove profitable predictions or connected readiness.

The following is retained historical evidence for earlier candidates.

COINCAT v1.03beta — WINDOWS VERIFICATION HANDLE REPAIR
Parent: published 5bb62739df56ae933e90770e75ca324f929b47f7.

OWNER-SUPPLIED NATIVE RESULT FOR THE PARENT
Windows Python 3.11.9 / SQLite 3.45.1 / Tk-Tcl 8.6. All 150 source hashes
matched; 450 discovered/distinct/run, 1613.266s, zero assertion failures,
one error and one host-symlink skip. The error was WinError 32 removing a
synthetic unrelated.sqlite3 at test teardown, not an exchange call or an
application trading assertion. That run is FAILED, not an acceptance pass.

REPAIR
SQLite's connection context manager commits/rolls back but does not close.
The fixture now explicitly closes before cleanup. Strong-reference resource
probes assert closure on success, foreign-store rejection and duplicate/conflict
returns. A corrupt-header rejection test also asserts file preservation and
handle closure; the beta store now closes on a failed initial identity query.
No skipped error, forced garbage collection or cleanup exception suppression.
Only this isolated storage error path, tests and release evidence change;
trading decisions, gates, fees, limits, UI, protected financial code, logo and
locked dependencies retain the parent's bytes.

EXECUTED REPAIR CHECKS
451 discovered/distinct/run, zero failures/errors/skips/expected failures in
45.525s, Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0. HTTP/WebSocket
forbidden before discovery and throughout execution. Fifteen focused live/store
tests pass in 0.194s, and pass on supplementary Python 3.13.5 / SQLite 3.46.1
in 0.240s. The corrupt-header regression deliberately detects the prior store's
unclosed handle and passes with the correction, without relying on GC.

The corrected source requires a new native Windows run. Exact package
extraction results are delivered with the corrected ZIP.
The following release ledger is historical evidence for the parent unless
explicitly superseded above; it is not a native pass for this repair.

COINCAT v1.03beta — BOUNDED REAL MAKER SOURCE CANDIDATE
Base: published v1.02 a09a1f3eab106f8d775e2ba76e80e29743292bd4.
Branch: coincat-v1.03beta. Earlier v1.02/v1.01/v100 remain preserved.

PERSONALLY EXECUTED CHECKS — NOVEMBER 4, 2026
Full offline source run: 450 discovered / 450 distinct / 450 run, zero failures,
errors, skips or expected failures in 45.207s. HTTP and WebSocket forbidden
before discovery and during execution. Python 3.11.17 / SQLite 3.53.1 /
Tk-Tcl 9.0 / Linux Xvfb. Canonical financial/native/frozen-session/UTF-8 tests
remain, with intentional current-version/default-live-gate assertions updated.
Forty-five new beta cases cover both maker dispatch directions, fee/native
math, shared caps, explicit UNKNOWN entry, no POST retry, partial/cancel races,
restarts, fee corrections (including terminal review), view-only/cursor imports,
L2 absolute sequencing/invalidations/grouping, privacy and actual Tk bindings.

Supplementary Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6: 56 core/GUI tests pass,
zero failures/errors/skips, 7.228s. This uses the same pure dependency directory;
it is a Tk diagnostic, not native Windows or supported-runtime acceptance.
A subsequent compact-row adjustment was checked with five actual Tk 8.6 GUI
cases (2.334s) and synthetic captures at 1380x900 and 1040x780: healthy book bid
and ask panes fit, with scroll access to extended details and true-alpha header.
No native background ThemeChanged error was suppressed. The final exact package
is independently extracted/rechecked; its full-suite log/checksum is delivered
beside the ZIP rather than represented as Windows/connected proof.

Actual localhost monitor: GET / and /monitor.js 200; unauthenticated status 401;
authenticated status 200; POST 405; /stop 404. Node DOM harness verifies current
bounded-live status, stale-current-gate clearing, absent snapshot and helper
failure clearing for paper/manual/book/live. Strict projections reject unknown
nested keys and export no quantities, settings, IDs, raw errors or private paths.

Finite --synthetic replay passes: two terminal paper orders, four simulated
fills, exactly two fictitious SOL, zero real orders/verified exchange fills.
Touch alone cannot fill. The legacy holdout remains an uncalibrated synthetic
stress exercise; no predictive or real profitability inference is made.
The supplied owner statement's native-note calculation was read locally and
matches .000151340 BTC gross / .0001505833 received / .0000007567 implied
historical deduction / .5%; USD arithmetic agrees. This is not authenticated
commission-currency, account reconciliation or an identifier join. No private
statement/IDs/financial records are packaged or committed.

All 59 other preexisting app files remain byte-identical to a09a1f3; only eight
preexisting app files (UI/version/diagnostics/monitor/broker) are changed.
The LiveLedger class remains byte-identical, SHA256:
15a496420f75ae64c28bad69fecf78816f19cc3c397d1a46f4c556d994d43f26
Financial/FIFO/state/import/key/lot/lock/native/global/transport libraries,
requirements/lock, logo/icon and old datasets are preserved. The explicitly
authorized broker edit removes unreachable market submission and adds only
the bounded Post Only adapter. No legacy financial schema/basis/lot mutation
was introduced. Source cache cleanup removed three .pyc files; no financial,
research/session/import/key/backup/lock deletion. Twelve installed dependency
versions match the unchanged lock; uv --offline pip check passes.

Live block starts ON. Deliberate OFF + applied limits + explicit Start can
send actual maker orders. Old positional broker calls remain blocked, and
missing critical data means HOLD. Proposed unapplied initial caps: .005 ETH,
$5/order, one open, four attempts, 30min, fee ceiling 2%. New live/manual stores
are isolated native-flow/observation journals, not tax records or paper funds.
STOP/reblock cancels only owned resting identities and reconciles racing fills;
acknowledgment is not terminal. Closing can retain unresolved locks. Restart
never resumes/reseeds. These behaviors are synthetic test evidence, not a
connected guarantee. The source guard checker validates the new default-ON /
maker-only boundary; it no longer falsely asserts a permanent global block.

NOT RUN / NOT CLAIMED
Native Windows setup/DPAPI/single-instance/DPI/reconnect soak; current Coinbase
server sequencing/fee-denomination contract; actual saved-key manual order
reproduction; real partial/cancel/timeout/balance reconciliation; prospective
frozen-plan strategy evidence; independent operational/financial review.
Coinbase hosts are unavailable and no Coinbase credentials are configured in
this cloud environment. No cloud Coinbase create/edit/cancel/preview/transfer
request, account allocation change or actual trade was made. Normal fee metadata
may omit explicit denominations, so even enabled REAL mode may HOLD/UNKNOWN.
No demonstrated edge, guaranteed profit or beta readiness signoff is claimed.
See START_HERE.md, docs/BETA_1_03.md and docs/BETA_1_03_ACCEPTANCE.md.

Source-only package uses regenerated SHA256_MANIFEST.json and independent ZIP
checksum; excludes private data/backups, keys, uploads/CSV, logs, monitor/token
files, virtual environments and bytecode. Final extracted checks are delivered
separately. GitHub Actions/Windows/independent results are not inferred from
local source tests. Prior verification entries below apply only to their named
historical versions; their permanent-live-block text is superseded above.

COINCAT v1.02 — GLOBAL PAPER SETTINGS SOURCE CANDIDATE
Base: published bba4dfea67b45e6f4eff7f15b7ba4398ab486a08, separate coincat-v1.02.
Previous coincat-v1.01 and coincat-v100 branches/installations are preserved.

PERSONALLY EXECUTED CHECKS — NOVEMBER 3, 2026
405 discovered / 405 distinct / 405 run, zero failures/errors/skips/expected
failures in 42.386s. HTTP forbidden before discovery and throughout execution.
Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0 / Xvfb; same twelve locked
dependencies. Thirty-one new global cases cover the working slice once, source
caps, all-view floor, fees once, UNKNOWN startup, native minimum/precision,
fresh approved USD separation, transactional latest-version/cap/fee rechecks,
immutable history/proof, canceled partial returns below target, permanently
UNKNOWN completion FX, original-version reporting, safe resting review, STOP,
reservation locks, restart, redaction, legacy projection and new UI defaults.
The full suite retains canonical financial/native assertions and legacy tests.

Supplementary Linux Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6: 67 core/actual
GUI/restart tests pass, zero failures/errors/skips in 13.846s. This uses the same
pure dependency directory for a Tk diagnostic, not supported-runtime or Windows
acceptance. Native idle ThemeChanged/background errors are collected rather
than filtered. Final extracted-source full-suite validation is delivered in
its separate log beside the source ZIP; no native pass is inferred from it.

Actual supplementary Tk 8.6 captures/checks at 1380x900 and 1040x780: new normal
Start uses the working 50% slice once, BBO/UNKNOWN creates zero orders; a separate
explicit synthetic depth/fee-unit/funding fixture exercises a qualified maker
order; all fourteen views, native bid/ask, scrollable order/wallet/outcome detail,
Trading Settings, archived chart and transparent header fit. The small-window
check first exposed clipped book panes; compact controls/scrolling and shared
bid/ask heading fix that. The original financial fixture remains unchanged.
No connected depth/fee evidence or native Windows/DPI result is claimed.

Actual Tk restart plus authenticated loopback monitor v3 acceptance passes:
original wallet/order and global revision restore as RECONCILIATION_REQUIRED,
without saved-opt-in resume. Eight-section diagnostics and cached heartbeat
omit native amounts, targets, percentages, references, receipts, private paths,
IDs and token. No paper SQLite polling during heartbeat/export. Real GET 200,
missing-token 401, private-path 404 and POST 405 checks pass. STOP/final CLOSED
snapshot, writer/server/GUI shutdown and unchanged financial fixture pass.
Only explicit localhost HTTP was used; exchange HTTP stayed forbidden. Node
syntax/DOM checks pass global policy/version/counts, missing/failed responses
and clearing stale information. The helper offers no command/update channel.

Declared offline replay passes: two terminal paper orders, four simulated fills,
zero real orders/verified exchange fills, exactly two fictitious SOL retained
through expiry, duplicate ignored and restart reconciliation leaves PAUSED.
These are toy inputs, not global-floor performance or predictive evidence.
The historical holdout tool still identifies its patient/short-lived policy;
it is not a global USD-gate forward trial. NO DEMONSTRATED EDGE in all cases.

17 protected broker/FIFO/state/import/key/lot/lock/native/transport/allocation/
cycle modules are byte-identical to bba4dfe. Original transparent logo/icon and
both dependency files are unchanged. LiveBroker.submit retains first-statement
unconditional LiveBlocked. No real financial schema/record/lot/basis changes,
account create/edit/cancel/preview/transfer calls, permissions or allocations.
132 manifest source files plus SHA256_MANIFEST.json are packaged. Source-only
ZIP/independent SHA256 and independently extracted hashes/full-suite/replay
logs are delivered separately. Private records/backups, keys, uploads, monitor
files/tokens, logs, environments and bytecode are excluded. git diff --check
passes. These are personally run checks; no GitHub Actions result is asserted.

LIMITS / WINDOWS GATE
Current normal scanner has BBO, without required sized exits/verified fee units.
Strict UNKNOWN therefore blocks initial and later global entries. Fresh ETH-USD
is a reference only, never a trade/bridge/history product, and does not fill the
missing inputs. Conditional admission/target estimates are not completed profit.
Terminal partial ETH returns can finish below the minimum; they and remaining
exposure stay recorded. Missing/late completion FX stays UNKNOWN permanently.
Versioned Apply cannot rewrite orders, raise size, relax protection or liquidate
losses. AI Lab is passive. Subscription costs remain separate/unmodeled.

Native Windows Python 3.11, DPAPI, single-instance, DPI, connected product/fee/
reference availability and 60–120-minute supervised read-only acceptance remain
UNRUN for v1.02. Earlier owner-supplied native results belong to old builds.
Follow START_HERE.md and docs/GLOBAL_PAPER_V1_02.md in a separate installation;
full Windows verification may take 20+ minutes, inspect final COUNTS/errors.
No installed-PC change, deployment, connected account mutation or live pilot.
Actual profit NOT_ESTABLISHED; live execution remains unconditionally blocked.

THE FOLLOWING LEDGERS ARE HISTORICAL CHECKPOINT EVIDENCE

COINCAT v1.01 — OPTIONAL SHORT-LIVED PAPER POLICY CANDIDATE
Base 5abbce56066f295708f73013a3d73602b8c91ab6, remote fetched/matched.
The owner requested brief validity/fresh market decisions while pursuing ETH
accumulation. SHORT_LIVED_ETH_V1 is selected explicitly for a new paper session;
PATIENT_MAKER_ETH_V1 remains the default and old sessions keep their exact frozen
serialization, funds and deadlines. No assumed loss-exit rule, live order,
account/financial change, new dependency or extra market polling.

Current supported checkout: 374 discovered / 374 distinct / 374 run, zero
failures/errors/skips/expected failures in 39.336s. Linux Python 3.11.17 /
SQLite 3.53.1 / Tk-Tcl 9.0 / Xvfb; HTTP forbidden before discovery and throughout
execution. Includes twenty-one additional checks: short lifetime, all fourteen
native sides, partial/final-fill cancel races, confirmed cancellation plus fresh
replacement, remaining source/campaign limits, minimum rest/hysteresis, original
deadlines, slot exhaustion, STOP/restart, old-session restoration, frozen params,
GUI opt-in/current scanner path and quantity-free monitor policy enum.

Supplementary Linux Python 3.13.5 / SQLite 3.46.1 / Tk-Tcl 8.6: 42 short-policy,
paper/journal GUI and restart checks pass, zero failures/errors/skips, 7.736s.
This is supplementary Tk evidence, not supported Python 3.11 or native Windows.
Actual synthetic Tk captures show an expressly declared seed receipt, a fresh
maker ETH return, cancellation after target invalidation and HOLD with visible
underwater inventory. All seven products/fourteen views, the large transparent
logo and scrollable settings fit 1380x900 and 1040x780; financial fixture bytes
remain unchanged. Final extracted-source validation is delivered beside the ZIP.

The policy's default child lifetime is 120s, review/minimum rest 30s, movement
threshold the greater of 10 bps or two native ticks. A replacement is another
order slot under the same original campaign/session deadline and remaining
approved source, not another ETH allocation. Cancellation/fill uncertainty
retains reservations. A fresh current maker receipt must meet the allocated
simulated net ETH target; otherwise HOLD. Sixteen two-minute attempts total 32
minutes of resting time, plus cancellation/review delays. Price-move replacement
can consume slots sooner. No hard
limit, fee evidence, queue model or profit threshold was relaxed to create fills.

All 24 unchanged chronological synthetic scenarios/models/seeds under the new
policy produced zero fills: one shared 1 ETH wallet per run, zero fees, sixteen
unfilled orders, observed midpoint delta/drawdown zero, no model-review errors,
and PAPER_ORDER_BUDGET_EXHAUSTED_HOLD_INVENTORY. All kept NO DEMONSTRATED EDGE /
actual profit NOT ESTABLISHED. Cash remains 1 ETH at the fixed horizon; no
successful trading cycle or predictive improvement is inferred from idle cash.
The assumptions are uncalibrated BBO stress scenarios, not exchange matching.
Actual fee-unit/depth/residue uncertainty still keeps non-cash recoverability
UNKNOWN. The earlier patient holdout includes marked losses and is retained;
model prices/parameters were not changed to make the short variant execute.

17 protected broker/FIFO/state/import/key/lot/lock/native receipt/transport/
allocation/cycle modules, original logo/icon and locked dependency files match
5abbce5 byte for byte. LiveBroker.submit keeps unconditional first-statement
LiveBlocked. The regenerated manifest covers 129 source files, plus the manifest
itself. Independent source ZIP SHA256, extracted-suite/replay results, detailed
logs, current GUI captures and handoff are delivered outside the source ZIP.

OWNER-SUPPLIED WINDOWS RESULT FOR PRECEDING 5abbce5
Python 3.11.9 / SQLite 3.45.1 / Tk-Tcl 8.6. All 129 hashes passed; 353 distinct/run
in 1332.850s (22m13s), zero failures/errors and one host-symlink capability skip.
No ThemeChanged cleanup warning appears. This confirms the prior fixture repair
on that PC, not this new policy's native/connected acceptance. The slowest test
was the four-run synthetic holdout, 474.703s. Native Windows re-verification and
the supervised 60–120-minute paper/connected-product/fee/DPAPI/DPI trial remain
separate gates. Real order submission remains blocked; no deployment is implied.

THE FOLLOWING LEDGERS DESCRIBE PRECEDING PUBLISHED CHECKPOINTS

COINCAT v1.01 — WINDOWS VERIFICATION REPAIR
Parent: published cf0b43f6e9b4d7bb7c34667a796954a93153df78, fetched/matched.
This repairs the owner's native verification failure and quiet progress output
within the already requested v1.01 build. No application/trading change.

OWNER-SUPPLIED NATIVE WINDOWS RESULT FOR PARENT cf0b43f
Python 3.11.9 / SQLite 3.45.1 / Tk-Tcl 8.6; all 129 source hashes pass.
351 distinct/run in 1278.366s (21m18s), zero assertion failures, two errors,
one host-symlink capability skip. Both errors were NotADirectoryError/WinError
267: new test fixtures used dictionary text containing Windows-invalid colons
as directory names. This was a completed FAILED run, not an indefinite hang.
The affected test branches had not reached their financial/eligibility asserts.

REPAIR AND PERSONALLY EXECUTED CHECKS
Use numbered portable fixture names; validate every auto-paper case folder on
all platforms. No financial/fee/funding/product assertion was removed or relaxed.
Four focused checks pass on Linux Python 3.11.17 and supplementary Python 3.13.5:
the two affected cases plus heartbeat lifetime and unchanged subtest-error/failure
accounting. All actual app modules, logo/icon and dependency files are byte-
identical to cf0b43f. The unconditional live order guard remains unchanged.

Current checkout: 353 discovered / 353 distinct / 353 run, zero failures/errors/
skips/expected failures, 38.333s. Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl
9.0 / Xvfb. HTTP forbidden before discovery and throughout execution. A real
30-second heartbeat appeared during that run. The slowest test was the four-run
synthetic holdout at 12.911s here; its Windows runtime has not been measured
individually. No speed improvement or native pass is inferred from Linux.

03_VERIFY_COINCAT.bat now labels hash/syntax/test phases and uses unbuffered
output. Tests show their number/name and per-test/total elapsed time. A separate
console-only worker emits liveness every 30s through discovery, long tests and
temporary-data cleanup, then joins cleanly. The final COUNTS and five slowest
tests remain visible. Heartbeats do not declare success or impose a timeout;
Windows tests can still take 20 minutes or more. Failures retain nonzero exit.

Regenerated manifest still covers 129 source files. The repaired source-only ZIP
and independent checksum/extracted-suite evidence are delivered separately from
the original cf0b43f package. No private/monitor/credential/log/environment files
belong in the source ZIP. Native Windows rerun remains REQUIRED: source hashes
alone do not establish acceptance. The symlink capability skip is distinct from
these two errors and has not been hidden. Real trading remains blocked.

THE FOLLOWING LEDGERS DESCRIBE THE PRECEDING PUBLISHED CHECKPOINTS

COINCAT v1.01 — AUTOMATED MAKER-ONLY PAPER SOURCE CANDIDATE (cf0b43f)
Base: published coincat-v100 ebe4fd7405dc7a827503b090ef60af348c45d838,
fetched and matched before implementation. The owner's later "please push as
v1.01 when complete" authorizes source commit/push on coincat-v1.01 after checks.
No installation on the running PC, deployment, account change or live trading.

PERSONALLY EXECUTED CURRENT CHECKS — NOVEMBER 3, 2026
Checkout: 351 discovered / 351 distinct / 351 run; zero failures, errors, skips
or expected failures in 42.475s. HTTP forbidden before discovery and throughout
execution. Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0 / Xvfb; same 12
hash-locked dependencies. Retained financial/native assertions pass. New cases
cover all fourteen actual product/side mappings, four once-only kickoff choices,
shared caps/reservations, fee/tick/minimum gates, partial/unknown/cancel races,
dispatch/restart/corruption/bounds, fixed-horizon/no-lookahead evaluation, frozen
model/policy, monitor redaction, generation rejection and clean worker shutdown.

Supplementary Linux Python 3.13.5 / Tk-Tcl 8.6: 21 actual paper/journal GUI and
restart tests passed in 6.395s, zero failures/errors/skips. This borrowed the
same dependency directory for a Tk diagnostic; it is not the supported Python
3.11 acceptance run. Every test interpreter collects Python/Tcl background
errors; native pending ThemeChanged idle work is exercised before destruction.
No theme warning was hidden or filtered. The owner's previous native Windows
v100 run was 307 tests / zero failures/errors / one synthetic-symlink skip,
487.932s, with a Tcl ThemeChanged cleanup warning. That run is historical and
does not establish native v1.01 acceptance or the Windows cleanup repair.

Actual supplementary Tk 8.6 GUI captures at 1380x900 and 1040x780 show explicit
Start from the normal scan, one shared wallet, modeled partials then a patient
ETH return, seven product tabs/fourteen reachable directions and scrollable
small-window details. The larger upper-header transparent logo/icon bytes are
unchanged. Existing mixer, chart/hover, allocation, journal and notes checks
remain in the full suite. Synthetic financial fixtures remained unchanged.

Separate actual Tk restart and authenticated localhost monitor acceptance:
the original wallet/order restores before a scan as RECONCILIATION_REQUIRED,
without saved-opt-in resumption. Eight diagnostics themes and monitor v3 expose
only safe aggregate paper fields, with no heartbeat paper-SQLite polling.
GET 200 / missing-token 401 / private-path 404 / POST 405, private-field/token
omission, STOP/final CLOSED snapshot and clean GUI/writer/server shutdown pass.
Only explicit loopback HTTP was used in that separate check; exchange HTTP was
forbidden. Node JavaScript syntax/DOM checks pass current, missing and failed
responses, including clearing stale paper/journal/research information.

17 protected broker/FIFO/state/import/key/lot/lock/native-receipt/transport/
allocation/cycle files are byte-identical to ebe4fd7. Requirements/lock and
original logo/icon are unchanged. LiveBroker.submit retains its unconditional
first-statement LiveBlocked. Source-only hashes/syntax cover 129 files;
SHA256_MANIFEST.json is additional. Independent ZIP SHA256, extracted-source
verification/full-suite results and logs are delivered beside the source ZIP.
No private data/backups, keys, monitor files/tokens, uploads, logs, environments
or bytecode belong in that package. No independent GitHub Actions claim is made.

SYNTHETIC HOLDOUT — SOFTWARE/EVALUATION EVIDENCE ONLY
24 predeclared runs: two fictitious chronological scenarios x four fixed models
x seeds 1/7/19. Each uses one 1 ETH wallet, an excluded 20-observation development
prefix and 222 holdout observations at 30-second intervals. The original horizon
and its first valid observation are immutable; later cleanup is not scored.
Partial executions are counted even when an order later completes. Completion
times, fees, unfilled/open orders, observed peak-to-trough drawdown, underwater
time and unknown after-cost recoverability are retained for every run.

All six NO_FILL runs retain exactly 1 ETH and charge no execution fees. Across
the remaining eighteen, midpoint deltas range from approximately -0.02720071 to
+0.04492348 ETH; these include open marked losses and are not executable profit.
All eighteen remain UNKNOWN for credible after-cost recoverability, due to
missing sized exits, verified exchange fee units and residual valuation. All
24 retain NO DEMONSTRATED EDGE / actual profit NOT ESTABLISHED and no model-
review error. Exact-decimal logs and the all-seed result table are delivered.
The model's queue sizes/gates are explicit uncalibrated BBO stress assumptions,
not observed queue/depth or calibrated maker fill probabilities. Touching a
quote never fills. No extra market GET or quote budget was introduced.

The retained offline declared-event replay still expects 2 terminal orders,
4 simulated fills, 0 real orders and 0 verified exchange fills, leaving exactly
2 fictitious SOL under its explicitly chosen toy inputs. It demonstrates the
lifecycle only. Source paper activity never credits the actual ledger as profit.

WINDOWS/CONNECTED GATES STILL UNRUN FOR v1.01
Run 02_SETUP_COINCAT.bat, 03_VERIFY_COINCAT.bat and tools\RUN_PAPER_REPLAY.bat in
a separate installation/data copy, then docs/AUTO_PAPER_V1_01.md's supervised
Start/Pause/STOP/restart/monitor trial for 60–120 minutes before longer runs.
Native Windows Python 3.11, DPAPI, single-instance, DPI, connected product/fee
availability and outages need that PC's evidence. The source candidate is not
installation-ready or a validated predictive/exchange execution system. Basic
membership changes no fee evidence; actual pair fee units remain unverified.
Real order submission stays blocked. No live pilot is authorized by these checks.

COMMANDS
  python -B VERIFY_SOURCE.py
  python -B tools/RUN_OFFLINE_TESTS.py
  python -B tools/PAPER_LIFECYCLE_REPLAY.py --synthetic
  python -B tools/AUTO_PAPER_HOLDOUT.py --synthetic
  python -B verification/run_verification.py
  python -B tools/BUILD_SOURCE_PACKAGE.py --zip <outside-checkout-path>
  git diff --check
Defaults, architecture, user steps and objections: docs/AUTO_PAPER_V1_01.md and
docs/AUTO_PAPER_FEEDBACK.md. Subsequent ledgers describe historical checkpoints.

THE FOLLOWING LEDGERS DESCRIBE PRECEDING PUBLISHED CHECKPOINTS

PAPER LIFECYCLE PREVIEW — SOURCE COMMIT/PUSH AUTHORIZED
Base: published journal commit 5e951db52c31f07f4b66c1f31b81829caed64300.
Owner selected implementation using explicit simulation/replay events on Nov 3,
then explicitly authorized this follow-up's source commit/push.
No connected execution, real allocation, financial data/schema/lot/basis change,
running-PC installation or deployment is included.

PERSONALLY EXECUTED CURRENT CHECKS
307 discovered / 307 distinct / 307 run, zero failures/errors/skips/expected
failures in the checkout (22.492s). HTTP forbidden before discovery and throughout
execution. Includes 31 paper lifecycle cases and 25 persistent-journal cases,
real Tk controls/STOP/mixer/hover/logo/export/monitor checks and all retained
financial/native receipt assertions. First focused startup regressions reproduced
the stale Journal empty label; the repair passed. The new focused journal/paper
run passed 55 tests before one additional bounds case passed in the full suite.

Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0 / Linux Xvfb. Same 12 hash-locked
dependencies; no new runtime dependency or exchange traffic. 121 source files
are listed in the regenerated manifest; all Python syntax and hashes pass.
The 17 protected/canonical/transport/lock/allocation/cycle modules are byte-
identical to published 5e951db. git diff --check passes. The source ZIP checksum
and independently extracted full-suite results are delivered beside the ZIP.

Separate actual Tk restart + authenticated loopback monitor v3 acceptance:
saved case and aggregate restored before first scan, unchanged financial fixture,
eight-section redacted export, no heartbeat/export SQLite polling, real GET,
401/404/405 guards, token/signal omission, STOP, final CLOSED snapshot and clean
writer/GUI shutdown. Exchange HTTP was forbidden; only explicit localhost HTTP
was used for this separate integration check. Node syntax/DOM checks cover the
startup journal count, missing snapshot and failed-response clearing.

The offline replay automatically advances expressly chosen ETH->BTC->SOL steps
from declared toy partial fills. A final fill wins a cancel race; duplicate fill
delivery is ignored. Two terminal orders/four simulated fills leave exactly
2 fictitious SOL from the declared 1 ETH and 1% toy-fee inputs. These are test
inputs, not defaults or performance evidence. No quote-derived fills occur.
Session expiry retains SOL; restart requires exact explicit reconciliation and
leaves PAUSED. Unknown fees/fill history/placement outcomes block new spending;
partial source and proceeds remain reserved. Dispatch grants cannot be repeated.

LIMITS
The normal scanner remains read-only; it does not start this engine or place
paper orders. No connected paper venue/event provider or validated predictor is
included. Missing sized exit/fee units keeps recoverable ETH UNKNOWN. Actual
profit NOT ESTABLISHED / NO DEMONSTRATED EDGE / no verified exchange fills.
LiveBroker.submit still raises LiveBlocked as its unconditional first statement.
No native Windows/DPAPI/connected account validation was run for this candidate.
The owner's earlier Windows 251-test result and later screenshots/diagnostics
belong to preceding builds; they do not establish this source candidate's native
acceptance. No independent GitHub Actions confirmation is claimed.

COMMANDS
  python -B VERIFY_SOURCE.py
  python -B tools/RUN_OFFLINE_TESTS.py
  python -B tools/PAPER_LIFECYCLE_REPLAY.py --synthetic
  python -B verification/run_verification.py
  python -B tools/BUILD_SOURCE_PACKAGE.py --zip <outside-checkout-path>
  git diff --check
Windows steps and discussion handoff: docs/PAPER_LIFECYCLE.md.

THE FOLLOWING LEDGERS DESCRIBE PRECEDING PUBLISHED CHECKPOINTS

PROSPECTIVE-JOURNAL PREVIEW — SOURCE COMMIT/PUSH AUTHORIZED
Base: published v100.0 1e0d88e0161c98f3f1328eeb9a40ebffe9826467.
The owner recommended persistent explicitly registered experiments before any
predictor validation or automated paper execution. This candidate implements
that local research increment, with no installed-PC or private-account changes.

Focused journal checks: 21 passed, HTTP forbidden before discovery/execution.
Includes immutable registration/restart, Decimal/frame round trips, adverse and
missed horizons, no-fill/partial/unknown outcomes, explicit gap/truncation records,
STOP rollback, storage/case bounds, duplicate/backdated rejection, refusal of an
unrelated database, manual Tk controls/local view and existing-scan integration.
Verified data copy retains the journal and preserves financial database bytes.

Candidate final checkout: 272 discovered/distinct/run, zero failures/errors/
skips/expected failures. All 116 source hashes and Python syntax pass. The 17
protected/canonical/transport/lock/allocation/cycle files match published v100.0
byte for byte; git diff --check passes. Final independently extracted-source
results are delivered beside the separate candidate ZIP.
Runtime: Linux Python 3.11.17 / SQLite 3.53.1 / Tk-Tcl 9.0 / Xvfb; same 12
hash-locked dependencies. No new dependency or exchange traffic.

Separate actual Tk + authenticated loopback monitor v3 acceptance passes:
registered-case count, strict redaction (no signal ID/size/token), eight sections,
401/404/405 guards, STOP/final CLOSED snapshot and writer shutdown. Node JS
syntax/DOM fixtures cover current/missing/failed responses and stale clearing.
116 source files are included in the candidate manifest. Existing protected
broker/FIFO/state/importer/key/lot/lock/native receipts/transport stay unchanged.
Original quote, fee, budget, generation and backoff limits are retained.

The owner's supplied Windows result belongs to PUBLISHED v100.0: 112 hashes,
251 tests run / 250 passed / one synthetic-symlink capability skip, no failures
or errors. Its diagnostic snapshot shows roughly 2h10 of retained setups without
reported interruptions. Neither establishes this new candidate's native Windows,
STOP/outage, connected-cost, predictive-edge or real-fill acceptance.
These are local personally executed checks; no GitHub Actions confirmation is
claimed. Current BBO/fee-tier evidence leaves after-cost outcomes UNKNOWN.
NO DEMONSTRATED EDGE / no predictor / no automatic case creation or paper trades.
LiveBroker.submit still unconditionally raises LiveBlocked as its first statement.

THE FOLLOWING LEDGER BELONGS TO THE PRECEDING PUBLISHED v100.0 CHECKPOINT

CoinCat v100.0 — Adaptive ETH Research verification

BASE AND AUTHORIZATION
Base: freshly fetched remote coincat-v95 40bdac5df0c29a9571acc5fe118dd4d8190bf54a.
Local source was clean; its 111 hashes passed before patching. Prior checkout was
an older version, preserved on its existing local branch. Owner explicitly
requested a new clean v100 build, cleanup, commit and push. Environment publication
and deployment to the running Windows installation are separate and not performed.

PERSONALLY RUN BASELINE
229 discovered / 229 distinct / 229 run, zero failures/errors/skips/expected
failures. HTTP forbidden during discovery/execution. Linux Python 3.11.17,
SQLite 3.53.1, Tk/Tcl 9.0 with Xvfb. Twelve dependencies installed with
--require-hashes from the unchanged app_requirements.lock in a disposable venv.
No private records or account credentials were used.

FOCUSED AND INTEGRATION EVIDENCE
31 focused adaptive/GUI/workspace cases pass, HTTP forbidden. Includes actual
Tk, resized larger alpha-transparent header, full mixer/hover and STOP checks.
The first broad run exposed two logo fit/size failures. The PNG handler is now
selected explicitly and the header reserves the required vertical space; the
layout checks then passed without weakening financial/economic assertions.

Separate actual Tk + authenticated loopback HTTP monitor v2 check passed:
eight-section diagnostics, v100 schema/adaptive projection, GET/static reads,
401 missing token, 404 private paths, 405 write methods, no token in status,
STOP and final CLOSED snapshot with deterministic writer/GUI shutdown.
Node syntax and DOM/fetch fixtures pass for current, missing and failed helper
responses; failures clear earlier observations. No exchange HTTP is used.

FINAL CHECKOUT / EXTRACTED SOURCE
251 discovered / 251 distinct / 251 run; zero failures, errors, skips or expected
failures in the checkout (12.515s). 112 manifest files verified. Seventeen
protected/canonical/transport/lock/allocation/cycle files are byte-identical to
the source checkpoint; 49 of 58 original app files are unchanged. All shipped
Python syntax and git diff --check pass. Final source-package/extracted-suite
evidence and independent archive checksum are recorded beside the archive.
The same Python 3.11 runner forbids HTTP before discovery and throughout execution;
actual Tk tests run under DISPLAY=:99. The package includes no private records,
backups, uploads/reports, monitor snapshots/tokens, keys, environments, logs or
bytecode. SHA256_MANIFEST.json identifies current source; ZIP checksum is separate.

COMMANDS
  python -B VERIFY_SOURCE.py
  python -B tools/RUN_OFFLINE_TESTS.py
  python -B tools/ADAPTIVE_ETH_DEMO.py --synthetic
  python -B tools/BUILD_SOURCE_PACKAGE.py --zip <outside-checkout-path>
  git diff --check
Linux validation uses Python 3.11.17 and DISPLAY=:99; Windows setup/verify
launchers invoke the local Python 3.11 environment and need native acceptance.

ACCEPTANCE LIMITS
PASS: offline native arithmetic, bounded scope, fees once, source reservation,
explicit hypothetical events, fixed-horizon/non-event/adverse outcomes,
underwater exposure, quantity-free diagnostics/helper and Linux GUI contracts.
Actual verified fills: zero. Realized earnings: NOT ESTABLISHED. Predictive
improvement: NO DEMONSTRATED EDGE. Missing conservative valuation: UNKNOWN.
NOT VERIFIED: connected catalog/fee/depth/fee-currency evidence, real holdings
reconciliation, native Windows/DPAPI/DPI/single-instance, Tailscale/cloud remote
access, continuous real risk monitoring or profitable fills.
BLOCKED: live submission, order create/edit/cancel/preview/transfer, auto ARM,
real funding/reserve changes and financial schema/record/lot/tax-basis mutation.
No connected private-account run, Windows test, PC installation or environment
publication was performed in this session. Preserve existing data/backups.

```
