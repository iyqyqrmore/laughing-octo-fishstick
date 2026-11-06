# CoinCat v1.04 — Windows acceptance

For the correction to the two `trial.sqlite3` WinError 32 cleanup errors at
`71d175e`, use the [fresh Windows rerun guide](docs/V1_04_WINDOWS_SQLITE_FIX.md).
The supplied 533-test run failed native acceptance despite all source hashes
matching; retain the original installation/data and verify a fresh extraction.

Use a separate extracted v1.04 folder. Preserve the installed folder and all
private records/backups; never overlay a running installation or share its data
between processes. Use normal 64-bit Windows Python 3.11.

1. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Wait for final
   COUNTS and PASS. Numbered tests and 30-second heartbeats show progress; earlier
   Windows runs took 20–30 minutes. Any failure needs its final traceback.
   **tools\VERIFY_RESUMABLE_TRIAL.bat** is a focused quick check, not full acceptance.
2. Recover verified private data into a separate empty destination. Use
   **04_FIRST_TIME_SETUP.bat** only for an explicitly intended fresh installation.
   Preserve financial records, basis and keys; never upload credentials.
3. Launch **01_START_COINCAT.bat**. Confirm v1.04, seven native market tabs,
   dropdown/favorite star, transparent upper-right logo and **Live orders blocked
   ON**. Connect while blocked. Manual Spot remains available; shadow research
   cannot send, preview or cancel a Coinbase order.
4. Open **Resumable Trial — 168 Valid Hours**. Review the initial shadow caps:
   $5/order, $10 lifetime turnover, four lifetime proposals, up to 50% available
   source inventory, one open proposal, 30-day original intent deadline.
   These are frozen research limits, separate from manual real-order limits.
   Start once. The five-coin actual snapshot is copied as hypothetical inventory
   and the original HOLD benchmark. Subsequent account changes do not fund it.
5. Observe for 15–30 minutes. PRIMING/RECOVERING transitions to RUNNING only with
   fresh validated seven-market coverage, a valuation reference and authenticated
   fee estimates. Confirm valid hours, remaining hours, coverage and HOLD value.
   Inspect policy-qualified opportunity episodes and directional checks, realistic
   fill feasibility (UNKNOWN without a calibrated model), conditional per-proposal
   costs, modeled native fees and net marked portfolio/HOLD comparison.
   Default decisions can remain HOLD. No price touch creates a fill. Proposed
   orders are local hypotheses; modeled fills require explicit replay receipts.
6. On Windows, minimize/close to the tray. Confirm the icon opens CoinCat and
   progress continues. Tray Pause stops valid hours; Resume keeps the same trial.
   Use **Exit safely** in the tray to quit. Restart after a short or overnight
   break: confirm the same trial, holdings, benchmark, limits and accumulated
   hours. Offline hours must not appear as valid time. User-paused stays paused.
   Windows shutdown must proceed normally; recovery uses the last checkpoint.
7. Disconnect the network, wait beyond quote freshness, reconnect. The state must
   show a gap without growing valid time; recovery needs fresh full coverage.
   Check multiple restarts and a several-day gap. Preserve a review-required
   database; do not delete it to manufacture a fresh trial. At 168 hours the
   trial freezes and writes a private summary; it never starts another trial.
   Zero qualifying opportunities, proposals, fills and fees must also complete:
   monitoring COMPLETE, portfolio equal to HOLD, profitability UNPROVEN.
8. Export **Diagnostics** and optionally enable **Local monitor**, then run
   **tools\START_LOCAL_MONITOR.bat**. Confirm v1.04, separate current manual and
   imported-history counts, and shadow state/progress/counts. Exports contain
   no monetary amounts, prices, IDs, trial UUIDs or private paths. The detailed
   trial dashboard and summary remain private on your PC.
9. For the November 4 evidence, choose **November 4 fee audit…** in the trial
   dashboard, or run **tools\AUDIT_MANUAL_FILLS.bat** and select the statement CSV.
   It uses the saved key for bounded GET-only history reads. Keep the detailed
   JSON local. Partial history, absent fee currencies and unmatched rows remain
   UNKNOWN; CSV arithmetic never changes future authenticated fee settings.

Shadow acceptance does not require turning off the manual live block. Turning
it OFF still enables actual manual Buy/Sell clicks under the existing caps;
it never grants automatic live permission. A future bounded autonomous live
pilot needs separate authorization and connected accounting/recovery acceptance.
See [the trial design](docs/V1_04_RESUMABLE_TRIAL.md),
[retirement map](docs/V1_04_RETIREMENT.md), and
[fee audit evidence](docs/V1_04_FEE_AUDIT.md).

Historical guides and **RUN_PAPER_REPLAY.bat** describe retained compatibility
workflows. The replay is finite offline simulation, not a live venue test.
