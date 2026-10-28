# CoinCat v70.1 — urgent shadow checks

This source patch implements the first three audit stages (v70.1a–c). Urgent
opportunities take priority over background research. **LIVE order POST remains
unconditionally blocked; this is a shadow/research release.** No private files,
credentials, tax lots, enrollment, or financial database schemas were changed.

## Behavior changes

* Urgent checks are eligible every five seconds, with a one-second recovery gap
  after completion. They run before a due full scan, automatic history catch-up,
  or GPU scheduling when the shared worker is idle. Existing scans and historical
  requests service urgent checkpoints between completed requests. No extra planner
  or parallel SQLite wallet worker was introduced.
* Newest valid quotes win when merging portfolio and research sources. Future,
  nonfinite, crossed, overly wide and expired observations are rejected.
* Bounded quote selection refreshes original HOLD and both current shadow-wallet
  mark dependencies before spending capacity on redundant routes. Fully sold HOLD
  assets remain included. Large mark sets refresh in stages under the same
  16-request cap. Stablecoins need an observed USD path; no peg is invented.
* A failed alternative route does not suppress another complete fresh route.
  Missing required valuation marks do not start a success cooldown. The same
  completed alert has a ten-second cooldown, using a monotonic clock.
* Public quote GETs use pooled connections per worker thread and share a 5/sec
  budget. 429 responses honor Retry-After for later requests without sleeping
  through a scout or automatically retrying a failed operation.
* The urgent collector has a six-second collection deadline. Late results are
  discarded; another batch cannot accumulate while previous GETs remain in flight.
  Individual requests use short connect/read timeouts and reject responses taking
  more than three seconds. Broad scans also preserve request-start timestamps,
  so an urgent interruption cannot make an old response look newly observed.
* Queued shadow proposals are refused if an earlier conversion changed the model
  inventory. Unsynchronized/incomplete full-wallet marks cannot produce a verified
  portfolio comparison or mature outcomes from fabricated zero/missing rates.
* Diagnostics retain the existing 18 sections and add request/planner timing,
  event latency percentiles, typed GET failures, mark coverage and honest quote
  provenance. Missing/invalid marks have distinct reasons; shared reports expose
  counts rather than exact held assets. Quantity parity now verifies wallet/lot
  quantities instead of inferring success from a scenario counter.
* Core Python dependencies are pinned with SHA-256 hashes in
  `app_requirements.lock`. Windows setup installs with `--require-hashes`.
  `02_SETUP_COINCAT_V70_CPU.bat` prepares CPU-only research/verification without
  requiring CUDA. The existing GPU setup remains available; its separate PyTorch
  install is not part of the core dependency lock.

Experimental SHADOW already bypassed historical qualification for explicitly
unvalidated experiments. This patch keeps that behavior; it does not remove the
Validated SHADOW held-out gate, fee evidence, price freshness, product minimums,
available-balance checks, or risk budgets. More trades are not evidence of profit.

## Practical limits

Five seconds is an eligibility interval, not a promised response or trading
cadence. In-progress network calls and synchronous analysis cannot be interrupted
mid-call; checkpoints run when those requests complete. Account reconciliation,
portfolio verification, and safe single-worker serialization remain higher
priority. Requests connect/read timeouts are not absolute wall-clock limits;
the collector bounds waiting and refuses overlapping unfinished batches.

Ticker best bid/ask has no verified exchange quote-event timestamp or executable
depth in this path. Local request-start age is conservative, not exchange age.
Depth-aware sizing, partial-fill execution modeling, a focused level2 research
feed, and connected Windows latency/after-cost forward measurements remain future
work. The existing 15-bps modeled slippage assumption was not removed or presented
as a measured guarantee. Full production settlement/recovery/loss-floor
certification and any live pilot are separate work and remain blocked.

## Verification and Windows use

The patch has deterministic synthetic regressions for quote precedence,
sequential conversions, mark completeness/skew, budget exhaustion, rate-limit
deferral, late responses, priority scheduling, failed-alternative isolation and
stale queued proposals. The final verification count is recorded in
`VERIFICATION_V70_1.txt`. Cloud validation uses Linux Python 3.11 with Xvfb; it
does not establish Windows, DPAPI, CUDA, connected Coinbase behavior or profitability.

1. Close older CoinCat processes. Extract the full source ZIP into a **new**
   `CoinCat_v70_1` source folder, preserving your old source folder.
2. Use `02_SETUP_COINCAT_V70_CPU.bat` for CPU-only research, or the existing
   `02_SETUP_COINCAT_V70.bat` for CUDA setup. Use Python 3.11.
3. Run `03_VERIFY_COINCAT_V70.bat`; require release hashes and the entire offline
   suite to pass before launching `01_START_COINCAT_V70.bat`.
4. Keep LIVE disarmed. Existing V70 private data still lives at
   `%APPDATA%\CoinCatV70`; the state marker and schema remain compatible. This is
   not a new private-data directory. Do not run two versions against it at once.
   Any first-time private-data copy still requires the launcher's explicit approval.

The historical `CODEX_HANDOFF_V70.md` describes v70.0 and is preserved as context.
Internal V60 filenames and V70 batch wrapper names remain for compatibility.
