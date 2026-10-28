# CoinCat v70.6.1 — retained SHADOW diagnostics

This maintenance patch preserves stopped-session results during diagnostic
collection. A temporary SQLite file disappearing during a storage read no
longer discards the experimental wallet report. A persistent failed subsection
is identified without hiding the successful parts or claiming a complete export.
The v70.6 cost-selection rule, fees, budgets, scanning and execution remain unchanged.

The approved, available portfolio funds one canonical planner. Fresh Coinbase
books feed one-leg proposals into the explicitly armed, isolated SHADOW wallet;
its current quantities and same-time HOLD comparison return to P&L. Excluded
assets and unsupported products cannot become trade candidates. Every positive
available holding stays eligible without a wallet-dollar cutoff;
newly received coins fund the next decision. Experimental selection now requires
a positive current after-cost receipt or a matched, observed forward-cost scenario.
A recent rise alone cannot trigger a modeled conversion. There is no absolute
dollar-score hurdle. Exchange minimums and saved
spending limits apply. Unrelated missing prices do not block a fully priced
experimental route; whole-wallet P&L stays unverified until all required marks
are complete and synchronized. Model counts and execution counts are separate.
See [PATCH_NOTES.md](PATCH_NOTES.md).

The stream watches approved markets continuously. Urgent checks rotate through
fundable alerts and verify actual conversion books; broad quote collection runs
in bounded, resumable batches. A previous scan's clock no longer labels a fresh
urgent job as a 90-second scan. Diagnostics identify a genuinely slow phase.

Public learning uses those same fetched books, even with the experiment OFF,
without spending the modeled wallet or making extra requests. The forward-cost
path needs at least eight nonoverlapping five-minute observations in the current
actual pair's feature bucket. A cold installation can therefore show
`OBSERVING_NO_COST_EDGE` for at least 40 minutes, often longer. Positive immediate
routes can still qualify without that history. A quote refresh alone cannot reuse
the same learned scenario to charge another conversion fee. Empirical scenarios
remain experimental; reversals can still lose against HOLD. Ten conversions per
hour is a capacity goal, never a trade quota or a profitability claim.

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
