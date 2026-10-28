# CoinCat v70.5 — responsive stream checks and bounded broad scanning

Approved markets remain continuously visible through the existing public stream.
Urgent research verifies actual funded bid/ask routes through the same canonical
planner and RAM SHADOW consumer. This cumulative patch retains v70.4's complete
inventory, small-wallet, immediate-reuse and self-contained-folder behavior.
**LIVE order POST remains unconditionally blocked.**

* Fix the false 90-second warning: it used the previous broad scan's start time
  whenever any job was busy. Track the actual job/its start, require an active
  broad scan, and show current phase/phase age plus last urgent-decision age.
  A genuine slow scan remains visible without guessing that connectivity is
  responsible. Completed/failed jobs do not leave the warning on later work.
* Replace unbounded public-quote executor joins with bounded batches. Deep quote
  work has a 12s pass budget; catalog quote work has 6s. Each batch contains at
  most 16 pairs and waits at most 4s. Urgent checkpoint time counts against the
  pass budget. An atomic checkpoint may finish after the remaining budget;
  these budgets are not a hard deadline for the entire broad job.
* Deferred deep pairs rotate into following passes. The catalog cursor advances
  only for attempted rotation work. Late quotes never reach the journal, and
  unfinished background GETs cannot create an accumulating worker pool. Broad
  and urgent collectors have separate outstanding-request guards and retain the
  same process-wide HTTP rate budget. No concurrent canonical planners are added.
* Run urgent checkpoints between broad research phases, including signals,
  maintenance, strategy/horizon work and route planning. A completed checkpoint
  leaves five seconds before another checkpoint, allowing background progress.
  A due broad scan receives its turn after 30s of scheduler deferral; it still
  services urgent checkpoints. Required account verification comes first.
* Consider all currently ranked approved, fundable stream alerts before choosing
  the three urgent targets. Prefer candidates over recently known-wide products,
  retaining a rotating slot for the remainder. No coin is permanently blacklisted
  for its last quote. REST request/target budgets remain bounded.
* Discovery can use another quote product: an ALT-USD event can lead to a direct
  ALT-BTC order when BTC funds the swap. Verify the actual conversion book, fees
  and synchronized source/destination USD paths. A wide discovery book alone no
  longer blocks a different liquid funded route. No bridge product is invented.
  Experimental FIFO price-band identity now follows the actual one-order pair.
* Distinguish available fresh cached books from newly fetched fresh books. Record
  worker-owned duration, per-phase timings and bounded-fetch/deferred counts in
  the existing diagnostics. UI queue delay no longer inflates completed scan time.

Validation: 372 offline tests, including 14 new worker/scanning regressions, the
actual broad-cycle path with mocked public quotes, real background-thread timing,
an unfinished-GET isolation test and actual urgent-to-FIFO alternate-pair replay.
The full 18-section GUI diagnostics and Python 3.11 source syntax also pass.
Tests use synthetic data and forbid external HTTP. See VERIFICATION.txt.

A public stream/REST budget cannot guarantee catching every opportunity before
prices change. This patch reduces avoidable waiting and candidate starvation;
it does not establish actual execution, price depth or profit. A slow individual
SQL/CPU/authenticated-account phase is reported, not forcibly killed or mistaken
for a completed scan. Connected Windows timing still needs local verification.
No private financial records, keys, schemas, spending limits or real-order
permissions were changed. See START_HERE.md for current-data import instructions.
