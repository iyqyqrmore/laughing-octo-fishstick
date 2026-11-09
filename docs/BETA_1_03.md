> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

# v1.03beta design and discussion handoff

Base: published v1.02 `a09a1f3eab106f8d775e2ba76e80e29743292bd4`.
Branch: `coincat-v1.03beta`. The owner's direct instructions authorize this
implementation, an ON-by-default switch permitting actual live orders when
deliberately disabled, and commit/push as 1.03beta. They supersede the attached
handoff's permanent LiveBlocked restriction. They do not constitute connected
test evidence, independent readiness review or a proven profitable strategy.

## Execution, caps and ownership

`coincat_live_beta.py` owns a separate REAL native-flow journal;
`coincat_beta_controller.py` runs on the app's single account worker.
`LiveBroker.submit(live_dispatch=...)` is the sole create-order path: durable
once-only dispatch grant, fresh explicit view/trade/no-transfer and portfolio,
authenticated product/native limits, fresh uncrossed book, Post Only and process
gate checks precede `limit_order_gtc_buy/sell(post_only=True)`. The unreachable
legacy market-submit body was removed. Old positional calls remain blocked.
There is no market/taker/IOC, outside product, transfer or preview fallback.

Live block is ON at boot/restart, STOP and unknown execution. OFF alone doesn't
start. Apply limits, deliberately OFF, then explicit Start allows ordinary
qualified trades without further prompts. Pending cap clarification defaults
conservatively to **.005 ETH, $5/order, one open, four attempts, 1800s, 2% fee
ceiling**, initially unapplied. Funding is min(50% fresh working ETH after
carve-outs, ETH cap), once. Later source is up to 50% available owned inventory,
within original session/native caps. No account BTC/SOL/ADA/LINK is adopted.
Global settings have immutable versions; capital and original expiry stay fixed.

Shared canonical global/receipt modules qualify every entry against the original
ETH slice, including entry/exit fees once, sized exits, native rounding, residuals
and fresh ETH-USD. 30s age, 0.25% spread, 12s decision span and strict UNKNOWN
remain. A hoped-for future price isn't current qualification. USD is valuation
only. A synthetic triangle can pass; tests don't establish such opportunities
exist on the account. Conditional estimates aren't completed profits.

The journal stores CID/price/size/version/reserve before POST. Ambiguous POST
locks that identity; absence from a read never permits another create retry.
Recovery checks exact CID/product/portfolio. Cancellation touches only known
owned order IDs. A cancellation acknowledgment retains source/partial proceeds
until exact terminal order/fill totals. Supported settlement requires explicit
size denomination, maker classification and native quote commission currency.
Unknown/third-asset fees, conflicting totals or corrections retain evidence and
locks without double credits. Outside activity consuming tracked inventory
pauses review rather than shrinking/relabeling the discrepancy. Available account
balance already excludes venue holds; holds aren't deducted twice.

Monotonic review and 120s acknowledgment-based child reconsideration never edit
accepted prices. Settings incompatibility or a qualifying market move requests
cancel/reconcile before replacement. STOP gates immediately and continues owned
order polling during stopped scanning/quote outages. Original attempts/expiry
are never expanded. Closing makes one bounded read/cancel pass, retaining any
unresolved locks. It cannot promise an exchange cancellation after shutdown.
Restarts block ON, reconcile to PAUSED, then require explicit Start; no reseed.

## Fee-adjusted ASK and historical CSV evidence

For quote commission fraction `f`, BUY cost is `q*ASK*(1+f)`; SELL proceeds are
`q*limit*(1-f)`. A SELL retaining intended net quote price `p` needs
`ceil_to_tick(p/(1-f))`. These are cost benchmarks, not another fill calculator.
Canonical native receipts still own every intent and settlement.

At .030255 BTC/ETH with a hypothetical .5% quote fee, BUY cost/base is
.030406275 BTC; SELL limit retaining that net at a .000001 tick is .030408.
Neither 10% nor .0001% is that fee. The screenshot's center was last price, not
best ASK; its form displayed .90%, so an older .5% deduction can't set the
current rate. Maker BUY remains at BID, SELL at ASK. An unanswered clarification
is not treated as authorization for marketable/taker BUY execution.

The supplied statement's local native-note reconstruction gives
.005*.030268=.000151340 BTC gross; .0001505833 BTC received implies .0000007567
BTC / .5%. USD arithmetic is consistent. This derived historical deduction is
not an authenticated commission-currency field or a proven identifier join to
the screenshot. The actual CSV/IDs are excluded from Git/ZIP. Source fixtures
use synthetic IDs. CSV math reads bounded data without record/settings writes.

The handoff's A05 expected .990025 assumes successive net-output fees. SELL then
BUY with both fees paid in quote has unrounded factor `(1-f)/(1+f)` = `.995/1.005`,
with separate native dust. Canonical quote-debit arithmetic is retained instead
of forcing that incorrect expected number. Missing fee units are never guessed.

## Optional market data and manual research

`coincat_order_book.py` owns bounded Decimal L2 books. The pinned/published official
SDK schema establishes `l2_data`, snapshot/update, absolute `new_quantity` and
zero removal. A connection-channel sequence spans interleaved products; exact
duplicates are ignored, discontinuities invalidate and resnapshot. **Current
server sequencing/contract still needs connected verification**; SDK schema
inspection is not connected acceptance. The provider defaults OFF.

A fresh snapshot envelope timestamps current state even if individual unchanged
levels have old last-change times. Updates retain native event time. Heartbeat
RFC3339 envelope time proves liveness, never refreshes product age; diagnostic
`current_time` isn't parsed as price time. Missing heartbeat >5s, product age
>30s, malformed/crossed/nonfinite/oversized data, gap or disconnect blocks use.
New generations require a new snapshot; late old callbacks cannot repair it.
Bounds: 8MiB message, 16,384 levels/side/product, 65,536 updates/event, six products.
The pinned synchronous websocket receiver applies backpressure and processes
every delta before GUI coalescing. Five consecutive failures exhaust bounded
jitter/backoff. Proxy environments are refused, not bypassed by this transport.

Four ETH anchors plus two BTC crosses are scheduled; selected crosses can
replace a slot, and a 60s reconnect rotates the schedule. There is no claim of
seven synchronized books or expanded REST budgets: six native + one reference,
sixteen total, four workers, .2s spacing, six-second collection deadline.
Tk renders immutable views at ~5Hz. Red asks, spread and green bids show native
price/amount/total and depth bars. Cumulative sums go outward from best before
ask display reversal. Quote notional uses actual level prices; grouping bids
down/asks up never changes native evidence. REST fallback sizes are UNKNOWN.
No synthetic recent trade or personal fill is displayed as exchange evidence.

Both stream and sized research provider default OFF. The optional provider
replaces only this pass's <=6 scheduled books with healthy L2. It separately
requires explicit authenticated product fee denomination. **Ordinary Coinbase
responses may omit it; paper and REAL then HOLD with UNKNOWN even with live
block OFF.** Neither visible depth nor a CSV-derived fee bypasses this gate.

Manual Trade Lab has GET method references only. View-only scope, exact IDs,
<=7-day windows, page/deadline bounds, deduplication and stable before/after order
snapshots precede exact native analysis. Coverage, order state, native flow,
fee currency, maker/taker/post-only, ownership, acceptance time and account
reconciliation remain independent. Incomplete/canceled/partial observations and
corrections are retained separately. Creation-to-fill isn't accepted queue time.
Native flow doesn't establish historical account reconciliation or bot ownership.
No automatic calibration/settings update is enabled; one selected manual fill
proves no all-market fill probability. Prospective criteria must be frozen before
collecting results. Existing synthetic no-fill/adverse holdout cases are retained.

## Cleanup, privacy and rollback

Visible scenario mixer becomes Manual Trade Lab; new experiment registration
is retired from normal UI. Historical viewing, compatibility handlers, frozen
session IDs and financial libraries remain. Unreachable submission code was
removed. Cache cleanup reports/removes only source bytecode, not financial,
research, paper/live/manual data, imports, keys, locks or backups. Dependencies,
logo/icon and protected financial modules remain unchanged; legacy LiveLedger
class remains byte-identical despite the authorized broker adapter edit.

New private stores are `research_data/live_beta/active.sqlite3` and
`research_data/manual_trade_lab/observations.sqlite3`. Application identity,
size/digest checks and transactional revision guards reject wrong stores and
conflicting writes. No old financial or research migration is performed. The
REAL journal tracks native flow, **not tax/FIFO lots or full account cash flows**.

Eight diagnostics sections and monitor v3 use strict count/enum/boolean beta
projections. No quantities/settings/levels/IDs/private paths/raw errors are
exported. Heartbeats/exports use cached projections; monitor is GET-only. Missing
responses clear current claims; stale snapshots cannot claim a current live gate.

Rollback: STOP/block ON, await terminal owned reconciliation, close, preserve all
data/backups and restore the prior separate source installation. Old source
can't manage beta-owned orders. Inspect Coinbase and retain/reconcile this journal
before another session; never delete history to pretend exposure ended.

## Copyable discussion handoff

CoinCat v1.03beta replaces permanent LiveBlocked with an ON-at-boot bounded
maker gate. Deliberate OFF + applied limits + Start can place real orders without
per-trade approval. Proposed draft caps: .005 ETH, $5/order, one open, four
attempts, 30min. Global $.01 completed ETH-return floor; initial <=50% working
once, later <=50% owned source, 30s review/120s acknowledgment-based lifetime.
UNKNOWN fee/depth/FX/residue/profit still means HOLD. Public L2/manual GET importer
are optional/read-only; historical .5% CSV math is not universal fee authority.
Separate journals retain partials, uncertainty, corrections and cancellation
races; tax/FIFO data stays unchanged. Cloud checks aren't native Windows,
connected settlement, independent signoff or evidence of predictive profit.
Review exact commit/package hashes and remaining acceptance gaps.
