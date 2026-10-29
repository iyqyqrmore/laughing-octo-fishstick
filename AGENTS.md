# Codex instructions — CoinCat v90.1

Read START_HERE.md, DECISION_CHAIN_REVIEW.md and docs/STRATEGY_AND_EVIDENCE.md. Current source is self-contained; historical module names are compatibility identifiers, not older-folder dependencies. Use the existing checkout, not worktrees unless the user asks.

## Nonnegotiable boundaries

- LiveBroker.submit must begin with unconditional LiveBlocked. Never enable LIVE, auto-ARM, order creation/edit/cancel, transfers or new authenticated preview traffic under Milestone A.
- Preserve app/coincat_live.py, app/coincat_unified_fifo_v501.py, app/coincat_state_v50.py and app/coincat_data_transfer.py unless explicitly authorized otherwise. No private record, credential, schema, lot ID, risk-setting or tax-basis mutation for a source patch.
- One canonical market store, planner and native receipt calculation. Exact Decimal amounts, source availability, exclusions, product rules, fee-once accounting, deadlines/backoff and synchronization remain binding.
- Primary v90 uses StrictImmediateShadow. W>0 AND L>0, no Experimental dollar floor, no momentum/history prerequisite and no forward appreciation as immediate profit. Archived v70 advisory models must never authorize primary movement.
- Positive unverified estimates remain visible. Missing depth, fee currency, preview evidence or pricing is not an economic loss. No live-observation strict qualification until separately scoped connected adapters are completed and verified.
- Synthetic strict evidence is only for explicit offline harnesses. Normal UI cannot accept it. Qualified model does not mean fill or profit. Preserve manual ARM/STOP and the separate Validated track.
- Partial opening marks are Experimental-only; preserve all native quantities and unknown marks. Full-wallet P&L remains unverified until complete synchronized prices. Never impute a missing price as zero.
- Fresh v90 setup requires an empty destination and explicit confirmation; never overwrite, reset or silently import an old dataset/vault. Default data is current-installation/private_data. Keep private_backups. Do not delete old folders automatically.

## Validation and delivery

Use Python 3.11, hash-locked dependencies and disposable synthetic data. Forbid HTTP during offline test discovery/execution. Run focused tests then the required full suite and GUI/18-section diagnostics. Report actual counts and limits; do not weaken assertions to pass. Preserve the Snowball UTF-8 label regression.

Package source only, with a regenerated SHA256_MANIFEST.json and independent ZIP checksum. Exclude private_data, private_backups, raw user diagnostics, keys, virtual environments, logs and bytecode. Keep current instructions at the root; old source versions remain recoverable in Git history. Never claim connected Windows/DPAPI, exchange execution, fee reconciliation or profit from offline tests.
