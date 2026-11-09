> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

# v1.04 Windows SQLite cleanup correction

The published `71d175e` checkpoint passed all 184 source hashes on the owner's
Windows Python 3.11.9 / SQLite 3.45.1 / Tk-Tcl 8.6 host, but failed full native
acceptance: 533 tests, zero assertion failures, two WinError 32 cleanup errors
and one synthetic-symlink capability skip. Both errors occurred while deleting
a deliberately corrupted disposable `trial.sqlite3` in recovery tests.

## Cause and resource ownership

`with sqlite3.connect(...) as db` manages a transaction, not the connection's
lifetime. The two corruption fixtures opened three mutation connections this
way and did not explicitly close them. A diagnostic holding connections strongly
found one still open in the first reported case and two in the second, without
waiting for garbage collection. The fix closes each cursor and connection, with
transaction commit/rollback happening before connection closure.

The production trial store already closed its connections. Its resource owner
now encompasses opening, metadata checks, caller operations and failure
unwinding. Every query cursor is explicitly closed, even when execute/fetch
fails, so retained exception frames cannot prolong prepared-statement handles.
All original SQL expressions, parameter bindings, transactions, schema/version,
checksums, original benchmark/budget invariants and recovery safeguards remain.
No trial migration/reset, strategy, fee, permission or financial-record change
is included. Corrupt/incomplete databases remain available for review.

The regression probe retains real SQLite connection/cursor objects and asserts
explicit closure before deleting each fixture directory. It never closes leaks
to make a test pass. The ten focused lifecycle tests also retain exceptions and
immediately rename/remove databases. On Windows an exclusive `CreateFileW` open
with read/write access and zero sharing must succeed first; its native handle is
explicitly closed. No GC call, delay/retry loop, suppressed cleanup exception or
new platform skip is used. Linux logical/rename checks are not a native Windows
sharing-lock pass; the corrected Windows run remains necessary.

## Fresh Windows rerun

1. Exit CoinCat normally. Preserve the existing installation, private data,
   journals and backups. Extract the corrective source ZIP into a **new folder**;
   do not overlay the running/failed folder or reuse its virtual environment.
2. Run **02_SETUP_COINCAT.bat** in the fresh folder using 64-bit Python 3.11.
   No account/key import or private-data copy is required for isolated tests.
3. Run **tools\VERIFY_RESUMABLE_TRIAL.bat**. It checks the new source manifest
   and runs the focused trial suite, including the ten lifecycle regressions
   and both originally failing recovery tests. All must pass. On Windows the
   retained-handle checks perform exclusive native access before fixture cleanup.
4. Run **03_VERIFY_COINCAT.bat** for the complete isolated suite. Expect **187
   source hashes** and **543 discovered/distinct tests**. Wait for final COUNTS
   and PASS. Earlier full Windows runs took 20–30 minutes; numbered tests and
   30-second progress messages show activity.
5. Require **zero failures and zero errors**. The host's existing symlink-
   capability skip may remain; no SQLite/lifecycle skip is expected. Preserve
   the RUNTIME, hashes, DISCOVERED, final Ran/COUNTS and PASS lines. If any test
   errors, retain its full traceback and do not treat acceptance as passed.
6. Only after the fresh full pass, resume the separate connected/read-only
   acceptance guide in START_HERE.md. Existing strategy/live controls are
   unchanged. This patch does not authorize an account trade or unattended live
   operation and does not require deleting any private trial or financial file.

For a narrower direct investigation after source verification, a command prompt
opened in the fresh source root can run:

```bat
set "PYTHONPATH=%CD%\app;%CD%"
".venv\Scripts\python.exe" -u -B VERIFY_SOURCE.py
".venv\Scripts\python.exe" -u -B -m unittest -v offline_tests.test_trial_sqlite_lifecycle offline_tests.test_resumable_trial.Recovery.test_atomic_actions_cannot_change_original_benchmark_and_detect_in_process_corruption offline_tests.test_resumable_trial.Recovery.test_corrupt_missing_or_wrong_checkpoint_never_reset
```

Those twelve targeted checks do not replace the complete offline verifier.
