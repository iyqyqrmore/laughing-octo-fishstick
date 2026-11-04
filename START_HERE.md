# CoinCat v1.03beta — separate Windows installation

Preserve the installed folder, private records and backups. Extract into a new
folder; never overlay a running version or share its data between app processes.
Use normal 64-bit Windows Python 3.11 and the locked setup dependencies.

1. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Wait for final
   COUNTS and PASS/FAIL. Prior Windows verification took about 22 minutes;
   numbered tests and 30-second heartbeats distinguish progress from a hang.
   Any error/failure needs its final traceback. A host symlink capability skip
   is separate from an error. Tests use disposable state and no exchange calls.
2. Run **tools\RUN_PAPER_REPLAY.bat** without an account connection. This finite
   toy replay normally finishes quickly: two terminal orders, four simulated
   fills, two fictitious SOL, zero real orders. It is not an overnight market
   or profit test. **tools\STORAGE_REPORT.py** reports source caches; only
   `--clean-source-cache` removes source `.pyc`. No financial/history deletion.
3. Use **04_FIRST_TIME_SETUP.bat** only for explicitly confirmed new empty data.
   Verified recovery copies to a separate empty destination. A new dataset
   cannot recover missing historical tax basis. Preserve original backups.
4. Launch **01_START_COINCAT.bat**. Confirm **v1.03beta**, the transparent header
   logo, **Live orders blocked ON**, stream OFF and no automatic start. Import
   keys only on your PC. Never upload keys, private SQLite or monitor tokens.
5. With block ON, **Connect / refresh**, inspect **Allocation** and review/apply
   working ETH, manual/protected carve-outs and exclusions. These are RAM
   proposals, not transfers. Apply Trading Settings: **$.01**, initial **50%**,
   subsequent source **50%**, review **30s**, reconsider **120s**. Profit-only
   Apply changes no capital/risk/timing setting or accepted order price.
6. Test PAPER first: opt in, **Start Auto Paper Trader**. One hypothetical ETH
   slice serves all fourteen directions. Expect **HOLD/UNKNOWN** if sized exits,
   explicit native fee units or residual valuation are missing. Touches never
   fill. STOP/reconcile/restart must retain prices, reserves and original expiry.
7. Optionally enable **Public order-book stream**. Four ETH anchors plus two BTC
   crosses are observed at a time; a selected cross can replace a scheduled
   cross. ETH-BTC price is BTC per ETH, amount ETH. Grouping/quote amount affect
   display only. Gaps/stale heartbeats/product data must show stale/resyncing.
   **Use healthy public L2** defaults OFF; enabling it cannot prove fee currency.
8. Stop scanning before deliberate history reads. In **Research Archive → Manual
   Trade Lab**, read the complete order ID locally or a narrow **1–168 UTC hour**
   window. A view-only key can use this importer even if main Connect requires
   stricter permissions. Inspect quantity/gross/commission/currency, native
   changes, coverage and maker/taker fields. Missing/contradictory data remains
   UNKNOWN. Creation-to-fill is not measured acceptance or queue time.
   **Statement math…** reads local CSV without importing records/changing fees.
9. Export diagnostics: **v1.03beta**, **COMPLETE (8/8)**, separate manual/bot/paper
   counts, correct live gate, no native amounts/IDs/paths. Enable Local monitor
   in **Research Archive → AI Lab / notes**, then run
   **tools\START_LOCAL_MONITOR.bat**. Check safe live/manual/book counts and
   stale/missing-response clearing. The helper has no trading/update channel.

Keep the first connected read-only observation supervised for **60–120 minutes**.
Check native Tk/DPI/hover/resize, rapid tab selection, STOP during reads/retries,
fresh fees, reconnects and clean shutdown. Cloud tests cannot establish the
current server contract, Windows DPAPI or actual account settlement.

## Deliberate bounded REAL beta

This source can send actual orders. Native Windows, connected settlement and
independent operational/financial review are **not proven** by offline checks.
See [the acceptance ledger](docs/BETA_1_03_ACCEPTANCE.md).

1. Stop PAPER/research and wait for current reads. In Trading Settings apply
   proposed REAL limits: **.005 ETH session, $5/order, one open, four attempts,
   1800s, maximum fee 2%**. The fee ceiling is not an assumed actual fee. Native
   minima block small orders; size is never increased to meet them.
2. Confirm allocation/global settings. Deliberately switch **Live orders blocked
   OFF**, then **Start REAL Beta Trader**. Fresh exact portfolio permissions must
   explicitly allow view+trade and disable transfers. No USD, margin, borrowing,
   futures or outside product/portfolio is traded.
3. OFF **does not force a trade**. Missing fee/depth/FX/residue/profit evidence
   means HOLD, not guessed fees. BUY rests at bid; SELL at ask. Fee-adjusted ASK
   is a cost benchmark, not authorization for a marketable/taker BUY. Qualifying
   autonomous orders run without repeated approval.
4. Watch the matching owned order on Coinbase: fixed price/quantity, Post Only,
   portfolio, actual fills/fees. Reconsideration requests cancellation at 120s
   from acknowledgment. No replacement spends reserved/partial proceeds before
   terminal reconciliation. Every child consumes the original attempt budget.
5. Use **STOP** or block **ON**. Keep the app open until owned orders are terminal
   and reconciled. A cancellation request/ack is not final; inspect Coinbase
   if identity/read/fee uncertainty remains. Holdings, losses and dust remain.
   Closing makes one bounded cancel/read pass and preserves unresolved locks;
   it cannot guarantee exchange cancellation after shutdown.
6. Restart restores ON and reconciliation required. **Reconcile owned live orders**
   leaves PAUSED only after terminal native evidence; another Start is explicit
   and cannot reseed or extend the original limits/expiry. An expired session
   needs operator review, not automatic new funding. **View private live journal…**
   stays local. The beta journal records native flow, not tax/FIFO lots or all
   account cash flows; keep exchange statements for tax records.

Manual consumption/unknown commissions remain unresolved instead of being
attributed as bot profit. AI Lab stays passive. No demonstrated predictive edge,
guaranteed profit or verified after-cost portfolio liquidation is claimed.
