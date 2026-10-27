# CoinCat v70.0 — Clean Codex Windows Source Baseline

1. **Do not overwrite existing CoinCat_v60.** Unzip the FULL SOURCE into its own folder `CoinCat_v70` on the Windows PC. Close older CoinCat processes before optional private-data migration.
2. Review `AGENTS.md` and `CODEX_HANDOFF_V70.md` first. This build is **NOT approved for LIVE trading**; `LiveBroker.submit` unconditionally blocks new order POST. No live orders will be placed by offline tests.
3. Run `02_SETUP_COINCAT_V70.bat` for a fresh isolated `.venv` (Python 3.11 and CUDA packages may need Internet/disk). Legacy internal v60 filenames are maintained deliberately for backward-compatibility.
4. Run `03_VERIFY_COINCAT_V70.bat` (expect **offline regression suite and release hash integrity to PASS**). If anything fails, stop and send the output. Never assume release status from source hash alone.
5. Launch via `01_START_COINCAT_V70.bat`. The launcher will request your approval to **COPY** (not move or overwrite) a complete verified private dataset from `%APPDATA%\CoinCatV60` or another complete backup into new `%APPDATA%\CoinCatV70`. Until then, startup fails closed. Never migrate while older CoinCat is running.
6. Keep LIVE DISARMED. For fast strategy experiments, ARM only Experimental SHADOW after verifying synced enrolled holdings and Coinbase-read-only prices. The validated track retains historical gates.
7. Point Codex to `CoinCat_v70`, read `AGENTS.md`, request a full audit and incremental code patches. No private SQLite databases, API keys, credentials, or full private logs belong in Codex/cloud source context.

**Compatibility note:** v70 is a clean source and *private data folder* cut-over. Internal V60-named modules, `VERIFY_SOURCE_V60.py`, `SHA256_MANIFEST_V60.json` and v60-compatible state marker/schema are retained for reproducible regression and preservation of tax and lot records. v70 still has single-entry isolated source with v70 display identity. The `Codex` handoff is the development guide, not a permission to submit Coinbase orders.

**Known Windows user issue:** One original v60.18 Windows verification failed because the installed UI label had mojibake `â€¢` for the bullet. The pristine prior v60.18 ZIP contains the correct Unicode. v70 source is encoded UTF-8 with a new regression to detect that corruption. Make sure the extracted source bytes and verifier agree before changing trading logic.
