# CoinCat v70.2 — one self-contained folder

Read [START_HERE.md](START_HERE.md). Use one permanent main folder named `CoinCat`.
The app, databases, encrypted credential vault, tax files and verified private
backups no longer depend on older program or AppData folders after import.

```text
CoinCat/
  01_START_COINCAT.bat
  02_SETUP_COINCAT.bat
  02_SETUP_COINCAT_CPU.bat
  03_VERIFY_COINCAT.bat
  04_IMPORT_PRIVATE_DATA.bat
  05_CHECK_CLEANUP.bat
  app/
  private_data/       active databases, settings, encrypted vault and tax files
  private_backups/    verified independent snapshots — keep these
  .venv/             this installation's Python environment
  tools/             optional debugging, GPU and read-only verification tools
  docs/history/      historical release notes, not current setup instructions
```

`private_data` and `private_backups` are created on your PC. Neither is included in
source ZIPs, Git commits or cloud tests. Source verification uses a disposable
test directory and never migrates private data.

Run setup and verification, then explicitly import your current complete private
data once. Run the cleanup checker on each old folder before deleting it manually.
An old source-only folder can be retired; an old private-data folder requires a
verified copy and backup. Unknown/modified files block an eligibility result.
Nothing in CoinCat deletes old folders.

Financial schemas, lot IDs, original tax basis and unknown-basis flags remain
unchanged. Internal compatibility module/database names remain intentionally;
they do not require an older installation. All visible launchers are versionless.

**LIVE order POST remains unconditionally BLOCKED.** This is a Windows Python
3.11 shadow/research application. Offline tests and an import receipt do not
authorize trading or establish profitability.

See [PATCH_NOTES.md](PATCH_NOTES.md), [VERIFICATION.txt](VERIFICATION.txt) and
[AGENTS.md](AGENTS.md) for current requirements and evidence.
