# Codex Agent Instructions — CoinCat v70

## Mission
Improve CoinCat's *after-cost full enrolled spot portfolio USD value versus HOLD* using one-order Coinbase Advanced Trade conversions. Research live market activity with minimal delay, learn from observed later outcomes, and state uncertainty honestly.

## Nonnegotiable constraints
- NEVER enable LIVE Coinbase POST, remove `LiveBroker.submit` unconditional block, auto-ARM, place trades, send/print keys, modify private ledgers, or claim profitable trades. Post remains blocked.
- Source-only work. No production data or API calls in offline tests. DO NOT create `.env`/credentials in git.
- Use one canonical planner, one market store. Public stream is discovery, Coinbase REST book is valuation input. No direct conversion without authenticated listed pair.
- `Experimental SHADOW` and `Validated SHADOW` have separate RAM FIFO wallets; experimental is not live proof. All synthetic test data must be labeled synthetic.
- Preserve V60-financial-ledger-compatible schema. This new source root defaults to **`%APPDATA%\CoinCatV70`** and will only COPY a verified V60 private state via explicit approval. Do NOT open or migrate the user's V60 data without authorization.
- Use fresh simultaneous market books, available + enrolled source balances, Decimal fees and precision. Never overestimate executable profit or silently zero missing FX. No extra profit reserve / legacy $5 SELL clipping.
- Keep Windows Python 3.11 compatibility and all v60-compatible module names. Keep one-button 18-section diagnostics.

## First steps
1. Read `CODEX_HANDOFF_V70.md` and `START_HERE_V70.md`.
2. Verify integrity with `03_VERIFY_COINCAT_V70.bat` (Windows, Python 3.11, disposable data) and report test counts and any errors exactly.
3. Inspect failure log: installed v60.18 on Windows had mojibake `â€¢` in Snowball label; pristine v60.18 ZIP had correct `•`. Check on-disk bytes before recommending fixes.
4. Audit missing experimental USD FX mark, FAST SNOWBALL end-to-end latency/selection, LIVE certification. Draft targeted changes with isolated regression tests. Wait for explicit approval before touching user-owned data.

## Definition of success
Evidence-backed reductions to research latency; verified after-cost HOLD comparisons, no lookahead, no stale-book fake profits; reproducible tests; 100% preservation of safety and user consent for any future live pilot.
