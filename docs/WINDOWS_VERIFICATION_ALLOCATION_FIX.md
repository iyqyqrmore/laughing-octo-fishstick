# Windows verification, allocation editing and ETH cycle checks

Read-only follow-up to `c24e60310ad74f847e0b6fd75c5a01c19ca89506` on the
existing development branch. No financial schema, production broker, native
receipt, active USD ranking, market-data limit, mixer or passive-advisor changes.

## Editable full-portfolio proposals

Each non-excluded asset initially proposes full AVAILABLE native units as
working, with manual/protected at zero. This owner-requested **RAM-only default
proposal** does not establish ownership, authorization, settlement or eligibility.
Existing exclusions override it. Actual eligibility still needs exact owner
authorization and separately verified snapshot-bound settlement/cashflow evidence.
The application supplies no reconciliation provider. Execution remains blocked.

Select an asset, edit native values, then Apply selected draft. Manual/protected
entries reduce proposed working from AVAILABLE until working is explicitly edited
for that asset. A lower explicit working value leaves the remainder UNASSIGNED.
Native values remain exact Decimals; no exchange rounding or order fitting occurs.
Protection is ETH-only, and bucket totals cannot exceed AVAILABLE.

The old refresh deleted/rebuilt table rows and reselected the asset; queued
selection events could overwrite text before Apply. Rows now update in place.
Repeated events for the same asset preserve entries. Explicit assignments are
never silently resized, and invalid/overallocated rows stay visible for correction.
Untouched defaults track AVAILABLE changes. Any entry edit revokes authorization,
and authorization requires applying pending edits first. Clear draft stays empty
through refresh. Full AVAILABLE draft explicitly restores the defaults. On restart
custom assignments are lost and the new proposal requires new authorization.

## Windows fixture cleanup

The supplied Windows run verified all 104 hashes and discovered 164 distinct
tests: zero assertion failures, seven errors and two skips. Every error occurred
while deleting disposable test SQLite files. A SQLite transaction context commits
or rolls back but does not close its connection. The snapshot helper and two
release-test connections omitted explicit closure; Windows refuses to unlink
open databases, whereas Linux permits it.

Fixtures now use contextlib.closing, preserving the write fixture's transaction
commit. Regression probes hold real connections strongly and require them closed
before temporary-directory cleanup, so GC cannot hide a leak. An old/new snapshot
probe retained one handle versus zero and returned identical data. Production
database modules already close their connections and are unchanged. No cleanup
error is ignored and no failing test is skipped to obtain a pass.

Tk fixtures drain idle initialization/shutdown events around root destruction.
Background Tcl/Python errors fail cleanup rather than being hidden. Native
Windows/Tk behavior still needs a local rerun. The former Linux-only lock test
now invokes SingleInstance in a child process, using the actual fcntl or Windows
msvcrt path. Symlink rejection may still skip when the host cannot create a test
symlink; the runner prints every skipped ID/reason and runtime versions.

## ETH-funded routes ending in ETH

The intended farmer considers ETH -> coin -> ETH and ETH -> coin A -> coin B ->
ETH, including further verified bridge legs when supported. ETH may fund newly
acquired coins; any approved listed market can be considered as an intermediate
direction. Every funding, cross and return leg needs its own fees, spread,
slippage, increment/minimum/maximum and liquidity evidence. Intermediate BTC is
not ETH proceeds. More recoverable ETH than HOLD after all costs is the objective;
no future appreciation is assumed to rescue an incomplete opportunity.

The new passive inventory checks **both directions of every approved market**
against an ETH-connected graph, regardless of current account holdings. It reports
bounded ETH-funded cycles, directions disconnected from ETH, and connected paths
beyond the current two-leg funding/return bridge model. Cycles use real listed
products with their BUY/SELL directions, start and end in ETH, and have no ETH
stop in the middle. A cross-coin cycle can have up to five legs; each occurrence
would require a costed canonical receipt, even when a product is used twice.
Prices/profitability do not influence these deterministic shortest funding paths.

Inventory is **topology only**: no new requests, quantities, cost estimates,
research admissions, trading rankings or spending authorization. Every approved
direction has an exported status; full route examples are bounded. These contain
public symbols and legs only. A connection is not proof that a size fits exchange rules, current
quotes synchronize, liquidity exists, working ETH is authorized or net ETH rises.
Missing routes are not invented, and longer connected paths are not called
impossible merely because this model does not cover them.

Synthetic VET -> BTC -> ETH tests verify canonical costs on both legs and that
modeled proceeds come from the final ETH receipt. A missing bounded BTC return
leaves BTC unconverted and complete ETH UNKNOWN. The ETH-funded topology fixture
also verifies ETH -> VET -> BTC -> ETH and ETH -> VET -> ETH. These product lists
are synthetic and do not certify actual Coinbase availability of VET-BTC/VET-ETH.

The existing scanner still ranks **direct USD research swaps** using the v91
policy. It is not an ETH-profit selector and does not enforce ETH endpoints on
that direct research list. Its separate passive return model closes supported
paths into ETH or leaves incomplete values UNKNOWN. ETH-funded topology does not
enable a selector, qualify an intermediate USD opportunity or bypass the broker.
Only authorized, reconciled working ETH could fund a future validated farmer.

## Local acceptance

Extract separately, preserve data/backups and run 03_VERIFY_COINCAT.bat. Require
zero failures/errors and inspect each printed skip; the symlink capability test
may remain unverified, while the native lock test should execute. Then type an
allocation, wait through live refresh, Apply, and check retained selection/values.
Confirm defaults, manual carve-outs, exclusions, explicit low working amounts,
authorization revocation and invalid-total rejection. Working/complete ETH may
remain UNKNOWN because conversion and reconciliation blockers still apply.

Inspect eth_cycle_feasibility in Export diagnostics for all-direction counts,
ETH-funded cycle examples and blocked reasons. Native sizing/costs are explicitly
UNVERIFIED. No real swaps occur. Full HTTP-forbidden and extracted-archive tests
remain required. Linux results do not certify native Windows/Tk, DPAPI, connected
performance, fills, fee currency, recovery or profit.

Observed checkout validation: **173 discovered / 173 distinct / 173 run**;
zero failures, errors, skips and expected failures. This retains the previous
164 cases, strengthens connection-lifetime/GUI checks, and adds nine allocation,
ETH-return and all-direction topology cases. Seventeen protected/economic,
return-model, control, admission, transport and lock files match c24e603 byte for
byte. The existing three-hour replay and request maxima are unchanged. The new
Windows-specific fixture behavior still requires rerunning the native verifier.
