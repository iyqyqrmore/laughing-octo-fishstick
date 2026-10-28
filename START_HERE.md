# Set up CoinCat v70.4

**LIVE order POST remains BLOCKED.** Do not delete an old folder until the new
installation, its copied data and its independent backup have been verified.

1. Close **every** older CoinCat process. Extract the new source into its own
   folder and rename it to your permanent `CoinCat` folder **before setup**.
   Do not extract over an older installation or copy an old `.venv`.
2. Run `02_SETUP_COINCAT.bat` for CUDA, or `02_SETUP_COINCAT_CPU.bat` for CPU-only
   research. Core dependencies are hash-pinned. Windows Python 3.11 is required.
3. Run `03_VERIFY_COINCAT.bat`. Require release hashes and the complete offline
   suite to pass. Tests use disposable synthetic data, not your private records.
4. Run `04_IMPORT_PRIVATE_DATA.bat` **once**. The preferred source is your current
   `%APPDATA%\CoinCatV70` dataset, not the older Desktop source folder. You may
   select another complete private backup, including an earlier self-contained
   installation's `private_data`. Do not mix versions or combine separate datasets.
   The importer copies all private SQLite databases, encrypted credentials,
   research, settings and tax files into `CoinCat\private_data`.
5. The importer checks SQLite integrity, logical DB contents, file fingerprints,
   and a separate copy in `CoinCat\private_backups`. Only a fully verified copy
   becomes active. It never deletes, overwrites or merges the original dataset.
6. Start using `01_START_COINCAT.bat` or the newly created `CoinCat - START`
   shortcut. Confirm **v70.4**, the expected records and exclusions, and no
   unexplained Coinbase reconciliation differences. Close older shortcuts. The
   new launchers do not point at the V60/V70 AppData folders.
7. Run `05_CHECK_CLEANUP.bat` and select an **old** folder. It only inspects; it
   never deletes. An imported data source must still match its snapshot. An old
   source folder must match its own manifest with no unaccounted private/custom
   files. Caches and generated CoinCat shortcuts are regenerable. Local Git history
   requires manual preservation. Unknown files or divergent old data block cleanup.
8. After the check passes and the new app starts successfully, manually remove
   that specific old folder and obsolete shortcuts if desired. **Keep the current
   CoinCat folder, especially private_data and private_backups.** Keep an additional
   backup on another drive when possible.

If import or cleanup is blocked, retain both copies and inspect the reason. Do
not clear tax lots, replace the ledger, reset balances or disable checks. A
changed old dataset needs reconciliation, not a blind merge.

DPAPI keeps the encrypted vault bound to the same Windows user/machine. Moving
it to another PC/user does not make it decryptable. Normal startup does not read
the old source or backup; cleanup verification needs the independent backup.
Moving/renaming the main folder preserves relative data routing, but rebuild
`.venv` and recreate shortcuts if necessary. Later updates must preserve
`private_data` and `private_backups` or use this verified importer again.

Optional tools live under `tools`. Only the dedicated Coinbase read-only history
tool permits authenticated GETs after a typed local opt-in. None permits orders.

Transient SQLite sidecars and old instance locks are not copied as ordinary files; committed WAL records are included in the database snapshots. Compatibility markers and import receipts are regenerated. User financial records are not rewritten.
