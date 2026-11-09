> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

# Inherited v100 research contract and pure API

Current v1.01 adds a separate opted-in shared paper controller; see
AUTO_PAPER_V1_01.md. The pure adaptive APIs and independent comparisons described
below retain their original boundaries. They do not become funded positions.

Source base: remote coincat-v95 checkpoint
40bdac5df0c29a9571acc5fe118dd4d8190bf54a, freshly fetched and matched. The clean
local environment originally contained an older source; no local changes were
overwritten. The owner explicitly requested a new clean v100 build and push,
superseding the attached handoff's older no-commit instruction. No execution,
environment publication or running-installation change was authorized.

## Inherited working behavior

The existing direct-ETH patient maker study remains the primary observation.
ETH-BTC uses SELL entry / BUY return in BTC per ETH. ADA/LINK/SOL-ETH use BUY
entry / SELL return. Each independent scenario compares the same working ETH
against HOLD; they cannot be added as concurrent allocations. Maker limits have
zero taker slippage; taker benchmarks use the manually selected stress. Exit
targets are not forecasts. Touch/cross/high is never a fill.

Only ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC and ADA-BTC are admitted
for research/history. ETH, BTC, ADA, LINK and SOL are the only graph assets.
Every product requires authenticated listing, online SPOT status, explicit
tradability, valid native rules and no exclusions/restrictions. No synthetic
inverse product or stablecoin bridge. Four ETH anchors and two rotating BTC
cross-pairs retain six research / 16 total books, four workers, 0.2s spacing,
six-second collection deadline and provider backoff. Seven books across two
passes are not one synchronized decision.

Account maker/taker rates must be fresh, exact and supported: capture not in the
future, TTL two hours, hourly due refresh and failed retry at least ten minutes.
No fixed/zero-fee fallback or subscription rebate is inferred. Quote fee debit is
an explicitly unverified scenario in the app; product exceptions remain unknown.
Quotes retain 30s age, 0.25% spread and 12s per-decision span. Maker setup identity
binds relevant ETH funding/rules/controls, not unrelated balances or catalog
statistics. Gaps retain original expiry and never create gap touches. Existing
monotonic bounded retries, STOP and late-result rejection remain unchanged.

## Added pure conditional tools

app/coincat_adaptive_eth.py imports no client, broker, database or network API.
All values are caller-supplied and all state is bounded RAM. Canonical
research_order owns native sizing, fees once, minima/maxima, increments, stress
and optional depth walks. No second receipt calculator was added.

- candidate_graph(source, catalog=..., rules=...): deterministic HOLD plus listed
  one-step BUY/SELL directions, at most 16 actions with explicit truncation.
- closed_routes(...): secondary research utility, at most three legs / 32 routes,
  simple intermediate assets. The full seven-market graph has four two-leg
  reversals and six triangles. This does not re-enable a cycle strategy.
- Frame(at, catalog, rules, quotes, tier, ...): caller-independent frozen copies
  of one observation; exact prices and ticks. Optional depth and fee-unit
  evidence are keyed by (product, side) and bound to the quote timestamp.
- estimate_path(...): one conditional native wallet through at most three legs.
  It may return modeled arithmetic with explicit limitations. recoverable_eth
  remains None for missing sized depth, unsupported/unknown fee units, maker-fill
  uncertainty or non-ETH residue. Supplied evidence still cannot establish a fill.
- ResearchFunds.from_proposal(amount_eth=..., balances=..., balances_at=..., now=...,
  draft=..., excluded=...): applies the existing ETH funding/carve-out contract
  to one explicitly hypothetical slice. The direct constructor is for callers
  that already supplied an isolated hypothetical working slice, not account funds.
- reserve(reference, leg=..., quantity=..., frame=...): locks the whole source
  budget, including rounding residue, until a known no-fill or exact assumed fill.
  No BTC is available merely because ETH exists or a quoted entry crosses.
- assume_fill(..., classification='SIMULATED_ASSUMPTION', input_quantity=...,
  output_quantity=..., fee_quantity=..., fee_currency=...): requires the full exact
  frozen canonical receipt. Partial/uncertain events lock funds and earn nothing;
  resolving them is deliberately unsupported. Bounded event references prevent
  replay. No-fill releases only a known untouched reserve. No persistence/recovery.
- scoreboard(funds, frame, real_eth=None, real_eth_at=None, alert_pct=None): separates
  optional fresh real ETH, simulated coin inventory, conservative after-cost ETH,
  net versus original ETH HOLD and drawdown. Direct exits across every holding
  must be synchronized and sized; dust stays UNKNOWN. Fees are charged once per
  hypothetical exit. Real balances never alter paper earnings. Alerts are opt-in,
  review-only; no forced liquidation and no maximum-loss/recovery guarantee.
- ForwardStudy.freeze(...): freezes a conditional source slice already present
  in ResearchFunds, caller signal/uncertainty, explicit fill classification,
  proposed exit condition, cost assumptions and a caller-chosen 1s–72h horizon.
  Future SOL/ETH is unknown. Independent counterfactual cases are not concurrent
  paper allocations; freeze never credits or reserves a wallet, and their values
  must not be summed. Shared spending requires ResearchFunds reservations.
- ForwardStudy.observe(...): compares after-cost HOLD of that source slice and
  the conditional rotation at the same future observation. First observation
  at/after the horizon closes the experiment within a fixed 30s observation
  window; otherwise it is MISSED_HORIZON. Missing/unsynchronized evidence becomes
  UNKNOWN_AT_HORIZON, never replaced by a later favorable price. Partial/uncertain
  entries have no return. NO_FILL retains HOLD with forgone conditional opportunity
  separate. Adverse observed differences and underwater open cases stay visible.
  The horizon does not close a position. Summary always says NO DEMONSTRATED EDGE.

The original published v100.0 GUI called observation_summary only. The local
journal candidate also observes explicitly registered cases using the same
returned books; it creates no experiments or paper trades automatically. Manual
registration requires explicit user values; see PROSPECTIVE_JOURNAL.md. The
Research notes panel and eight-section diagnostics/local monitor share the same
strict quantity-free summary. No synthetic evidence is injected into the UI.
The optional real-account scoreboard input has no connected adapter in this patch.

## Offline worked example and acceptance

Run Python 3.11 tools/ADAPTIVE_ETH_DEMO.py --synthetic for explicit toy evidence,
an exact assumed ETH→BTC event and an adverse BTC→SOL conditional comparison.
The fee-zero toy fixture is deliberate arithmetic, not a live fee fallback or
Coinbase One assumption. No account, network or dataset is opened by the demo.

New tests cover directions/scope/permissions, source budgets, fees once, maker
orientation, sizes/ticks/stress/depth, dust/unknowns, fresh versus deferred quotes,
exact simulated sequential fills, reservations/no-fill/uncertain/replay, adverse
forward/non-events/late observations, underwater exposure, review-only alerts,
strict redaction and monitor v2. All original financial compatibility assertions
are retained. Baseline: 229 tests personally rerun before changes; current counts
and runtime are in VERIFICATION.txt.

Future production reservation, actual partial fills, fee/rebate reconciliation,
idempotent order lifecycle, cashflows, restart/unknown-outcome recovery, prediction
validation and any execution require separate design and explicit authorization.
