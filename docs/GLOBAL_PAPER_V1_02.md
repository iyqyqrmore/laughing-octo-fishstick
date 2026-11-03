# CoinCat v1.02 — global paper policy and discussion handoff

This source increment implements the owner's global settings request on top of
published v1.01 bba4dfea67b45e6f4eff7f15b7ba4398ab486a08. It does not install on
the Windows PC, change an account or authorize live execution. The current BBO
scanner cannot supply all required valuation evidence; strict global admission
therefore normally HOLDs with UNKNOWN and zero new orders. Do not mistake that
gate for a hung scanner or relax it to produce activity.

## Applied defaults

| Setting | Default / constraint |
|---|---|
| Minimum net completed ETH-return profit | $0.01 USD-equivalent; whole cents ≥$0.01 |
| Presets | $0.01 / $0.05 / $0.10 / $0.25 / $0.50 / $1.00 |
| Initial paper allocation | 50% of fresh working ETH after carve-outs, once |
| Subsequent source amount | Up to 50% of available, unreserved source, then native/session caps |
| Order type | Limit + Post Only; no market/taker/IOC fallback |
| Review / reconsideration | 30s / 120s |
| Minimum rest / movement review | 30s from acceptance / greater of 10bps or two ticks |
| Markets | ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC, ADA-BTC |
| Directions / wallet | Fourteen directions; one shared paper wallet |
| Fees / membership | Fresh authenticated account maker rate + declared stress, within ceiling; Basic gives no assumed rebate |
| Operational protections | One open order, sixteen total order slots, 24h original horizon |
| AI Lab | Passive observations only; cannot apply global settings |

The owner explicitly selected the initial slice once, without double-halving,
and strict UNKNOWN blocking even at startup. A new global session does not
force the legacy ETH→BTC kickoff or bypass its profit gate. All eligible ETH
directions are considered deterministically under the same floor. Initially
there is only simulated ETH; BTC/SOL/ADA/LINK balances are never copied from the
account into the paper wallet. A custom amount must fit the approved initial
working percentage. Initial funding/percentage remains frozen for that session.

Later amounts are min(available × applied source percentage, native cap,
remaining campaign budget). The percentage applies to available inventory,
not to the cap itself. A cap is never a credit. Native increments round down;
minimums never increase size. Pending, unknown and partial proceeds cannot
fund another order. Profit-only Apply changes only the minimum, even if risk
or timing fields contain separate unapplied edits.

## Qualification and result semantics

Net ETH = conservatively valued ETH return − original simulated ETH allocation.
Net USD = net ETH × approved fresh ETH-USD reference (bid for gains, ask for
losses). Entry cost attribution uses the same canonical native fill receipts,
including entry fees once. There is no alternate financial receipt calculator
or real tax-lot change. The native exit receipt includes its own fee once,
native rounding and minimums. Non-ETH residue without conservative valuation
blocks qualification rather than disappearing from the calculation.

Admission requires actual approved pair/direction/rules/permissions/exclusions,
fresh account rates, matched supported fee units, declared sized depth at the
matching native observation, valid precision and synchronized exits to ETH.
All dependencies retain 30s age, 0.25% spread and 12s decision-span limits. USD
must be exactly ETH-USD from COINBASE_PUBLIC_REST_BEST_BID_ASK, with no manual,
USDC, stale, wide or future substitute. One extra public reference GET shares
the existing four-worker / 0.2s spacing / six-second collector / sixteen-total
request budget. Six native books remain the research maximum; BTC crosses
still rotate. USD is absent from the trading graph, catalog, chart, native
history and funding. A failed USD request leaves native observations usable
but USD qualification UNKNOWN.

For a non-ETH output, a conservative sized exit benchmark uses canonical
taker-stress valuation receipts at current synchronized prices, with a rate
no lower than the maker planning ceiling. This is a valuation stress test,
**never an executed taker fallback**. All dispatched intents remain maker-only.
Current independent valid exit paths can be compared; future favorable prices
are never searched. A modeled required return price is a target calculation,
not proof that the future price or fill will occur.

CONDITIONAL_QUALIFIED is a hypothetical admission estimate. It is not a completed
rotation, actual profit, exchange fill or calibrated forecast. Entry depth also
does not prove maker execution. The provider retains explicit latency, sustained
strict penetration, synthetic queue depletion, seeded gates, partials and
non-fills; touching a price is insufficient. Quote currency fees in the venue
are declared simulation assumptions and do not establish verified exchange fee
units. Normal scanning currently has no sized-depth/fee-unit provider, so these
required inputs remain UNKNOWN and block new global entries.

Only a terminal FILLED/CANCELED order returning native ETH can produce a
completed **ETH-return slice** report. Its original attributed allocation and
actual declared native fees determine its result. A partly filled canceled
return is only that settled slice; the remaining inventory, open losses and
fees stay in the shared portfolio. An intermediate BTC/SOL gain is never a
completed ETH profit. Small partials can finish below the minimum even if the
whole conditional order qualified; they are recorded NOT_MET, never hidden.
This describes a result, not a guarantee that every execution achieves a floor.

The retained AUTO_PAPER_HOLDOUT.py harness exercises the historical patient/
short-lived policies named by its --policy argument. Its toy trades are not a
v1.02 global-floor performance result. RUN_PAPER_REPLAY is likewise a declared
lifecycle example, not a profitable strategy trial. The global tests use
explicitly declared depth/fee-unit/reference fixtures to exercise qualified
branches; they do not claim the normal scanner supplies those inputs.

The first completion observation permanently records MET, NOT_MET or UNKNOWN
against that order's pinned target/version. It needs fresh approved USD within
30s of the last fill, with a 12s dependency span. Missing/late FX stays UNKNOWN;
a later favorable price cannot repaint the result. Outcomes are append-only.
Whole-wallet midpoint change and conservative recoverable ETH vs original HOLD
remain separate. Unspent assets, open exposure, missed fills, fee gaps and
unknown exit values stay visible. Actual profit is always NOT_ESTABLISHED.

## Versions, replacement and restart

Apply appends a SHA256-identified settings revision, maximum 64 per session.
The native wallet, limits, orders, fills and original funding do not change.
Unchanged Apply is idempotent. Every new global intent pins the latest version
and its conditional evidence; core admission rechecks it in the reservation
transaction, preventing a stale UI candidate from bypassing the gate.

Resting orders retain their original price, expiry, version and evidence.
At the next valid review, a wholly unfilled order can be retained only if its
existing fixed price/reservation still meets the new policy. Otherwise request
cancel and reconcile before a fresh candidate can replace it. Partials are
canceled for reconciliation; the known fill and its fees remain. Repricing is
cancel/ack/new-intent, never a silent edit. No replacement can reuse reserved
funds, exceed remaining campaign source or renew the original campaign/session
deadline. Every child uses an existing order slot. Exhaustion pauses rather
than raising limits. Unknown placement/cancellation outcomes remain locked.

Pause/STOP do not liquidate assets or assert a cancellation acknowledgment.
Previously determined explicit fills may still settle. Generation checks
reject late GUI scan results. Saved opt-in never resumes; restart requires exact
paper reconciliation then an explicit Start from PAUSED. Old v1.01 sessions
retain their exact frozen base configuration; apply globals explicitly before
resuming them in the v1.02 interface. No second seed is credited. New session
retains the previous database and starts a separate baseline after new Apply
and opt-in. Individual session results must not be pooled as funded capital.

## Interface and retained-code audit

Auto Trader opens by default: global target/presets, applied summary, opt-in,
Start/Pause/STOP/reconcile/history, shared wallet, current order bid/ask vs limit,
resting age/review reason, completed-slice result and whole-wallet HOLD metrics.
Trading Settings groups the global source/timing controls, first funding slice
and frozen session protections. Per-market bid/ask and both directional views
remain inspectable; sized book/queue fields explicitly say UNKNOWN.

Research Archive holds ETH Growth, Legacy scenario mixer, AI Lab / notes and
legacy paper settings. The duplicated per-direction target/source forms were
removed from the main trader flow and centralized global settings govern new
global intents. The older controls/modules still serve frozen configurations,
diagnostics, prior records and offline financial compatibility; deleting them
would break those contracts. No financial module, tax record, native receipt,
historical identifier or private dataset was deleted. The logo/icon and twelve
locked dependencies are unchanged. No new dependency is required.

Diagnostics retain eight quantity-free sections. Monitor v3 gains only safe
policy/version/completed/qualifying counts; old exact v1.01 optional paper
projections are accepted and extra/partial schema fields are rejected. No
profit target, percentage, native amount, reference, receipt, signal, ID, private
path or token enters public snapshots. There is no command/update channel.

## Windows trial and discussion handoff

Follow START_HERE.md: separate source/data folder, setup, full verifier, finite
offline replay, actual v1.02 UI/STOP/restart/monitor checks, then 60–120 minutes
supervised read-only observation. Prior native verification took about 22
minutes; named progress and 30s heartbeats indicate activity, not success.
Inspect final errors/counts. Native Windows Python 3.11, DPAPI, DPI, locks and
connected catalog/fee availability remain separate from Linux fixture evidence.
VERIFICATION.txt records actual run counts and platforms. No GitHub Actions or
native pass is inferred from source hashes or Linux tests.

Copyable discussion context:

> CoinCat v1.02 has one versioned global $0.01 net USD-equivalent ETH-return
> floor, first working ETH slice 50% once, subsequent available source ≤50%,
> 30s review / 120s reconsideration across seven pairs/fourteen directions.
> All intents are Limit + Post Only. UNKNOWN blocks initial and later entries.
> Current BBO data lacks required sized exits/verified fee units, so normal
> sessions HOLD. Conditional estimates are not completed profit. Native terminal
> ETH-return slices, fees, partial results, remaining exposure and whole-wallet
> HOLD comparisons are retained. Settings cannot rewrite existing orders or
> erase losses; cancel/reconciliation precedes replacement. AI Lab is passive.
> The next evidence gap is a supported conservative valuation-data provider,
> followed by predeclared forward policy evaluation against HOLD after costs.
> Live submission remains unconditionally blocked. No live pilot is authorized.

Independent objections remain: one cent may be immaterial relative to model,
slippage, subscription and valuation uncertainty; a 50% source cap is substantial
exposure and says nothing about edge; short lifetimes reset queue position and
can increase missed fills; canceling unfilled orders does not sell held assets;
fees on partial fills remain; USD conversion of a tiny ETH delta is sensitive to
freshness and precision. A completed profitable slice can coexist with a losing
whole portfolio. An execution engine is not a profitable predictive strategy.
Do not optimize a threshold on the same sample used to claim improvement or
interpret explicit toy outcomes as evidence for a bounded live pilot.
