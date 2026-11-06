# CoinCat v1.04 — native one-leg assumed trial

CoinCat uses seven market tabs with 1-hour chart defaults and a private live
portfolio total/holdings hover beside the title and inset transparent logo.
The **Native one-leg trial** starts with a fictional **$100 each in ETH, BTC,
ADA, LINK and SOL**, uses minimum native limit orders across seven markets,
and records explicit assumed fills with local SIM IDs. Each BUY or SELL pays
one applicable authenticated maker/taker-rate fee in the modeled quote coin.
No round-trip charge, added slippage, USD spending/turnover/attempt cap or
one-cent qualification gate applies to this mode. Per-market sizing sliders
increase quantity above the exchange minimum using versioned future settings.

The isolated SQLite journal stores the original trial identity, settings history,
portfolio, assumed orders, native fees and monotonic checkpoints.
Offline, paused, stale and incomplete-market intervals add no valid hours.
Opted-in shadow trials recover only after state and input revalidation. Paused
trials stay paused. At **168 cumulative valid hours**, completion freezes the
trial and a private report. Windows tray monitoring can continue with
the main window hidden; Windows shutdown is never vetoed.

The default BUY uses the native ASK and taker estimate; SELL uses ASK and maker
estimate. BUY at BID is an explicit maker alternative. The live book determines
the next price; fees affect cost/proceeds, not base quantity. Native increments,
base/quote minimums, product maximums and shared fictional funding still apply.
**Assumed fills are not realistic execution or profit evidence.** The private
dashboard compares conditional portfolio USD value with holding the original
quantities. Exchange commission precision remains unverified; a product quote
increment is not used to invent a minimum fee. AI sizing control remains off.

The earlier portfolio-policy trial and its records remain under **Previous trial**.
Its baseline, limits and valid hours are preserved separately. Starting the new
trial pauses that old policy; it does not rewrite or merge the two trials.

**Live orders blocked defaults ON at every launch.** Switching OFF continues to
enable real manual order clicks under the existing bounds. The assumed engine
has no exchange submission/cancellation adapter. Shadow authorization
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
Source branch: `coincat-v1.04`; native one-leg follow-up base: `999d77c`.
See [the native one-leg guide](docs/NATIVE_ONE_LEG_TRIAL.md).
See [the portfolio/header guide](docs/V1_04_HEADER_PORTFOLIO.md).
Original Manual Spot foundation: `9023209` on `coincat-v1.03beta`.
