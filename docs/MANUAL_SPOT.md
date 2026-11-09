> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

Current v1.04 uses tabs-only market selection, 1h chart defaults and a private
portfolio total/holdings hover with an inset logo. See
[V1_04_HEADER_PORTFOLIO.md](V1_04_HEADER_PORTFOLIO.md). The foundation guide below
retains historical UI descriptions; execution safeguards remain applicable.

# Manual Spot follow-up — v1.03beta

The previous default sent every order through a strategy controller's completed
rotation qualification. Missing future exit/fee/depth evidence held all entries.
There was no direct manual ticket. The new default addresses that integration
gap with a separate, operator-driven client and leaves automatic strategies OFF.

`coincat_launcher` launches `coincat_spot_app`. It keeps the existing verified
data import, Windows DPAPI key vault and single-instance lock. It does not
initialize the old scanner, paper controller, live coordinator, financial ledger
or WebSocket stream. Historical modules and records remain for compatibility;
they are not additional authorities running behind the new ticket.

## Native reads and display

The seven approved products are ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC,
SOL-BTC and ADA-BTC. Each has a tab with a chart, book and ticket. The dropdown
selects a tab; its star stores only a local favorite. A shared worker serializes
API operations. Selected-market REST refreshes occur about every eight seconds;
exchange trade candles refresh about once a minute. Candles are real exchange
OHLC/volume observations, never quote-made candles or fill evidence. Book
grouping and base/quote notional affect display only. No exchange queue or fill
is inferred from visible liquidity or a price touch.

Reads share the existing process GET pace and have a sixteen-call/25-second
admission budget, with the SDK's finite per-request timeout. No new unbounded
thread pool is introduced. Native books use receipt freshness and validate an
exchange timestamp when present. ETH-USD is read solely for a spending-cap
valuation; it cannot become a ticket or candle/history trading product.

## Explicit real orders

Every launch sets the manual create gate ON. Switching OFF does not submit.
Only an explicit Buy/Sell button invokes `ManualExecution.submit` with a new
click/client-order identity. Tickets are LIMIT GTC only. Post Only OFF permits
marketable limit orders, including BUY at ASK. Post Only ON rejects a crossing
price. There are no market/IOC calls, automatic replacements or taker fallbacks.

Preflight refreshes permissions (view+trade, no transfer), portfolio, native
product rules, selected book, account available balances, maker/taker rates and
cap references. It validates exact increments and native size/value minimums
and maximums. Available already excludes venue holds. The default 2% buffer is
applied conservatively to source funds and risk caps; it is not a fee forecast.
A fresh authenticated native limit preview must accept the exact base size and
estimated commission within the buffer. Preview never creates fills.

The user-entered amount is the source commitment. No ETH seed, allocation plan,
profit target, predicted exit, sized future liquidity or historical fee unit is
needed. Cap valuation uses the greater of sell limit and current ask so a low
SELL limit cannot hide the source's market value. The session's cumulative
ETH-equivalent commitment counts actual filled portions and unresolved orders;
only a terminal verified unfilled portion releases its conservative commitment.
Each dispatched submission consumes a slot, even if rejected/canceled.

After preview, fresh checks and STOP check, the journal durably records immutable
ticket fields and identity before one create call. The SDK 1.8.4 requests adapter
has zero retries; a replaced retry-enabled adapter is refused. Ambiguous POSTs
retain their identity and lock creation. Recovery searches bounded scoped order
history for the exact client ID and verifies product, side, scope and immutable
configuration. Absence in the bounded search does not authorize another create.

Cancellation checks the remote owned identity before sending, then reads order
and all reported fills. A cancel acknowledgment alone is not terminal proof.
Partial and racing fills must reconcile exact base/gross/commission scalar
totals and reported coverage. Missing fee currency can leave economics UNKNOWN
while quantity is established. This does not invent a wallet credit or profit.
Cancel & refresh uses original size minus confirmed fills, fresh BID for a
post-only BUY, otherwise fresh ASK, and a once-only parent link. No replacement
is sent until another click. Reusing a consumed replacement parent is rejected.

Reblock/expiry prevents new creates and requests owned-order cancellation.
Shutdown waits for the current bounded worker and makes one bounded reconciliation
pass. Unresolved state survives shutdown. A completed explicit New session
archives the entire manual database and preserves its limits; a restart alone
does not reset caps, expiry or attempt count. An older unresolved automatic live
journal must be reconciled before a new manual session can spend capital.

## CSV/native settlement

The statement reconstruction already established native arithmetic for the
owner's small ETH-BTC sale. This follow-up connects that evidence to saved API
observations. A complete order's fills must each have exactly one matching CSV
row by product, side, normalized native quantity, exact price and UTC second.
Derived native deduction must equal the API commission scalar, and aggregate
quantities/gross/fees must match. Duplicate rows, reused rows, absent timestamps,
conflicting fee assets or mismatched totals remain unresolved.

A successful report revision is `STATEMENT_CORROBORATED_NATIVE_FLOW`, explicitly
`NOT_PROVEN_FIELD_MATCH_ONLY` for identifiers. Raw API fills, unknown API fee
currencies, account reconciliation UNKNOWN and prior report revisions stay
intact. This is corroboration of that settlement arithmetic, not a universal fee
rate, an API-reported commission denomination or tax/account reconciliation.

## Acceptance and records

Follow [START_HERE](../START_HERE.md) for local manual placement/cancel/fill tests.
Offline tests prohibit HTTP/WebSocket and use fake SDK events. They cover all
fourteen directions, maker/marketable limits, native validation, caps, partial
fills, cancellation races, unknown POST/restart recovery, remaining-size drafts,
STOP/shutdown, CSV ambiguity, actual Tk controls and redacted exports. Native
Windows/DPAPI, actual Coinbase preview/create contracts and connected settlement
still require local evidence. No actual order is placed in this cloud session.

Financial/FIFO/tax/key/import/lock modules and original datasets are preserved.
Manual identities live at `research_data/spot_manual/active.sqlite3`; completed
journals are retained beside it. Historical read-only observations retain their
existing store. Eight-section diagnostics and the strict optional monitor-v3
`manual_execution` extension export controlled states/counts only. The monitor
remains GET-only and cannot place, cancel, reprice or update the app.

The history-reporting follow-up copies the saved read-only history summary
into `beta.manual` for the manual workspace as well as archived clients.
Diagnostics section 4 and the monitor execution panel label the current
CoinCat session. Section 6 and a visible Imported Coinbase history panel show
historical order/filled/partial/canceled/native-flow/unresolved-settlement
counts. Missing fee denomination does not erase a reported filled order.
API-supported or uniquely CSV-corroborated native flows count as known
arithmetic; account reconciliation remains UNKNOWN. No imported record becomes
an execution, a fundable position, a new order or a changed fee setting.
