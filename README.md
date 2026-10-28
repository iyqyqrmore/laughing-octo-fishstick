# CoinCat v70.1.1 — Shadow Valuation Fix

**DO NOT ENABLE LIVE ORDER POST.** CoinCat's Coinbase all-spot broker is intentionally blocked because cross-currency financial settlement, fail-closed loss floor and crash recovery are not production certified. The project remains a source-only Windows Python 3.11 application.

- Optional CPU-only setup (no CUDA requirement): `02_SETUP_COINCAT_V70_CPU.bat`
- Start: [`START_HERE_V70.md`](START_HERE_V70.md)
- Full engineering history and observed results: [`CODEX_HANDOFF_V70.md`](CODEX_HANDOFF_V70.md)
- Agent safeguards: [`AGENTS.md`](AGENTS.md)
- Suggested first Codex prompt: [`CODEX_FIRST_TASK.md`](CODEX_FIRST_TASK.md)
- Verify on Windows: `03_VERIFY_COINCAT_V70.bat`
- User-private state: `%APPDATA%\CoinCatV70`, **separate from** pre-existing `%APPDATA%\CoinCatV60`; first copy requires user approval.

The v70.1.1 hotfix corrects shadow startup valuation and provides specific blocker messages; see [PATCH_NOTES_V70_1_1.md](PATCH_NOTES_V70_1_1.md). The v70.1 patch prioritizes urgent shadow checks over background research and corrects quote freshness and complete-wallet mark acquisition. See [PATCH_NOTES_V70_1.md](PATCH_NOTES_V70_1.md) for changes, offline results and remaining limits. Historical V60 module names and release-verifier filenames remain for compatibility. Never place or retrieve API credentials or live private ledger files in a Codex repository.
