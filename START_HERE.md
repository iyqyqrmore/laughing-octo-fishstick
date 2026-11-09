# CoinCat v1.05 — Windows installation and acceptance

Use a new **coincat-v1.05** source folder. Keep the installed folder, private data and backups intact. Do not merge extracted files into an older checkout: removed dashboards and stale manifests would remain. This release has its own shadow trial path and never adopts or resets v1.04 trial state.

## Install and verify offline

1. Download the `coincat-v1.05` branch/source package and extract it completely to a short local path, such as `C:\CoinCat_v1.05`. Do not run inside the ZIP.
2. Install 64-bit Windows Python 3.11 with the `py` launcher if needed. Run **02_SETUP_COINCAT.bat**. Dependencies install into this folder's `.venv` from hash-locked requirements; the current shortcut is **CoinCat v1.05 - START**.
3. Run **03_VERIFY_COINCAT.bat**. Expect v1.05, zero source-hash mismatches, source syntax success and the complete isolated suite with zero failures/errors. It prints each test and a 30-second heartbeat. Native Windows runs may take 20–30 minutes or longer. An `E`, `FAIL` or traceback needs the final error details; moving dots alone are not a pass.
4. Optionally run **tools\VERIFY_INTELLIGENT_TRADER.bat** for focused forecast/fees/sizing/order/recovery/privacy/Tk checks. It is not a substitute for the full verification. **tools\VERIFY_MANUAL_WINDOW.bat** checks the retained manual workspace.
5. Save the final `RUNTIME`, `DISCOVERED`, `Ran`, `COUNTS` and skipped-test lines. A host symlink capability skip is acceptable only when stated. SQLite cleanup/file-lock errors are failures; do not delete the trial or suppress cleanup errors.

All isolated tests use disposable synthetic state and forbid HTTP/WebSockets before discovery. They never open your saved key or exchange account. A successful Linux report does not replace this native Windows rerun.

## Connect read-only and inspect

6. Start **01_START_COINCAT.bat**. Confirm **CoinCat v1.05**, seven tabs, 1h chart defaults, an inset transparent logo and the live account total/holdings hover. Confirm **Live orders blocked ON**. Actual account totals may be partial/stale or contain assets outside the five-asset shadow universe; they do not become shadow funds.
7. Use your existing authorized local data setup and key. For a separate fresh installation, use **04_FIRST_TIME_SETUP.bat** only for a genuinely new empty destination. To reuse existing financial history, follow the established private-data import/backup tools; never copy over an active database or run two instances against the same data directory. No account key or private record needs to be sent to chat.
8. Click **Connect / refresh**. Verify current native BID/ASK, depth, exchange candles, balances, manual history and fee display. Stale/partial data must be labeled. Keep the live block ON throughout this acceptance procedure.
9. Open **Intelligent shadow…**. Default portfolio is **ACCOUNT_AVAILABLE**: first Start freezes the freshly read available BTC/ETH/SOL/LINK/ADA balances, excluding holds. Optional FICTIONAL_100_EACH creates a different baseline only before first Start. The trial is simulated; no account funds move.
10. Press **Start / resume intelligent shadow** once. Initial native product priming is followed by bounded GET waves. The history cache backfills five USD references over approximately 100 days, one bounded page per background job. It may take several minutes, and sparse/unavailable historical products can leave the model in HOLD. Progress shows aligned hours out of 2,400 and current coverage. USD references are not extra trading markets.

## Supervised shadow acceptance

11. Observe for 15–30 minutes, then 60–120 minutes if all checks pass. Inspect **14 directions**, **Best opportunity**, **Orders**, **Portfolio / evidence**, **Forecast / rejections** and **Frozen settings**. HOLD is valid. Directional checks/rejections are not orders. Do not loosen protections just to generate activity.
12. Confirm native directions and units. SELL ETH-BTC exchanges ETH for BTC; BUY ETH-BTC exchanges BTC for ETH. Projected maker commission appears once in its native quote currency under a declared modeling assumption. Quotes/candles touching a limit must not create a fill. A modeled fill is conditional public-trade evidence, never an actual Coinbase receipt.
13. Confirm a resting order is retained only while justified; a 120s review is not a forced trade. Finite child/campaign expiry and three replacement budget remain. Cancellation releases only reconciled remaining holds. Partial inventory is retained; UNKNOWN blocks replacement. Do not manufacture replay receipts and then interpret them as fill feasibility.
14. Inspect modeled USD portfolio and original HOLD at identical references, USD/% advantage, open losses, paid modeled native fees, drawdown, forecast edge and rolling 1/6/24h history. Negative results must stay visible. A filled leg may immediately lose marked value through fees. No hypothetical exit is debited and no sale is mandated after 24 hours.
15. Pause. The shadow order requests cancellation, preserves filled inventory and stops valid time; manual live block remains ON. Resume keeps the same trial identity, baseline, settings, wallet, fees, campaign budgets/expiry and accumulated hours.
16. Disconnect the network or sleep the PC, then restore it. Stale/gap/offline/suspended periods must not count as valid full monitoring or create fills. Restart with open/partial/unknown orders must reconcile before new placement. Do not expect missed forecast horizons to be backfilled with favorable later quotes.
17. **Close exits** after checkpoint/bounded owned manual-order reconciliation. There is no tray icon, hide-to-tray or custom minimize behavior; the Windows minimize button is removed and maximize remains. Test close, explicit Exit safely, Windows shutdown and restart locally. Shutdown must not be vetoed. Default manual live block returns ON after restart.
18. **History archive** reads old v1.04 trial checkpoints without starting controllers or changing clocks/financial records. Never delete a damaged record to make recovery pass. At 168 valid hours the new trial completes, preserves its summary and starts no new trial automatically. Zero trades can validate monitoring/recovery, not profitability.

## Redacted exports and evidence

19. Stop any older monitor helper. Enable **Local monitor**, run **tools\START_LOCAL_MONITOR.bat**, and check v1.05, current versus stale capture, intelligent policy/horizon/history/coverage/rejection categories, order counts, restart/completion and absent automatic real authority. The helper is read-only. Historical v1.04 captures must be labeled historical.
20. Export **Diagnostics** and the monitor snapshot. These redacted outputs contain fixed codes and counts only: no wallet amounts, USD gains, native commissions, account/order/trial IDs, keys or raw receipts. Private report/replay/CSV/audit files contain financial details and stay on your PC.
21. Report source commit, Windows runtime/counts, history state, native/valuation coverage, rejection breakdown, recovery behavior and any controlled errors. Do not send secrets. Read-only November 4 settlement audit remains **tools\AUDIT_MANUAL_FILLS.bat**; no new settlement claim is inferred from synthetic tests.

Do not turn off the actual live block to test the shadow. Automated real-money execution is unavailable. Forecast accuracy, maker execution calibration, exact account settlement and a separately authorized bounded live pilot require their own evidence.
