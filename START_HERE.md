# CoinCat v95.0 — first read-only trial

Keep the existing installation and all private records/backups. Extract v95 into
a separate new folder. Never overlay the running installation or share one data
folder between running versions. Use normal 64-bit Windows Python 3.11.

1. Run **02_SETUP_COINCAT.bat**, then **03_VERIFY_COINCAT.bat**. Inspect the exact
   test counts, errors and skips. A failure blocks this preview's acceptance.
2. For a new dataset only, run **04_FIRST_TIME_SETUP.bat** and confirm NEW data.
   It refuses nonempty destinations and creates a verified independent initial
   backup. A new key/dataset does not recover old trades or tax basis. Optional
   recovery under tools copies a complete verified dataset into an empty
   destination only; do not run it casually against your working installation.
3. Run **01_START_COINCAT.bat**. Confirm **CoinCat v95.0**. Import the key JSON
   locally on your PC, never into chat. Existing permission/DPAPI checks remain:
   View + Trade, Transfer disabled. Trade permission does not enable orders.
4. **Connect / refresh**. Companion choices come from authenticated direct ETH
   spot products with explicit tradability, status and valid rules. Nothing is
   preselected. BTC/SOL/ADA availability is NOT VERIFIED. If the list is empty,
   stop with NO QUALIFIED EVIDENCE; there is no USD/USDC fallback.
5. In **Allocation**, review ETH working/manual/protected proposals and exclusions.
   Apply each edited row. These are RAM-only; a checkbox cannot reconcile funds.
   Unassigned, excluded, manual and protected funds never supply this model.
6. **Manual mixer** starts with the defaults below. Model ETH automatically uses
   the full ETH working proposal after connection, less manual/protected/excluded
   amounts. A custom entry stays unchanged through refresh; Reset returns to the
   latest full working default. In **ETH Growth**, choose one to three companions
   under the chart, then **Apply research plan**. Each companion is an independent scenario using the identical ETH
   allocation; do not add the scenarios together as simultaneous funding.
7. Leave target/entry offset/wait/cadence/taker stress at the initial research
   defaults unless deliberately choosing another scenario. Hover labels, controls,
   table rows or details for costs, native dust, timestamps and waiting risk.
   Numeric text fields and keyboard arrows accompany the audio-mixer faders.
8. **Start research**. Verify quote updates and fee evidence. Maker targets are
   hypothetical, not forecasts; no-fill retains initial ETH. Partial/unknown fills
   earn nothing in the app. Even a later target crossing remains uncertain.
9. Test **STOP** promptly. Displayed findings should remain; no late queued result
   should replace them. Change a control or allocation: the plan must invalidate
   and require explicit Apply before restarting. Export v95 diagnostics while the
   app is open. Exports have eight sections and omit private native quantities.

Tonight's goal is startup, data integrity, manual controls, hover usability and
STOP—not a profit verdict. After code/local checks, collect 48–72h of read-only
coverage, then optionally 2–4 weeks across independent regimes. RAM setups and
counts disappear on restart; export before closing. Public quotes use the existing
bounded local research store. Native Windows launcher, DPAPI, single-instance,
cleanup and resource checks still need local evidence. Source restoration and
environment publication are separate; no old publication success is asserted.

## Tonight's defaults

| Control | Default |
|---|---|
| Model ETH | Full available ETH working proposal after carve-outs/exclusions |
| Entry offset | 0 bps |
| ETH target | 0.25% hypothetical net-ETH target |
| Wait limit | 24 hours |
| Scan interval | 5 seconds after each pass |
| Taker stress | 15 bps per benchmark leg |

Entry offset is distance away from the best resting price: BUY below bid or,
for an inverse ETH-base product, SELL above ask. 0 bps uses bid/ask respectively;
10 bps is 0.10% farther away. A larger offset seeks a better entry but may never
fill. Defaults are research scenarios, not recommendations for live orders.

The ETH Growth chart sits above Coins & research. **Candle** selects 1s, 1m, 5m,
15m, 1h, 4h, 1d, calendar month or year. **History** selects one minute, hour, day,
month, year or All stored. The arrows page through time; Latest returns to now.
Wheel changes candle interval. Wide ranges explicitly fit coarser candles to
at most 500 bars. Hover shows sampled OHLC and observation count. There is no
trade volume or invented candle in an empty interval. One-second candles cannot
create observations between five-second scans. All stored reaches only the
history actually present in this installation's public quote database.

Tooltips now open near the pointer, flip above it near an edge, fit the visible
window/monitor work area and scroll when detailed text is long. Move into the
popup to use its scrollbar. Escape dismisses it. Windows monitor/DPI behavior
of this follow-up still requires a native rerun.
