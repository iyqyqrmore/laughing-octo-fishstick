# Codex instructions — CoinCat v1.03beta

CURRENT OWNER OVERRIDE — NOVEMBER 4, 2026
The owner explicitly requested replacing the unconditional live submission
block with a "Live orders blocked" switch, ON by default, and real trading
when deliberately switched OFF for beta testing. This overrides the attached
beta handoff's permanent LiveBlocked invariant and the historical restrictions
below for the new bounded adapter only. Keep ordinary risk/funding/fee/depth/
precision/profit/UNKNOWN checks. No blind retry, taker fallback, startup resume
or implicit fee units. Delete unreachable legacy market-order submission logic;
do not expose it by merely deleting its first raise. Existing financial/FIFO/
tax/import/key/lock modules and datasets remain protected. Use a separate live
beta journal and only known CoinCat order identities for cancellation/recovery.
The live block resets ON at startup/restart. STOP/reblocking prevents new orders,
requests cancellation of owned resting orders and reconciles racing fills;
it never liquidates positions. Read-only adapters cannot submit/cancel orders.

The owner explicitly authorized commit and push "when complete as 1.03beta".
Use coincat-v1.03beta from freshly matched a09a1f3eab106f8d775e2ba76e80e29743292bd4;
preserve v1.02/v1.01/v100, and package source only after checks. No running-PC
installation or actual account trade from this cloud session is authorized or
possible here: no Coinbase credentials/network access are configured.

The owner requested fee-adjusted ASK pricing, with decimal/percentage education.
Use fresh authenticated applicable fee rates, not a universal 0.5% inferred
from one statement. BUY cost at ASK with quote fee is quantity*ASK*(1+rate);
SELL limit retaining a desired net quote amount divides by (1-rate). These
benchmarks are distinct from post-only execution prices. Current clarification
about marketable ASK BUY versus maker-only execution is pending; do not silently
enable taker fills. Initial live cap defaults are conservative and unapplied
until local settings/Start; the owner was asked to choose beta limits.

Keep the new book stream/data provider and manual importer optional/read-only,
strictly separate from the live controller. Retire old experimental UI/clutter
and genuinely unreachable code, preserve historical datasets and shared pure
financial compatibility. Storage cleanup defaults to a report, never financial
or research-record deletion. Report unresolved connected/native evidence honestly.

The following is the retained v1.02/historical contract; the current override
above controls conflicts about live submission/publication only.

Read docs/GLOBAL_PAPER_V1_02.md first. The owner requested shared whole-cent
USD-equivalent completed-rotation settings, 50% working ETH initially and up to
50% of available source afterward, 30s review / 120s reconsideration, all seven
markets / fourteen directions, strict UNKNOWN admission and a simpler interface.
The owner explicitly clarified that the first order uses the approved working
slice once, without a second halving, and UNKNOWN blocks even initial entries.
This request supersedes the earlier mandatory kickoff and main mixer layout
for new global sessions. Existing frozen configurations and records remain.
Profit-target application cannot increase size, relax protection or liquidate
losses. Existing orders retain immutable price/version; safe cancel/reconcile
precedes replacement. AI Lab is passive and never applies global settings.

ETH-USD is now allowed solely as a separate public USD valuation reference.
It is never an approved trading product, funding asset, chart/history product
or research graph edge. The same bounded collector obtains at most six native
books plus one reference under the existing 16-total / four-worker / 0.2s / 6s
limits. Freshness/spread/decision span and failures remain binding. No invented
depth/fee units are allowed. The normal BBO scanner cannot currently qualify
these required inputs, so new global paper sessions HOLD with UNKNOWN. Exit
taker-stress receipts value a conservative benchmark only; no taker order is
ever dispatched. Completed paper ETH-return slices are distinct from estimated
profit, intermediate gains and full-portfolio performance.

Keep v1.01/v100 intact. v1.02 source is based on published bba4dfea67b45e6f4eff7f15b7ba4398ab486a08.
No installation, connected account mutation, live permission or deployment.

Read docs/AUTO_PAPER_V1_01.md, docs/AUTO_PAPER_FEEDBACK.md, START_HERE.md,
DECISION_CHAIN_REVIEW.md, docs/V100_RESEARCH.md,
docs/V100_WORKSPACE.md and docs/V100_MONITOR.md. Use this checkout, no worktrees
unless requested. The owner explicitly authorized a clean v100 build, redundant
code/text cleanup, larger transparent upper-header logo, verification, commit
and push on November 2, 2026. The owner subsequently explicitly authorized the
prospective-journal follow-up commit/push. This does not authorize deployment or
execution.

On November 3 the owner selected implementation of a paper-only lifecycle using
explicit simulation/replay events. The isolated engine and scripted offline
driver are authorized. The owner subsequently explicitly authorized this paper
follow-up's source commit/push. Connected execution, strategy defaults, live
changes and installation remain separate. See docs/PAPER_LIFECYCLE.md.
Keep paper state in its own empty dedicated database, never a financial file.

The owner then requested all-market maker-only automated PAPER integration:
seven real-product tabs/fourteen directions, one shared portfolio, explicit
once-only kickoff, patient maker policy and a labeled conservative provider.
The pasted November 3 handoff governs that expansion. The later instruction
"please push as v1.01 when complete" explicitly authorizes source commit/push
after verification on coincat-v1.01, preserving coincat-v100. No installation,
deployment, real funding, account changes, new permissions or live execution.
The remote baseline was fetched/matched at ebe4fd7405dc7a827503b090ef60af348c45d838.
Do not ask again for this already authorized source publication.

The owner then requested brief validity/market following for paper limits while
retaining ETH accumulation as the objective. The short-lived optional policy
uses 120-second child orders, fresh re-evaluation after confirmed cancellation,
the original campaign source budget/deadline and the original session horizon.
No loss-exit rule is authorized: preserve the simulated net ETH target and HOLD
when the current native maker receipt cannot meet it. Legacy patient sessions
keep their exact frozen serialization/policy. Replacements are child intents of
one initial funding campaign, not new seeds; every child consumes an existing
order slot. Stop for the existing budget rather than expanding hard limits.

Only ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC and ADA-BTC may receive
active research quotes/history. Five assets: ETH, BTC, ADA, LINK, SOL. ETH is the
only initial funding source. No USD/USDC bridges, alternate products, automatic
REAL selection/funding, actual startup BTC seed, fee fallback, quote-touch fills, realized account ETH credit,
reserve harvesting or auto ARM. Direct maker scenarios remain independent
comparisons; never sum their full-wallet amounts as concurrent funding.

Adaptive ETH research is pure/conditional. With Auto Paper off, UI scanning observes only explicitly registered persistent cases; it
creates no experiments, seeds or paper trades automatically. Manual registration
requires a fresh applied ETH slice, signal ID, horizon and explicit conditional
assumption. See docs/PROSPECTIVE_JOURNAL.md.
The separate opt-in paper controller may select/reserve/settle inside its frozen
limits from current accepted scan frames. Saved opt-in never resumes or repeats
kickoff after restart. Four-way kickoff is explicit; blocked choices never fall
back or increase size to meet minima. No research comparison becomes funding.
One funded wallet serves all fourteen views. All intents LIMIT/POST_ONLY; no
taker/market/IOC fallback. Review defaults 30s and retains reasonable orders.
Cancel must reconcile before replacement. Paper expiry never liquidates holdings.
Only explicit conditional SIMULATED_ASSUMPTION events can advance paper inventory.
One budget cannot fund competing reservations; unknown/partial fills remain
locked. Fixed-horizon forward observations never select the best later exit or
establish predictive improvement. HOLD and NO DEMONSTRATED EDGE are the default.
Missing depth/fee units/residue valuation means UNKNOWN. A drawdown alert is
review-only and opt-in for offline callers, never a forced sale or loss limit.

LiveBroker.submit must retain unconditional first-statement LiveBlocked. Preserve
coincat_live.py, coincat_unified_fifo_v501.py, coincat_state_v50.py,
coincat_data_transfer.py and protected key/lot/lock code. No real exchange create/edit/cancel,
transfers, new authenticated previews, financial schema/record/lot/basis changes,
real allocations, risk-setting changes or credential requests. Preserve
private_data/private_backups and DPAPI/single-instance behavior. Fresh setup
requires explicit confirmation and an empty destination.

Canonical Decimal receipts, fees once, actual rules, native dust and exclusions
remain binding. Retain secondary pure cycle/native financial compatibility and
all financial assertions. Historical module/DB names are compatibility identifiers,
not dependencies on old installation folders. No alternate receipt calculator.

Preserve 30s age / 0.25% spread / 12s decision span, 16 total / 6 research books,
four workers, 0.2s GET spacing, six-second collection deadline, provider backoff,
hourly fee refresh, two-hour TTL and at least ten-minute failed-fee retry. Four
ETH anchors plus two rotating BTC cross-pairs do not guarantee seven synchronized
books. Never use cached/deferred books as a new combined executable decision.

Preserve ETH-only continuity identity and original expiry through quote/fee gaps,
bounded monotonic retries, sanitized stage errors and STOP/late Tk generation
rejection. Unrelated balances and display controls must not reset ETH setups.
Existing manual controls/defaults and exact custom amounts remain. Chart OHLC
uses sampled midpoints, not exchange trades, volume, fill evidence or signals.

Python 3.11, hash-locked dependencies, disposable synthetic state. HTTP must be
forbidden during test discovery and execution. Run focused tests, full suite,
actual Tk/STOP/mixer/hover/export/monitor checks, protected-file byte checks,
source hashes, source-only packaging and independent extracted-source validation.
Preserve the Snowball UTF-8 regression. Report counts/runtime/skips and distinguish
Linux fixtures from native Windows/DPAPI/connected account evidence.

Eight diagnostics themes and monitor v3 are quantity-free strict allowlists.
Reject unknown fields at every monitor nesting level. Do not export balances,
receipts, authorization references, account IDs, private paths or raw errors.
NO_SETUP_UNPRICED is a legitimate state; QUOTE_WIDE is a pricing blocker, not a
fill or a continuity failure. No monitor command/update channel.

Monitor v3 may contain one strictly allowlisted optional auto_paper aggregate
extension; private GUI amounts/settings/history never enter exports. The BBO
feed has no sized depth/queue. Seeded stress assumptions never become observed
liquidity or calibrated fills. Touch alone cannot fill. Freeze model parameters,
policy and original horizon; retain no-fill/adverse/partial/missed cases and open
losses. Basic membership changes no authenticated fees or inferred units/rebates.
Simulated quote fees do not establish credible exchange liquidation; subscription
costs are separate and unmodeled.

Source packages include regenerated SHA256_MANIFEST.json and an independent ZIP
checksum; exclude private records/backups, reports/uploads, monitor files/tokens,
keys, virtual environments, logs and bytecode. Further publication/deployment or
later strategy/execution changes require their own owner authorization.
