# CoinCat v100.0 seven-market spot workspace

The owner requested a Coinbase-style chart/control/activity arrangement and named
exactly seven spot products: ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC,
ADA-BTC. The owner clarified that ETH is currently the only funding source and
that BTC is an ETH companion. The current owner request authorizes the v100 source
build and push; it does not authorize purchases, transfers, account changes,
execution enablement or deployment to the running PC.

## What the layout does

The dark workspace keeps the stored-quote candlestick chart on the left and the
ETH research controls on the right. Native chart units match the actual product:
ETH-BTC is BTC per ETH; ADA/LINK/SOL-BTC are BTC per companion coin. The research
comparison still measures outcomes in ETH. Candle history is sampled midpoint
OHLC, with no fabricated trades, volume, gaps or earlier history.

Research, Watchlist, Open orders and Portfolio sit below the chart. Selecting a
watch row changes only the chart. Manual mixer, Allocation and Research notes
remain separate top-level tabs. The same six exact manual faders remain; the
right-hand amount/target/offset fields share those controls. Editing still
requires Apply. Scrollable right controls, pointer/focus hover, STOP, local
monitor and larger transparent CoinCat logo remain available.

The Open orders view says CoinCat orders are zero because submission is blocked,
and explicitly says the Coinbase account order feed is not loaded. It does not
assert that the owner has no manual orders. In an eventual execution-capable
release, accepted resting orders normally appear on Coinbase for the same
portfolio and matching filters. Filled orders move to history. A research setup,
quote touch or hypothetical completion never appears as an exchange order.

## Funding and independent work

ETH is the sole initial funding source. No LINK, ADA, SOL or BTC purchase is
needed to test ETH-funded paper entry arithmetic. Four direct ETH companions
are now possible because the owner explicitly named BTC plus ADA/LINK/SOL. This
supersedes the earlier three-companion UI limit without changing book limits.

Each direct ETH scenario compares exactly the same ETH amount against HOLD,
independently. These are comparisons, not simultaneous four-way allocations.
Their scenario profits must never be added together. There is no new shared-fund
execution allocator, balance reservation or live order worker in this patch.

BTC cross-pairs are observation-only. A future buy on ADA-BTC needs usable BTC;
selling ADA-BTC needs usable ADA. Acquiring a companion through ETH first could
provide that inventory only after a real fill and settlement evidence. This
read-only app cannot assume a quote touch filled, credit inventory from it, or
spend the same ETH/BTC in several orders. A future concurrent trading engine
requires a single funding/reservation coordinator and verified fill/fee state.
The unconditional first-statement LiveBlocked remains unchanged.

## Exact observation scope and collection

Authenticated product metadata is filtered to the seven names before active
research admission. The existing paginated account catalog can contain other
product metadata; those products never receive research quote requests, are not
journaled by this flow and are not learned from. Missing eligibility, view_only,
restricted products, bad rules and asset exclusions still reject a product.
No inverse ID, alternate listing, bridge or replacement is synthesized.

The GUI applies the full approved observation mode alongside its manually chosen
ETH comparisons. Four eligible ETH books are anchors. Up to two of the three
BTC cross-pairs rotate through the remaining slots, covering all seven in two
successful passes when eligible. This is concurrent monitoring over time, not a
claim that seven quotes were simultaneously synchronized. At most six research
books/16 total, 0.2-second spacing, deadlines/backoff and 30s/0.25%/12s guards
remain unchanged. Deferred books retain their timestamp and deferred label.
Cached cross-pair books never supply a new ETH entry decision.

Cancelled or failed passes do not advance the rotation or publish their staged
cache. Only approved actually returned books are journaled. Pure secondary
receipt/calculator capabilities remain compatible; they do not expand active
scope or re-enable the old immediate-cycle strategy.

The chart's SQL reads are restricted to the approved IDs. Other historical data
is preserved without being displayed or read as a price series. No schema,
financial record, private data, existing history or backup is removed.

## Basic counters and reference value

The right panel shows published research scans, hypothetical setup count, verified
bot fills (zero) and bot orders (zero). It never turns an observation or price
touch into a completed swap. Coinbase manual orders are not counted by this app.

ETH held comes from the fresh account snapshot. Watched-basket value includes
reported ETH/BTC/ADA/LINK/SOL, using fresh direct ETH midpoint references, before
exit fees. BTC uses the actual ETH-BTC inverse rate for ETH measurement. No
companion balance is needed when ETH is the only positive watched holding.

The first fresh complete basket establishes a RAM display baseline. Its change
includes price moves, deposits, withdrawals and manual trading, and is explicitly
unadjusted for those flows. It is not verified bot profit. Reset view baseline
changes only this display reference. Stale/missing/wide/future quotes or stale
account data keep the basket unpriced. Holdings outside the watch network, such
as VET/VTHO/USD, are listed as unvalued; the app does not fetch additional markets
to manufacture a complete whole-portfolio ETH total.

The eight-section export adds the approved/deferred scope and observation roles,
without native prices/amounts or reference-value quantities. The local helper
accepts up to four direct ETH setup rows and keeps its quantity-free whitelist.
No private funding or valuation numbers enter helper snapshots.

## Validation and remaining acceptance

New tests cover the exact scope and two-pass rotation, authentication/exclusion
gates, ETH-only four-entry modeling without fake inventory, cancelled staging,
native chart units and off-scope SQL rejection, reference-price/deposit changes,
unpriced/stale values, minimum layout, chart/baseline independence and diagnostic
redaction. Existing transport, receipt, ledger, recovery, backup/import, helper,
STOP, chart and Windows compatibility regressions remain.

Native Windows display/DPI, connected eligible markets/fees and Tailscale remain
local acceptance steps. No actual order, fill, realized gain, connected private
read, deployment or environment publication is established by Linux fixtures.

## v100 additions

The transparent RGBA banner now occupies the upper-header space to the right of
the title and connection controls. It scales with the available width; no small
old banner is loaded. The chart and seven-market workspace remain below.
Research notes adds the read-only Adaptive ETH Research summary. Scanner,
diagnostics and monitor share one bounded quantity-free projection; no new
polling source, paper funding or prediction fitting is enabled.
