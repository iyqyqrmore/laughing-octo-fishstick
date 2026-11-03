# CoinCat v1.02 — test in a separate installation

Preserve the existing installation, private records and backups. Extract this
source into a new folder; never overlay a running version or share its data
folder between app processes. Use normal 64-bit Windows Python 3.11.

1. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Expect source
   hashes, syntax verification and numbered isolated tests with elapsed times
   and a 30-second heartbeat. Prior Windows runs took about 22 minutes; a slow
   named test with heartbeats can still be working. Wait for the final COUNTS
   and PASS/FAIL. Errors or failures block acceptance; report the exact traceback.
   A host symlink capability skip is distinct from a test error.
2. Run **tools\RUN_PAPER_REPLAY.bat** without an account connection. This is a
   finite scripted toy-event lifecycle, not a market session or profit test.
   Expect two terminal orders, four simulated fills, zero real orders/verified
   exchange fills and exactly two fictitious SOL. It normally finishes far
   sooner than full verification; do not leave it running overnight.
3. For new data only, **04_FIRST_TIME_SETUP.bat** requires explicit confirmation
   and an empty destination. A new dataset/key cannot recover old tax basis.
   Existing verified recovery tools only copy to a separate empty destination.
4. Launch **01_START_COINCAT.bat**; confirm **CoinCat v1.02** and LIVE blocked.
   Check the larger transparent logo in the upper header. Import any key JSON
   locally on the PC, never into chat. Existing DPAPI/permission checks remain.
5. **Connect / refresh**, then inspect **Allocation**. Review/apply ETH working,
   manual, protected and excluded proposals. These remain RAM proposals, not
   real transfers or allocation reconciliation. Other balances cannot seed the
   paper wallet. An unavailable catalog/fee/funding input means HOLD.
6. Open **Trading Settings**. Start with minimum **$0.01**, initial **50% of
   working ETH**, subsequent source **50%**, review **30s**, reconsider **120s**.
   A custom initial ETH amount must be within the approved working percentage;
   native minima block small orders instead of increasing size. Apply all
   Trading Settings. The first eligible order can use that initial slice once,
   without halving it again. One wallet serves all fourteen directions.
7. In **Auto Trader**, explicitly opt in and press **Start Auto Paper Trader**.
   Inspect shared holdings, available/reserved amounts, every market's native
   bid/ask and direction reasons. **With the current BBO feed, expect zero new
   orders and HOLD/UNKNOWN** because sized exits and verified fee-currency
   evidence are missing. A fresh ETH-USD valuation reference cannot supply
   those missing inputs. Do not loosen gates to force an order.
8. Try the global $0.05/$0.10 presets or type a whole-cent target and Apply.
   The applied summary must show the new version/floor across all directions.
   Draft fields are not applied settings. Profit-only Apply preserves applied
   capital percentages and timing, including any separate unapplied draft.
   Existing orders keep original price/version/expiry and receive a safe review;
   cancellation must reconcile before replacement. STOP retains reservations
   and holdings; it does not confirm cancellation or liquidate inventory.
9. Test **Pause**, **STOP**, clean close, relaunch and **Reconcile paper**.
   A saved session restores RECONCILIATION_REQUIRED; reconciliation leaves
   PAUSED. Pressing Start again is explicit; no new seed or baseline is created.
   New paper session retains the old database and requires new opt-in/Apply.
10. Export diagnostics while open. Confirm v1.02, COMPLETE (8/8), safe policy/
    settings-version/completion counts, actual profit NOT ESTABLISHED. Do not
    upload private paper/financial SQLite files, keys or monitor tokens.

Enable **Local monitor** in **Research Archive → AI Lab / notes**, then run
**tools\START_LOCAL_MONITOR.bat**. Confirm its v1.02 title, global paper policy
and aggregate version/counts; no native amounts/settings/receipts are exported.
Check missing-response/stale states clear earlier current claims. This helper
is read-only and offers no trading/update channel. See docs/V100_MONITOR.md.

Keep the first connected read-only session supervised for **60–120 minutes**.
Check STOP during a request/retry, bounded reconnects, fresh account fee evidence,
quote age/spread/gaps, small-window/DPI tooltips and clean shutdown. Preserve
original expiries through outages. A network interruption must not invent fills
or recreate a seed. Native Windows/DPAPI/single-instance and connected product/
fee evidence require that PC's checks. Proceed to longer observation only after
these pass; time running alone cannot demonstrate predictive improvement.

The old **ETH Growth**, **Legacy scenario mixer**, journal and passive **AI Lab**
are in Research Archive. Their independent hypothetical comparisons never fund
a global paper intent. Existing manual entry/Reset/Apply, chart intervals and
hover controls remain available. For archived workflows see docs/V100_RESEARCH.md,
docs/V100_WORKSPACE.md, docs/PROSPECTIVE_JOURNAL.md and docs/AUTO_PAPER_V1_01.md.

Read docs/GLOBAL_PAPER_V1_02.md for the exact qualification, partial-completion
semantics and copyable discussion handoff. No real order can be submitted.
