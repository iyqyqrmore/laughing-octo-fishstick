# CoinCat v1.05 — Windows update and acceptance

This update adds a separate multi-horizon shadow trial while preserving the existing v1.05 24-hour trial and all private financial records. Never delete a cache/trial to obtain a passing test or reset a benchmark.

## Update an existing v1.05 installation

1. Close CoinCat and its local monitor helper; wait for both to exit. Back up the entire stopped folder, including data. Never copy an open SQLite database or run two instances against one data directory.
2. Download the latest `coincat-v1.05` ZIP into a staging folder. Verify its source hashes with `VERIFY_SOURCE.py`, or setup then `03_VERIFY_COINCAT.bat`. Confirm zero mismatches.
3. This update retires no additional source files. Copy only source-package contents into the stopped **existing v1.05** folder, replacing listed source files and `SHA256_MANIFEST.json`. Preserve `.venv`, `private_data`, `private_backups`, `research_data`, `support_monitor`, saved keys and other private files. The source ZIP contains none of those data folders. Do not overlay pre-v1.05 installations with retired dashboards.
4. Alternatively, use a fresh source folder and the established verified backup/import procedure to retain private data; preserve the entire `research_data` tree while both apps are stopped. A blank data directory starts another installation rather than recovering the old trial. Keep the original backup intact.
5. Run **03_VERIFY_COINCAT.bat** from the updated folder. Expect v1.05, matching hashes, syntax success and zero failures/errors. Save final runtime, discovered, counts, skipped tests and any traceback. Launch only after it passes.

## Fresh installation and offline verification

Install 64-bit Windows Python 3.11 with `py` if needed. Extract the complete ZIP to a short path such as `C:\CoinCat_v1.05`; do not run inside it. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Setup uses hash-locked dependencies in this folder's `.venv`.

The verifier prints named tests, timing and a 30-second heartbeat. Windows may take 20–30 minutes or longer. Wait for final `COUNTS`. A stated host-symlink capability skip is acceptable; SQLite cleanup errors are failures. Tests use disposable synthetic state and forbid HTTP/WebSockets before discovery; they never open your key/account. Linux success does not replace native Windows acceptance.

Optional **tools\VERIFY_INTELLIGENT_TRADER.bat** includes both policies, history, construction, chronology, fees, lifecycle, recovery, privacy and Tk. It does not replace full verification.

## Connect and identify the policy

1. Start **01_START_COINCAT.bat**. Confirm v1.05, seven tabs, initially 1h charts, inset logo, private live portfolio total/holdings hover and **Live orders blocked ON**. Close exits; tray/minimize remains removed, maximize remains. Windows shutdown must not be vetoed.
2. Connect with your saved local key/data; never send keys or databases to chat. Check books, candles, available balances, manual history and fee estimates. Stale/partial inputs must be labeled. Non-watch holdings in account totals do not become shadow funds.
3. Open **Intelligent shadow…**. Select **24-hour baseline** or **Multi-horizon**. An existing opted-in 24h trial recovers with original settings; user pause persists. Selecting another view does not pause/start/reset/migrate either trial.
4. Select **Multi-horizon**, inspect **Frozen settings**, then press **Start / resume intelligent shadow** once to opt in to its own trial. Default first Start freezes fresh available BTC/ETH/SOL/LINK/ADA balances, excluding holds. Fictional funding is only a pre-start choice. No funds move. To observe only one policy, explicitly Pause the other.

## Read progress and explanations

1. The top shows state/freshness, last observation age, review/direction/order/fill counts, valid hours and completion percentage. Advancing counts with HOLD mean it is running; zero orders is not a hang.
2. **Forecast / rejections → History / progress** shows five fixed USD references across minute/five-minute/hourly grids: bars, pages, aligned totals, jobs, failures, last success age and review/backoff. Full windows are 4,320 minutes, 2,880 five-minute bars and 2,400 hours. Immediate needs 61 minutes. Valid hours measure current monitoring, not training readiness.
3. After the current worker/manual reconciliation ends, overdue history gets a bounded opportunity every 30s. Jobs rotate references/grids and alternate current/older backfill, one page of at most 350 bars. Failed references retry independently. Network latency and sparse products can delay readiness; no guaranteed completion time is claimed.
4. **By horizon** shows fourteen directions and six outcomes. Missing 24h history must not suppress a supported short horizon. Review exact reasons and history/data/fees/rules/funds/liquidity/uncertainty/risk/advantage counts. These are evaluations, not exchange order rejections. Conflicting closed prices require review, never silent overwrite. Save diagnostics if stuck; do not reduce fees or delete data.
5. **Construct / explain…**: choose ETH-BTC BUY, enter an all-in **BTC source budget** or use native minimum, then explain. Confirm ETH base quantity, BTC/ETH limit, own BTC fee assumption and native increments/minima. SELL uses ETH quantity and deducts its own BTC fee from proceeds. Preview cannot submit/cancel/authorize.
6. Read A native rules/funds, B six economic scores, C conditional public evidence versus unknown fill calibration, D shadow-only authority. The November 9 example computes a conditional 0.50% estimate; exact actual commission and original economics remain UNKNOWN. Today's quotes never reconstruct that historical recommendation.

## Supervised shadow and recovery checks

Observe 15–30 minutes, then 60–120 minutes before overnight use. HOLD is valid. Check maker BID BUY/ASK SELL, 30s review, 120s assessment, 600s child, 1,800s original campaign and three replacements. No forced trade/exit or taker fallback. Touch/time never fills. Public-tape fills are conditional, not Coinbase receipts; no-fill provider deliberately infers none.

Fees occur once on filled quantity only. Partial inventory remains owned; canceled unfilled size pays zero. UNKNOWN blocks replacement. Remaining holds, racing fills and original funding/quantity/expiry/attempts reconcile before replacement. Fake replay receipts are not realistic exchange fill evidence.

**Portfolio / evidence** shows modeled and original HOLD USD on identical references, net USD/%, losses/open inventory, drawdown, native fees and rolling 1/6/24h changes. A justified forecast trade can initially lose marked value through its fee. No future reverse commission is paid and no horizon mandates a sale. The chart retains full span with reduced older resolution and recent rolling detail; the private journal retains all recorded marks/intents/receipts.

Pause/resume, then restart and disconnect/sleep/reconnect. Identity/settings/benchmark/wallet/fees/hours must persist. Offline/stale/partial/suspended time does not count or fill. Recovery waits for fresh inputs; user pause remains. UNKNOWN/corruption stays for review. At 168 valid hours the report freezes and no new trial starts. Zero trades validates monitoring/recovery, not profit.

**Comparison** labels independently started live trials NOT PAIRED. Do not rank different starting portfolios/periods. For identical synthetic studies run `verification/multi_horizon_scenarios.py --output <folder-outside-source>`. The two-hour favorable/reversal/no-fill studies do not mature a 24h forecast or prove live returns.

## Diagnostics and monitor

Stop the old helper, enable **Local monitor**, then run **tools\START_LOCAL_MONITOR.bat** from the updated folder. Check current v1.05 freshness, separate policy identities, per-horizon counts and history progress; automatic real authority stays false. Helper routes are read-only.

Export Diagnostics/monitor snapshot: fixed codes/counts/enums only, without quantities, USD advantage, native fees, keys, paths, IDs, receipts or forecasts. Private reports/CSV/audits stay local. Report source commit, Windows runtime/counts, history/rejection progress and controlled recovery errors. Exact account settlement auditing remains separate.

Keep actual live block ON throughout acceptance. Deliberate OFF + manual click remains REAL bounded trading; neither shadow policy can automatically place real orders. Connected Windows/product/history/fee/account checks, forecast/fill calibration and any future live pilot remain pending.
