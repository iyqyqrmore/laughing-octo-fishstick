# CoinCat v1.03beta — manual trading test

Use a separate extracted folder. Preserve the installed folder, private records
and backups; do not overlay a running version or share data between processes.
Use normal 64-bit Windows Python 3.11 and the locked setup dependencies.

For the Windows resize-verification follow-up, first run
**tools\VERIFY_MANUAL_WINDOW.bat** after setup. It verifies the source hashes
and runs only the **ten** isolated manual-window checks, including delayed
native resizing. This provides a quick check before repeating the full suite;
its focused PASS does not replace full verification. The corrected full suite
discovers **488 tests** and source verification checks **158 files**.

1. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Wait for the
   final COUNTS and PASS/FAIL. Windows previously took about 22–30 minutes;
   numbered tests and 30-second heartbeats show progress. Any failure/error
   needs its final traceback. A host symlink-capability skip is separate.
2. Recover verified private data to a separate empty destination, or use
   **04_FIRST_TIME_SETUP.bat** only for explicitly confirmed fresh data.
   Preserve financial backups; an empty setup cannot recover historical basis.
3. Launch **01_START_COINCAT.bat**. Confirm **Manual Spot**, seven market tabs,
   market dropdown with favorite star, upper-right transparent logo,
   **Live orders blocked ON**, and **Automation OFF**.
4. Import the key JSON locally if needed, then **Connect / refresh**. Never
   upload keys, private databases or monitor tokens. Confirm ETH-BTC prices
   are BTC per ETH, amounts ETH, and balances distinguish available from held.
   Read-only REST pricebooks are sufficient; WebSocket is not required.
5. Switch between all seven tabs, try grouping and the base/quote amount
   selector, and resize the window. The scrollable ticket keeps its order
   button visible. Stale books clear; they never become simulated fills.
6. In **Trade details / CSV**, select an order or enter its full ID and click
   **Read order & fills**. Then **Cross-check statement CSV**. Reopen details
   to inspect the saved report revision. A unique consistent native/time match
   can corroborate settlement while API fee currencies remain unchanged.
   Ambiguous/missing/conflicting rows stay unresolved. No order is placed here.
7. Use **Diagnostics** and optional **Local monitor** in the toolbar, then
   **tools\START_LOCAL_MONITOR.bat**. Confirm the manual LIMIT provider,
   current gate, current CoinCat session counts and Automation OFF. Imported
   Coinbase history has its own order/filled/known-flow/unresolved-settlement
   counts, updated after history reads and CSV cross-checks. A filled imported
   order remains visible while its settlement arithmetic is UNKNOWN. Exports have
   no native amounts, prices, limits, IDs, key material or private paths.

## One bounded real manual order

This step can move real funds. Offline tests cannot prove that today's connected
exchange contract or Windows DPAPI works. Keep Coinbase open alongside CoinCat.

1. Open **Caps…** and review the defaults: **$5/order, .005 ETH-equivalent
   session turnover, four submissions, one open order, 1800 seconds, .02 fee
   buffer fraction (2%)**. They are active risk limits for manual tickets.
   Pick a small valid amount within the caps and exchange minimums. If a native
   minimum exceeds the cap, stop and review; CoinCat will not enlarge the order.
2. Choose the native market and side. **SELL at ASK** normally rests.
   **BUY at ASK with Post Only OFF** may take immediately. Its fee estimate
   uses the maximum authenticated maker/taker rate. With **Post Only ON**, use
   BID to buy or ASK to sell; a crossing price must be rejected without fallback.
3. Deliberately switch **Live orders blocked OFF**. It enables manual clicks;
   it does not start a trader. Click the ticket's Buy/Sell button once.
   Fresh scope/permissions, rules, funds, valuation caps and exchange preview
   precede the one create request. There is no predicted-profit prerequisite.
4. Find the matching order on Coinbase. Compare market, side, size, native
   limit, Post Only and status. Inspect actual fills/fees, not quote touches.
   Use **Open orders → Cancel selected**, or **Cancel & refresh ticket**.
   Wait for terminal cancellation and complete reported fills. A refreshed
   remainder is only a draft; inspect it and click again to send it.
5. Test a partial fill/cancel if naturally available. A racing full fill must
   leave no remainder. A network timeout/unknown result must lock the original
   identity rather than retry. Refresh/reconcile and inspect Coinbase before
   doing anything else. External/manual Coinbase orders are read-only here.
6. Switch block ON before finishing. Keep CoinCat open until owned orders
   reconcile. Closing performs one bounded cancel/read pass and retains locks
   if it cannot establish the outcome; verify uncertain orders on Coinbase.
   Restart always blocks live creation and never repeats a submission.
7. Limits survive reconnect/restart. After every order is terminal, **New
   session · archive completed** preserves the completed journal and starts
   blocked with the same caps. It cannot clear an unresolved order.

The older paper replay remains available at **tools\RUN_PAPER_REPLAY.bat** as a
finite offline simulation. It does not run this manual client or test live
connectivity. **tools\STORAGE_REPORT.py** is report-only unless source-cache
cleanup is explicitly selected; financial/history data is never deleted.

First establish manual placement, fills and cancellation locally. Automation,
automatic refreshed replacement and predictive-performance claims are separate
future work. Historical guides describe archived workflows, not today's launcher.
