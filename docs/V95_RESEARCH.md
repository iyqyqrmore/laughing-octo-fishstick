# CoinCat v95.0 — read-only study and evidence contract

Owner-approved hypothesis: patient post-only entry from ETH into a manually chosen
coin, followed by a later proposed post-only exit into ETH. The objective is more
ETH after costs versus HOLD of exactly the initial ETH allocation. This can fail:
no fill, partial fill, adverse selection, fees, native dust, price decline and long
coin exposure can all dominate. There is no promise of positive returns.

## Actual market and fee evidence

**Eligible pairs on this account: NOT VERIFIED in cloud.** BTC, SOL and ADA are
examples only, not selections. Connect locally: the authenticated paginated SPOT
catalog must contain an actual direct ETH product with online status, explicitly
false view_only, no restricted flags, consistent product/currency identity and
valid base/quote/price increments and minima/maxima. No missing flag is permission.
The inherited registry excludes limit-only/post-only-only restricted products;
this conservative preview does not broaden that registry. Use fewer companions
if fewer qualify. If none qualify, report NO QUALIFIED EVIDENCE and make a separate
owner decision. A missing filtered product does not prove a specific regional or
listing restriction. No synthetic inverse product or fiat/stablecoin bridge exists.

**Account fee tier: NOT VERIFIED here.** The existing optional authenticated GET
transaction_summary(product_type='SPOT') refreshes on connection/account refresh
when due (hourly; failed retry ≥10 minutes). Cache TTL two hours; future-dated
fees are now invalid. Both maker and taker estimates carry capture time. No fixed
0.5%/0.9% fallback. Product-specific exceptions and actual fee currency remain
UNKNOWN. The canonical receipt models quote-currency debit once as an explicit
scenario; it is not proof of the eventual fee debit. Negative maker rebates are
unsupported by the canonical receipt and block this preview rather than being
invented. UI fee fractions are converted to percentages; diagnostics retain the
fraction units. No previews, create/edit/cancel orders or transfer APIs are called.

## Two separate calculations

Immediate benchmark uses actual bid/ask, estimated authenticated taker rates and
the manual slippage stress (default 15 bps per leg). It is usually negative and is
not an arbitrage recommendation. Unpriced inputs are not economic losses.

Maker entry rests at bid minus the manual offset for an ALT-ETH BUY; an actual
ETH-ALT product uses a SELL above bid, at ask plus offset. Prices round away from
crossing, to the verified tick. The exit target solves the owner's requested net
ETH percentage (default 0.25% scenario), including entry and exit maker estimates,
both legs' size limits/increments, initial unspent ETH and native dust. BUY return
rounding also reserves estimated fees inside its native budget. No taker-slippage
stress is charged to a resting maker hypothesis. Adverse selection is represented
as uncertain fills and observed adverse movement, not an invented market fee.

The future exit is a target, not a forecast or an observed valid exit decision.
Hover details show actual product-oriented limit units and a separate ETH-per-coin
quote. The pure offline completion helper checks entry and exit post-only eligibility
at their respective valid snapshots. A later marketable target is not a valid new
post-only order. Entry and exit intentionally may be hours apart; each decision
retains its own 30s quote/spread checks instead of a cross-time 12s gate.

Each companion is an independent scenario against the same initial ETH. Results
must never be summed as simultaneous deployments. Non-ETH dust remains explicit:
ETH subtotal is not full recoverable ETH when residue remains. Full-fill results
are conditional scenarios under assumed fee currency; no financial return is
credited, even if scenario arithmetic is positive. No-fill retains all initial
ETH. Partial/unknown fill quantity and return remain UNKNOWN. Worst-case residual
ETH assumes the entire acquired-coin exposure can be lost; a real holding could
outlast the selected observation horizon.

## Observation model and uncertainty

At most one frozen setup per selected product, at most three active setups. A
valid setup binds its entry time, original quote, rules, rates, amount, target and
controls. Repeated scans do not create independent setups. Later entry touch is
PARTIAL_OR_UNCERTAIN_FILL, never HYPOTHETICAL_FULL_FILL. Later target crossing is
also uncertain. No queue position, traded volume, depth, real partial fill or
cancellation/repricing outcome is evidenced by REST BBO alone. Counts never claim
actual executions. The offline helper separately supports NO_FILL, PARTIAL_OR_UNCERTAIN_FILL,
HYPOTHETICAL_FULL_FILL, UNPRICED, CANCELLED_OR_EXPIRED and UNVERIFIED scenarios.

Changes to relevant ETH funding, applied controls or a selected market's critical
rules invalidate the affected hypothesis with an explicit reason. Unrelated
asset/draft/exclusion changes and catalog price/volume statistics do not reset
ETH-only research. Verified fee-rate changes close/restart with a reason; missing
fees and missing/stale/wide/invalid quotes pause the original setup through its
original expiry. The first recovered quote does not infer touches across a gap. Expiry records CANCELLED_OR_EXPIRED; a later
scan can begin a new setup. All changes are RAM-only. STOP stages no completed
research result and rejects stale Tk generations; changing controls or unapplied
allocation fields requires a new Apply action. Public quotes use the existing
canonical research journal; hypotheses/counts do not persist across restart.

Within a quote decision: ≤30s age, ≤0.25% spread, ≤12s span. At most three selected
books share the existing collector, below the unchanged six research/16 total
ceilings. Existing four-worker maximum, 0.2s spacing, six-second collection window,
slow-quote rejection and Retry-After/backoff remain. No parallel request loop or
old endpoint experiment runs. REST request timing is local evidence, not verified
exchange-event synchronization. Bounded sequence-verified L2 data is a possible
future improvement, not part of this increment.

## Funding and records

The owner requested full available ETH as the modeling default. The GUI now uses
the full ETH working proposal after manual/protected/excluded carve-outs; before
connection it remains unset/zero. Custom amounts are preserved until Reset. The
scanner still requires the amount to fit a fresh valid ETH working draft, with
no fallback to other assets or unreconciled execution funding. The editor's owner checkbox does
not establish settlement, open-order holds, external flows or cashflow-adjusted
basis. All GUI funding stays UNRECONCILED / RESEARCH ONLY and execution-ineligible.
The reserve proposal calculator remains a secondary pure source capability,
without earmarking, harvest, high-watermark journal or earned-balance inference.
Protected broker/FIFO/state/importer/lot/key modules are byte-identical to the
checkpoint. No running Windows installation or private records are changed.

## Pre-registered observational trial

After offline and native local checks, use 48–72h for initial coverage; optionally
2–4 weeks across independent regimes. Choose companions/amount/target/offset/wait
before running. Export before closing; record every manual baseline change as a
new run. Do not optimize controls to one volatile day.

Record catalog eligibility and missing markets, actual fee evidence, quote failures
and integrity, distinct setups versus repeated reviews, entry/target touches,
expiry/uncertain outcomes, required move, time waiting, adverse move and exposure,
dust, negative taker baselines and missed opportunity costs. Conditional full-fill
ETH scenarios do not become completed after-fee outcomes without evidence of both
fills. REST-only qualified completed fills may remain zero indefinitely. Zero
positives or NO QUALIFIED EVIDENCE is valid evidence, never a test failure.

Stop if no eligible pairs exist, minima/fees dominate sizes, quote integrity is
inadequate or a defensible fill model is unavailable. Do not relax guards or switch
routing to manufacture positive results. Export quantity-free v95 diagnostics;
private detailed values remain local. No cloud authenticated account run is claimed.

## Stored-quote candlestick view

Chart history reads the same canonical market_quotes table, in SQLite read-only
mode with query_only enabled. It performs no network request, schema change or
financial write. Candles aggregate recorded bid/ask midpoints into display-only
OHLC (including inverse ETH-base products, normalized to ETH per coin). These
are sampled quote candles, not executed-trade/exchange OHLC or fill evidence.
SQLite REAL chart coordinates never become native strategy prices.

Time controls span seconds/minutes/hours/days and calendar UTC months/years.
Range controls browse a minute through a year or all actual retained history;
empty intervals remain gaps, future-dated samples are excluded and earlier
history is never invented/downloaded. All stored uses the recorded oldest/newest
bounds. Requests are cancellable on a single background reader, use a 20-second
SQL progress deadline, and fit at most 500 candles with explicit interval
coarsening. Very large/busy reads request a shorter range instead of returning
an unlabeled partial chart. Live chart refresh is throttled to at most once per
10 seconds and creates no exchange load. STOP rejects queued chart generations;
manual history browsing remains possible while research is stopped.

The chart is above Coins & research. Faders have a separate Manual mixer tab.
Chart product selection does not approve a companion or change funds, hypotheses
or scanner inputs. Diagnostics export only chart coverage/interval/basis metadata,
not native balances or full price-series payloads. Existing research-store quota
still pauses new recording at its limit; no retention deletion was introduced.

## Overnight continuity hotfix

Per-market versioned research identity uses canonical typed product/rule fields,
effective applied controls and the exact ETH funding slice. It does not use the
whole-account allocation digests, quote prices, chart controls or changing catalog
statistics. The unchanged full allocation/reconciliation contract is still shown
separately; ETH-only research applies that same contract to the ETH slice and
never grants execution eligibility. Non-ETH drafts cannot provide ETH funding.
ETH edits and actual ETH funding changes require explicit Apply again. Unrelated
editor changes leave the applied ETH plan and its clock intact.

A quote gap is SETUP_ACTIVE_UNPRICED, not a new setup. Original entry/expiry,
prior observed uncertainty and assumptions remain frozen. Gap episodes, reasons,
resumptions, invalidations and expiries are counted separately; repeated unpriced
polls do not count as distinct episodes. At most three setups and 128 public
lifecycle events remain in RAM; dropped-history count is exported. First recovery
quotes establish a new observation boundary and do not infer gap touches. Missing
or stale fees never create current return/fill claims. Realized profit remains
unverified and no hypothetical fill is posted to financial records.

The connection controller exposes RUNNING, RETRYING, PAUSED_NEEDS_ATTENTION and
STOPPED. Transient read failures retry after 10/20/40/80/160 seconds, at most five
attempts after the initial failure, on a monotonic clock. Longer Retry-After and
the existing public budget win. Fee-provider failures preserve its existing
at-least-600-second retry interval; a deferred fee refresh cannot masquerade as a
new successful response. Authentication/permission errors, malformed settings,
local SQLite failures and exhausted retries require manual attention. Only one
read job can run; no collector/pool/GET-cap increase exists. Reconnection refreshes
account permissions, balances and product eligibility before pricing again.

Operation stage/class/status are controlled metadata: permissions, balances,
catalog, fee tier, public quote or local public quote store. No raw exception
message, account ID, URL, secret or private path is retained in public failures.
No current successful result is published for a fully failed quote collection.
Partially usable collections preserve explicit per-market gaps; permission denial
pauses even when another book was returned. Account refresh and observer changes
are staged; STOP checks occur between read stages and around public journaling,
which rolls back a cancelled insert. GUI generation guards discard late results.
STOP cancels pending retries; explicit connect can recover without starting
research, and selected funding changes still require Apply.

Last-good observations are kept separately from live validity. Every second, the
GUI labels aged rows STALE_LAST_OBSERVATION and shows current retry state. Exports
retain original quote_age_s and fee-fresh-then evidence, adding scan/account ages,
per-product export-time age/state and fee validity using the established two-hour
TTL. The eight-section export makes no network calls or financial writes.
