# v95 overnight continuity hotfix

Owner authorized implementation on November 2, 2026. Base/checkpoint:
`f0b6181efc5ae4e12a2b9c82578d1a6b08482d87`, freshly matched to GitHub.
The installed Windows source is not independently hash-verified by this session.
Preserved source archive is outside the checkout. No running-installation changes,
private datasets, commits, pushes, deletions or publication are authorized here.

Changed-file plan recorded before implementation:

- Add pure continuity helpers for ETH-only funding identity, canonical selected
  product rules, quote rejection reasons and export-time freshness overlays.
- Add a sanitized read-only failure/recovery controller with monotonic bounded
  retries and explicit running/retrying/attention/stopped states.
- Update the scanner, fee reader and public quote journal for operation-stage
  attribution, staged/cancellable commits and reuse of existing request budgets.
- Update the maker observer to retain unpriced setups, original expiry and gap
  boundaries, with bounded reason-coded histories and distinct episode counts.
- Update GUI plan binding, relevant allocation edits, retry/STOP generation guards,
  periodic historical labels and all eight redacted diagnostic sections.
- Add focused deterministic regressions, run the full HTTP-forbidden suite and
  actual Tk tests, compare protected source, regenerate manifest/source-only ZIP,
  verify the extracted source and document supervised Windows acceptance.

Financial allocation/reconciliation contracts and protected broker/FIFO/state/
importer/key/lot modules remain unchanged. No stale fee/quote qualifies a current
evaluation, no gap creates a touch/fill and no recovery changes manual settings.
Existing ETH-only/three-market scope, economics, 30s/0.25%/12s guards, 16/6 ceilings,
three-book collector, spacing, deadlines and server backoff remain binding.

## Delivered source changes

- New: `app/coincat_continuity.py`, `app/coincat_recovery.py`,
  `offline_tests/test_v95_continuity.py` and this hotfix record.
- Updated runtime: `coincat_app.py`, `coincat_scanner.py`, `coincat_eth_maker.py`,
  `coincat_simple_diagnostics.py`, `coincat_v502_fee_learning.py` and the public
  quote journal `coincat_live_forward_store.py` (cancelled inserts roll back).
- Updated existing tests: growth lifecycle/STOP checks and the release-core
  no-order adapter scan. Canonical financial assertions remain unchanged.
- Updated current instructions, verification evidence, source-package metadata
  and manifest. No source file, private record or backup was deleted.

Actual checkout: 197 distinct tests passed, zero failures/errors/skips, with HTTP
forbidden. Linux Python 3.11.17 / SQLite 3.53.1 / Tk/Tcl 9.0 / Xvfb. Seventeen
protected/core source files match the checkpoint byte for byte. New source is
packaged with 99 manifest entries; the final extracted-source result and archive
checksum are provided beside the ZIP. No native Windows/account/deployment or
profitability finding is claimed. Supervised local acceptance is in START_HERE.
