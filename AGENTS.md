# Codex Agent Instructions — CoinCat v70

## Mission
Improve CoinCat's *after-cost full enrolled spot portfolio USD value versus HOLD* using one-order Coinbase Advanced Trade conversions. Research live market activity with minimal delay, learn from observed later outcomes, and state uncertainty honestly.

## Nonnegotiable constraints
- NEVER enable LIVE Coinbase POST, remove `LiveBroker.submit` unconditional block, auto-ARM, place trades, send/print keys, modify private ledgers, or claim profitable trades. Post remains blocked.
- Source-only work. No production data or API calls in offline tests. DO NOT create `.env`/credentials in git.
- Use one canonical planner, one market store. Public stream is discovery, Coinbase REST book is valuation input. No direct conversion without authenticated listed pair.
- `Experimental SHADOW` and `Validated SHADOW` have separate RAM FIFO wallets; experimental is not live proof. All synthetic test data must be labeled synthetic.
- Preserve V60-financial-ledger-compatible schema. The user authorized a self-contained installation. Default to **`<current app>/private_data`**; copy old private state only after the local import prompt, with a verified sibling `private_backups` snapshot. Do NOT open or migrate the user's V60 data without authorization.
- Use fresh simultaneous market books, available + enrolled source balances, Decimal fees and precision. Never overestimate executable profit or silently zero missing FX. No extra profit reserve / legacy $5 SELL clipping.
- Keep Windows Python 3.11 compatibility and all v60-compatible module names. Keep one-button 18-section diagnostics.

## First steps
1. Read `docs/history/CODEX_HANDOFF_V70.md` and `START_HERE.md`.
2. Verify integrity with `03_VERIFY_COINCAT.bat` (Windows, Python 3.11, disposable data) and report test counts and any errors exactly.
3. Use current PATCH_NOTES.md and DECISION_CHAIN_REVIEW.md. Historical handoffs describe older policies; v70.6 replaces momentum-only experimental acceptance with the policy below. Preserve the Snowball UTF-8 label regression.
4. Audit current diagnostics and the single planner-to-wallet-to-P&L path with isolated regression tests. Wait for explicit approval before touching user-owned data.

## Current experimental selection (v70.6)
- Public stream momentum discovers candidates; it does not forecast a repeat move. The archived `legacy_repeat_score` is an offline comparison only and must never authorize RAM movement.
- Require a positive actual current wallet receipt AND positive synchronized Snowball estimate, OR a matched causal forward-cost scenario from `ForwardStore.selection` in the same public market database. No extra exchange collector, wallet-based research table or alternate planner.
- Forward scenarios use the actual listed pair, exact BUY/SELL direction, at least 8 nonoverlapping 5-minute windows, >=80% observed coverage, fresh features/labels and the current costed receipt. Mean and empirical lower quartile must both clear costs. These are unvalidated scenarios, not confidence bounds or held-out certification.
- Passive observations do not spend the wallet and continue without ARM. Missing observation windows are not backfilled as later wins. Only completed prior outcomes may influence a decision.
- Do not reuse a posted pair/side/context/last-label/fee scenario on a new quote or size alone. Failed/no-op receipts do not consume evidence. Fresh positive immediate routes and new qualified families remain eligible; no arbitrary global cooldown or forced 10/hour quota.
- Preserve all positive approved native funding, small-wallet eligibility, acquired-coin reuse, current budgets, fees, slippage, product minima, precision and honest FX/P&L synchronization. Validated SHADOW retains its separate chronological held-out gates.

## Definition of success
Evidence-backed reductions to research latency; verified after-cost HOLD comparisons, no lookahead, no stale-book fake profits; reproducible tests; 100% preservation of safety and user consent for any future live pilot.

## Portable data rules
Use the existing checkout; do not create worktrees without a user request. Never commit private_data, private_backups, migration staging or credentials. Database schemas, lot IDs and unknown tax-basis flags remain unchanged. Never automatically delete old folders. Normal startup must work with all old folders absent; migration source paths in receipts are audit history only.
