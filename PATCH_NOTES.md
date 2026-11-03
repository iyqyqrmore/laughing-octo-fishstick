# Paper lifecycle preview — source push authorized

Based on published journal commit 5e951db. The owner selected implementation
using explicit simulation/replay events. Adds a separate durable paper state
machine, shared native reservations, post-only admission, explicit partial fills,
fee-unit quarantine, cancel races, idempotent dispatch/fill handling and exact
restart reconciliation. The offline scripted driver runs ETH→BTC→SOL then HOLD.
No quote-derived executions, connected execution adapter or predictor is enabled.
See docs/PAPER_LIFECYCLE.md for Windows test steps and discussion handoff.

Fixes the restart mismatch where the saved case viewer showed a record while the
main workspace said Journal empty. Startup/manual refresh restores the count;
diagnostics and monitor v3 use the same cached sanitized summary before any scan.
Heartbeat/export do not poll SQLite. Unavailable summaries remain UNAVAILABLE,
and a post-commit summary-read error does not claim registration failed.

The existing seven products, scanner limits, real broker block, protected
financial code, private schemas and transparent header are preserved. This
candidate's source commit/push is explicitly authorized. No PC installation or
real-account action is included.

# Prospective-journal preview — preceding published checkpoint

Based on published v100.0 commit 1e0d88e. Adds explicit manual preregistration,
a separate persistent conditional-experiment journal, original-deadline restart
handling, adverse/no-fill/unknown/missed outcomes, a local view and quantity-free
monitor v3 counts. Existing scans supply observations; no predictor, automatic
case creation, paper execution, new HTTP load or financial change is enabled.
See docs/PROSPECTIVE_JOURNAL.md for use, bounds and limits. Amount, horizon,
signal and entry assumption remain explicit owner choices.

The published v100.0 release notes below describe the prior pushed checkpoint.

# CoinCat v100.0 — clean Adaptive ETH Research build

Based on exact remote checkpoint 40bdac5df0c29a9571acc5fe118dd4d8190bf54a.
Owner requested source implementation, cleanup, build, commit and push. The
attached handoff's older publication restrictions do not override that request.
No deployment to the running PC, private-account action or environment publication.

Added one pure bounded adaptive module and an explicit synthetic offline example:
listed candidate directions, exact native path costs, shared hypothetical source
reservations, explicit assumed full-fill events, fixed-horizon conditional HOLD
comparisons and a separate honest paper ETH/drawdown scoreboard. No predictor or
positive edge is claimed. App integration is read-only topology/quality summary
from existing scans; it creates no paper inventory, reservations or extra polling.

Moved a larger transparent RGBA CoinCat banner into the upper area beside the
title/actions as requested. Header display adapts to width. Removed the obsolete
small opaque asset and its display code. Current product labels, launchers,
first-run receipts, shortcut, diagnostics and monitor identify v100.0. Monitor v2
exports a strict adaptive subsection and admits/explains NO_SETUP_UNPRICED /
QUOTE_WIDE without relaxing unknown-field redaction.

Consolidated superseded release narratives into current instructions and three
current contract documents plus independent technical feedback. Prior docs/art
remain in Git history. Current tests were renamed for v100; no financial assertion
or protected compatibility module was removed. Historical module/DB filenames are
intentional compatibility identifiers, not redundant runtime implementations.

All protected broker/FIFO/state/importer/key/lot/lock/native receipt/transport
sources and existing dataset schemas are unchanged. Quotes, fees, book limits,
manual controls, original expiry, retry/backoff and STOP generation guards remain.
Exact newly run validation and platform limits are recorded in VERIFICATION.txt.
