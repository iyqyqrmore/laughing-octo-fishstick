# ETH Farmer development evidence — October 29, 2026

Baseline: GitHub `coincat-v91` at
`752a01096e93e98cc72dc3d9287a338bd55d0c21`.
Development branch: `coincat-eth-farmer-design`. The owner subsequently authorized
committing and publishing this separate source branch for GitHub ZIP download.
No real account access, order, preview, transfer, reserve earmarking or
production-data change was performed.
This is a read-only development preview, not a numbered production release.

## Observed checks

- PASS: original v91 baseline, **72 discovered / 72 distinct / 72 run**;
  0 failures, 0 errors, 0 skips, 0 expected failures.
- PASS: development suite, **101 discovered / 101 distinct / 101 run**;
  0 failures, 0 errors, 0 skips, 0 expected failures. This retains 72 v91
  regressions and adds 29 ETH measurement/reserve/advisor/mixer tests. One v91
  GUI expectation intentionally now requires six research entries/resets in
  addition to the same five main actions. No trading assertion was relaxed.
- PASS: actual Tk GUI in Linux Xvfb, STOP/queued-result retention, exact entry
  and fader synchronization, accessibility bindings, eight-section diagnostics
  and redaction of account/model quantities. Manual synthetic layout inspection
  caught and corrected renderer-unsafe new labels; detailed accounting text is
  collapsible. The mixer fits a 1040x800 window with the wallet table visible.
- PASS: all seven protected financial/key modules match exact v91 SHA-256 bytes
  (broker, production FIFO, state router, importer, inventory lots, cross fills,
  key module). The first-statement unconditional LiveBlocked remains tested.
- PASS: CPython 3.11.17, 12 unchanged hash-locked runtime dependencies,
  dependency compatibility check, repeatable workspace-only installation.
- PASS: source syntax/hash checks (91 manifest entries, zero mismatches) and
  `git diff --check`. The regenerated
  manifest retains the v91 base build identifier for compatibility and explicitly
  labels this ETH Farmer development overlay and its baseline commit.

HTTP is forbidden through requests during offline discovery and execution.
All account fixtures, key-signing tests and data are synthetic/disposable.
The 92-file source archive passed independent manifest membership, CRC and
byte-equality checks. Its extracted source also ran all 101 distinct tests with
0 failures, errors, skips or expected failures under the same HTTP-forbidden runner.
An independent SHA-256 sidecar accompanies the locally packaged ZIP. GitHub's
Download ZIP creates its own archive with a containing directory and different
ZIP metadata; use the included source manifest to verify those extracted files.
No environments, bytecode,
private data/backups, credentials, logs, raw diagnostics or uploaded handoffs
are packaged. Source/archive checksums are integrity evidence, not approval.

## Reproduce

From the prepared checkout (or extracted source with the prepared interpreter):

```sh
cd /workspace/laughing-octo-fishstick
.venv/bin/python -B VERIFY_SOURCE.py
PATH=/workspace/.local/usr/bin:$PATH xvfb-run -a .venv/bin/python -B tools/RUN_OFFLINE_TESTS.py
git diff --check
```

`xvfb-run` creates and cleans the required display; no persistent server or
Coinbase credential is required. Python 3.11, dependencies and Xvfb are retained
in the cloud filesystem. Reusable install/start instructions and the exact v91
repository ref were saved in the environment draft. Publishing and validation
in a newly restored task remain separate, unperformed product actions.

## Changes

Added `app/coincat_eth_farmer.py`, `app/coincat_mixer.py`,
`app/coincat_settings_advisor.py`, `offline_tests/test_eth_farmer_design.py`,
`docs/ETH_FARMER_DESIGN.md` and this evidence note.

Updated the app shell, scanner snapshot carrier, passive Lab and simple
diagnostics; the GUI regression's control expectations; AGENTS.md, README.md,
START_HERE.md and DECISION_CHAIN_REVIEW.md; and SHA256_MANIFEST.json.
Dependencies, version constants, v91 ranking/canonical receipt and seven
protected production modules remain unchanged. Historical VERIFICATION.txt
still describes the original v91 release, not this overlay.

## BLOCKED / NOT VERIFIED

- Actual settled/working/manual/protected allocations, external cashflow
  attribution, earned ETH, a durable reserve journal and real harvesting are
  deliberately unimplemented. Reserve defaults are RAM-only proposed arithmetic.
- ETH re-denomination cannot create an edge. Modeled return paths are fixed,
  bounded, non-executable observations; dust/missing/skewed totals stay UNKNOWN.
  This is not a new closed-route arbitrage selector or atomic execution adapter.
- Windows batch execution/DPAPI, connected Coinbase/account semantics, sized
  depth, actual fee currency, exchange-event timing, fills, production recovery,
  CUDA, profitability and LIVE readiness were not verified. No offline result
  authorizes any of them.
- No environment publication or fresh-task restoration was performed.
  Source publication to the separate development branch is owner-authorized;
  it does not change the v91 branch or authorize trading. Review/save the
  environment draft and publish in environment
  settings when you want to activate its prepared snapshot.
