# CoinCat v70.2 — folder consolidation and private-data cut-over

The owner selected one main CoinCat folder with local `private_data`. This
replaces `%APPDATA%\CoinCatV70` as the runtime location. Older folders are only
explicitly approved import sources; they are unnecessary after cut-over.

* Removed duplicate V60/V70 launchers and wrapper chains. Six versionless root
  launchers cover start, CUDA/CPU setup, verification, data import and cleanup.
  Optional tools and shortcuts use the same installation and data selector.
* Active database, encrypted vault, GPU research, diagnostic and debug paths use
  one shared root. Fixed V70 wrappers that incorrectly targeted V60 AppData.
  Verification accepts arbitrary installation folder names.
* Import snapshots and validates every SQLite database, compares logical contents
  and file fingerprints, verifies an independent `private_backups` copy, then
  atomically publishes active data. Receipts contain fingerprints/provenance, not
  account values or decrypted credentials. No existing dataset is merged or
  overwritten, and no empty ledger is inferred from missing records.
* Every historical/current process lock is probed, including the previously
  missed V70 lock. Symlinks/junctions, unreadable trees, insufficient disk,
  corruption, differing copies and divergent old data fail closed. SQLite
  WAL-committed records are copied through the backup API.
* A read-only cleanup check verifies the backup and each selected old folder.
  Unknown/modified/private files are not assumed disposable. It never deletes.
* Historical handoff/release documents moved to `docs/history`. Current guidance
  is `START_HERE.md`; integrity files are `VERIFY_SOURCE.py` and
  `SHA256_MANIFEST.json`. Internal compatibility module/database/marker names
  remain to preserve the state contract, not an older-folder dependency.

The owner's actual AppData and Desktop folders have NOT been accessed, moved or
deleted by Codex. Local import and cleanup checks still need to run on that PC.
All cloud migration tests use synthetic temporary data. Trading strategy, lot
identities, tax basis, financial schemas and the unconditional live POST block
remain unchanged. See `VERIFICATION.txt`; Windows/DPAPI/CUDA and connected
Coinbase reconciliation remain local checks.
