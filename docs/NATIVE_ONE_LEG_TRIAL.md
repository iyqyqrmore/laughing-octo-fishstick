> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

# Native one-leg trial — v1.04

Open **Native one-leg trial** in the main header. This is the new 168-valid-hour
trial requested for a fictional portfolio with **$100 each in ETH, BTC, ADA,
LINK and SOL**. It uses live read-only market data and explicitly assumed fills.
The initial quantities are frozen once from fresh native-market USD midpoint
references; tiny seed-quantity rounding makes the starting total approximately
$500. Your real account balances never fund this portfolio.

The previous portfolio-policy trial remains available under **Previous trial**.
Starting the new trial pauses that earlier policy while preserving its records,
original quantities, settings and accumulated valid hours. Its hours are not
transferred to the new trial: the baseline and execution assumptions differ.
Manual Spot trading, permissions, caps and private financial records are retained.

## A single leg

All seven approved markets participate: ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH,
LINK-BTC, SOL-BTC and ADA-BTC. Each fresh observation wave, about every ten
seconds, attempts one simulated order per market, alternating BUY then SELL.
They share one portfolio and settle sequentially; the same coin cannot be spent
twice. There is no USD order cap, lifetime turnover/attempt cap, artificial
source-fraction cap, one-cent threshold or mandatory return-to-ETH evaluation.

- **BUY at ASK** is the default: exact current native ASK and authenticated
  taker-rate estimate, with a marketable LIMIT assumption.
- **BUY at BID** is an explicit alternative: exact BID and maker-rate estimate,
  under a Post Only assumption. Choose the BUY basis before starting; it is
  frozen for that trial's interpretation.
- **SELL at ASK** uses the exact native ASK and maker-rate estimate under a
  Post Only assumption.

Each leg pays its own fee once. No future return fee, round-trip charge or
slippage surcharge is added. A later independent SELL or BUY pays that later
leg's own fee. Later prices come from refreshed books, without a historical
fee markup or a forced break-even price. Losses are retained.

For a BUY of `q` base coins at native price `p`, with quote-denominated fee
rate `f`, quote cost is `q × p × (1 + f)`. For a SELL, quote proceeds are
`q × p × (1 − f)`. `q` remains the base order amount; fees are separate.

For example, a hypothetical `0.00000001 ETH` BUY at `0.0294 BTC/ETH` with
`0.9%` taker fee has a modeled fee of `0.000000000002646 BTC` and total cost
`0.000000000296646 BTC`. The base quantity remains `0.00000001 ETH`, rather
than `0.00000001009 ETH`. This example is valid only if the authenticated ETH-BTC
base increment, base minimum and quote minimum all permit it. Screenshots do
not override current product metadata. The rates are examples, not fixed settings.

Current authenticated maker/taker rates are required; missing/stale rates show
a specific waiting reason with no fallback. Commission currency is an explicit
quote-coin assumption (ETH or BTC). The estimate uses the exact proportional
rate; authenticated exchange commission rounding/precision remains unverified.
A product's quote increment is not proof of fee precision. Actual imported
exchange fill commissions and their evidence remain separate and unchanged.

## Adjusting order size

The **Order sizing** tab has a slider for each market. Zero means the smallest
order that meets both native base and quote minimums, rounded to the base
increment. Moving toward 100% increases quantity toward the available simulated
source inventory after that leg's fee and the exchange's native maximums.
The slider changes base quantity, not BID/ASK price or the fee percentage.

Press **Apply sizes to future simulated orders**. Each applied change gets a
durable version; previous SIM fills, fees, quantities, IDs and settings versions
remain unchanged. The native preview shows the next quantity and its separate
fee. AI sizing control remains off; no automatic optimizer is claimed here.

Every assumed order receives a local `SIM-...` ID and `ASSUMED_FILLED` status.
Canonical native fill normalization/settlement updates the shared wallet and
cumulative native fees. An assumed fill is not an exchange acknowledgment,
queue observation, actual maker/taker classification or realistic fill evidence.
No SDK create, preview or cancel method is available to this engine. Changing
the manual live switch does not give it submission authority.

## Observation, recovery and evidence

The new trial uses the existing monotonic 168-hour accounting rules. Full valid
time requires fresh synchronized coverage of all seven native books, valid
product rules, applicable authenticated fees and consistent valuation references.
Paused, offline, suspended, disconnected and partial intervals do not earn full
hours. A missing USD reference after seeding can make valuation/time partial
without preventing otherwise valid native one-leg arithmetic. Duplicate cached
frames cannot renew an observation lease or create extra assumed orders.

An opted-in trial resumes after checkpoint/ledger integrity validation and fresh
inputs. Explicit Pause persists across restart. Startup never reseeds balances,
resets counters or invents downtime orders. Transient read gaps wait/retry;
corrupt or uncertain checkpoints require review and are preserved without reset.
At 168 valid hours the trial freezes, including a private completion report in
its database, and cannot start new orders or reset itself.

The private portfolio view compares the current simulated portfolio with holding
the original native quantities at the same midpoint references. It includes
modeled fees and open inventory; it is before unexecuted exit costs. Results are
conditional on assumed fills and do not demonstrate executable profitability.
Completion validates observation/recovery/accounting behavior, not a trading edge.

The isolated ledger is `research_data/assumed_fill_sandbox/active.sqlite3`.
It contains the seed, append-only SIM orders, settings history, clock and frozen
completion report. The UI's recent-orders limit does not trim the ledger. No tax,
FIFO, real balance, imported receipt, previous trial or backup is rewritten.
All SQLite connections/cursors close explicitly on success and exception paths.

Diagnostics and the local monitor expose only controlled assumed-state/counts,
maker/taker counts, cumulative valid seconds and restart counts. Native prices,
amounts, fee currencies, slider settings, wallet values and SIM IDs stay private.
Assumed counts never become observed fills, previous-trial fills or proof of profit.

## Fresh Windows test

1. Preserve your installation and private records/backups. Extract the new source
   into a separate folder. Run **02_SETUP_COINCAT.bat**.
2. Run **tools\VERIFY_ASSUMED_FILLS.bat** for the focused synthetic tests, then
   **03_VERIFY_COINCAT.bat** for the complete suite. This source has **200 hashes**
   and **602 distinct tests**. Require zero failures/errors; the existing
   host-symlink capability skip may remain on Windows.
3. Launch with **Live orders blocked ON**, open **Native one-leg trial**, connect
   and press **Start / resume assumed fills**. Confirm one initial fictional
   $100 slice per watched coin, minimum native sizes, BUY ASK taker estimates,
   SELL ASK maker estimates, one fee per order and SIM-prefixed IDs.
4. On **Order sizing**, change one slider and Apply. Confirm a new settings
   version affects future orders, while earlier IDs/fees/amounts remain intact.
5. Pause/restart, resume/restart and test a disconnected interval. Confirm the
   same seed/wallet/hours survive, pause persists, and offline time creates no fills.
   Check cumulative valid time versus partial/disconnected coverage.
6. Inspect diagnostics/local monitor: assumed counts and trial progress appear,
   while private quantities/IDs/prices do not. No real Coinbase order should exist.

Cloud tests and previews use synthetic data and forbidden HTTP/WebSockets.
Native Windows rendering, actual endpoint availability and the full real-time
168-hour observation still need local validation.
