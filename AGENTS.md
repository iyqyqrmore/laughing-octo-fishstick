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
3. Inspect failure log: installed v60.18 on Windows had mojibake `â€¢` in Snowball label; pristine v60.18 ZIP had correct `•`. Check on-disk bytes before recommending fixes.
4. Audit missing experimental USD FX mark, FAST SNOWBALL end-to-end latency/selection, LIVE certification. Draft targeted changes with isolated regression tests. Wait for explicit approval before touching user-owned data.

## Definition of success
Evidence-backed reductions to research latency; verified after-cost HOLD comparisons, no lookahead, no stale-book fake profits; reproducible tests; 100% preservation of safety and user consent for any future live pilot.

## Portable data rules
Use the existing checkout; do not create worktrees without a user request. Never commit private_data, private_backups, migration staging or credentials. Database schemas, lot IDs and unknown tax-basis flags remain unchanged. Never automatically delete old folders. Normal startup must work with all old folders absent; migration source paths in receipts are audit history only.
