# CoinCat v1.04 — resumable portfolio research

CoinCat preserves its seven-market Manual Spot workspace and adds an opt-in,
restart-safe **168 cumulative valid hour shadow trial**. It studies total
portfolio USD value after modeled costs against holding the original BTC, ETH,
SOL, LINK and ADA quantities. There is no mandatory ETH return or one-cent trade
trigger. HOLD is a valid result.

The isolated SQLite journal stores the original trial identity, frozen settings,
portfolio, reservations, decisions, replay fills, fees and monotonic checkpoints.
Offline, paused, stale and incomplete-market intervals add no valid hours.
Opted-in shadow trials recover only after state and input revalidation. Paused
trials stay paused; unknown order outcomes remain locked. Completion freezes the
trial and produces a private report. Windows tray monitoring can continue with
the main window hidden; Windows shutdown is never vetoed.

Maker hypotheses use LIMIT GTC / Post Only, noncrossing BID buys and ASK sells,
30-second reviews and conditional 120-second reconsideration. Forecasts remain
unvalidated. **Quotes never manufacture fills**: explicit replay receipts are
required to model executions. No queue-calibrated autonomous fill model or
unattended live authorization is claimed by this release. The dashboard counts
prospective qualification episodes, distinguishes UNKNOWN realistic fill feasibility
from replay assumptions, shows conditional costs and compares net modeled holdings
with HOLD. Zero qualifying trades can complete the trial successfully; monitoring
completion provides no profitability evidence.

**Live orders blocked defaults ON at every launch.** Switching OFF continues to
enable real manual order clicks under the existing bounds. Shadow authorization
is a different type and cannot reach authenticated creation or cancellation.
Manual and shadow journals, ownership and limits remain separate.

Diagnostics and the GET-only local monitor expose controlled states, counts and
trial progress. Detailed holdings/valuations and audit evidence remain private.
Legacy controllers are retired from default execution paths; financial/FIFO/tax
records, backups, historical compatibility and the transparent logo are retained.

Follow [START_HERE.md](START_HERE.md) for Windows setup, verification and recovery
acceptance. Native Windows tray/DPAPI behavior, connected Coinbase acceptance
and an actual 168-hour observation trial must still be validated locally.
Cloud deterministic tests and a completed shadow trial do not establish profit.
Source branch: `coincat-v1.04`; evidence follow-up base: `cc565d9`.
Original Manual Spot foundation: `9023209` on `coincat-v1.03beta`.
