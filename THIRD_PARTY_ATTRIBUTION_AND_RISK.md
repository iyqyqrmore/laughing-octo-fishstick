# CoinCat — software credits, licenses, research risks and automation policy

**v60.7 source distribution • October 26, 2026**

CoinCat is experimental educational research software, not financial advice, a profit guarantee, an approved investment advisor, or an exchange order certification. Trading can lose all authorized capital; even strategies with favorable historical outcomes can fail through fees, spread, slippage, order-book impact, outages, adverse selection, or model drift. The goal is to compare **total enrolled portfolio value in USD to unchanged HOLD** after all estimated leg costs, funding reservations and residual assets; a projected $0.10 minimum is a screening preference, not promised profit.

## Public research acknowledgments (conceptual inspiration ONLY)

| Project | Source | Public repository license as checked October 26, 2026 | Role in CoinCat v60.7 |
|---|---|---|---|
| Freqtrade | https://github.com/freqtrade/freqtrade | GPL-3.0 | Time-safe strategy comparisons, look-ahead testing, drawdown research concepts |
| Hummingbot | https://github.com/hummingbot/hummingbot | Apache-2.0 | Maker/taker and realistic non-fill execution research concepts |
| OctoBot | https://github.com/Drakkar-Software/OctoBot | GPL-3.0-or-later | Strategy variety and optional portfolio allocation concepts |
| Jesse | https://github.com/jesse-ai/jesse | MIT | Strategy benchmark and quantitative validation concepts |

**No source code from those four projects was copied, adapted, vendored, imported, or linked into the v60.7 patch.** The new CoinCat strategy comparison was independently implemented using elementary published descriptions of momentum, range and breakout analysis and CoinCat's own genuine REST bid/ask data. Merely crediting a project does NOT grant a license or waive its terms.

Before adding any external source/code/assets in a *future* patch: identify the exact upstream file, copyright owner, repository URL, pinned commit, copyright notice, SPDX license, modification and distribution obligations; include all required full license texts and NOTICE files, review GPL copyleft/source-disclosure implications with qualified counsel, and inspect dependency licenses and security. Do not combine GPL code into CoinCat by assumption. This is a technical distribution checklist, not legal advice.

## Approval model and unattended trading design (FUTURE only)

The intended future operation is **one explicit, typed, session-level ARM LIVE approval** covering automated eligible spot rotations **within previously approved bounds**, not a dialog for each otherwise compliant trade. Within that session the engine may propose, route, execute and reconcile qualifying BUY/SELL/SWITCH operations without asking on each order, but may NEVER enlarge authorizations, withdraw funds, bypass excluded/staked/locked inventory, silently raise spending limits, re-ARM after STOP/restart, or interpret new research as order permission. All manually saved SHADOW budgets are preferences, not live authorization.

This v60.7 build **does not implement or enable unattended LIVE trading**. Real Coinbase POST is blocked in source, independent of any GUI setting. Before any future one-time LIVE ARM mode, verify atomic production multi-currency FIFO, actual fee currency/fill reconciliation, Coinbase SDK product minimums and authenticated order previews, durable idempotent ambiguous-POST/crash recovery, software STOP fail-closed, independent portfolio-wide USD loss floor, read-only historical tax reconciliation, and independently validated positive after-cost portfolio edge against HOLD. A separate user-reviewed live-enablement release and explicit ARM will still be required.

## Four-tab invariants

- **Coinbase/Portfolio:** authenticated available liquid enrolled balances and exclusions, tax provenance and USD snapshots remain the sole source of authorized inventory. Research reports do not invent balances.
- **AI Lab:** one public REST quote store, three independent strategy generators, one automatic CUDA advisory (only when evidence permits), chronological later marks and missing-outcome tracking. Strategy patterns are not BUY permission.
- **Auto Trader/SHADOW:** one existing rotation planner and one set of safeguards; research-only candidates enter ONLY its exploratory queue and cannot become qualifying BUY signals or real orders without independent forward HOLD evidence. After modeled SHADOW fills, subsequent decisions use evolved SHADOW holdings only.
- **P&L/Tax:** unchanged original purchase-cost provenance and confirmed-fill ledger; shareable Complete Diagnostics uses the exact same last-cycle aggregate strategy snapshot and does not disclose holdings.

No strategy or CUDA model is guaranteed to increase portfolio value. The trade frequency, win rate, $0.10 research floor, and screen display should never replace measured expected **net portfolio USD gain versus HOLD** with downside and cost uncertainty.
