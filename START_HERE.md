# First-time CoinCat v80.0 setup

**LIVE order POST remains BLOCKED.**

Use one new permanent main folder, for example Desktop\\CoinCat. This is complete source, not an EXE installer. No old program folder is required.

1. Preserve old records first. Copy the old installation's complete private_data to a separate private backup if you want its financial/tax/research history. A fresh v80 dataset and a new key cannot recover that local history. Do not upload the backup or key.
2. Extract v80 into a new empty CoinCat folder. Do not copy an old .venv or extract over a running installation. You may keep the old app running until you choose to switch; do not run two versions against the same dataset.
3. Install normal 64-bit Windows Python 3.11 with its py launcher. Run **02_SETUP_COINCAT.bat**. It installs hash-pinned core dependencies into this folder's .venv. CPU research is the default; fast immediate discovery does not require CUDA or a trained GPU model.
4. Run **03_VERIFY_COINCAT.bat**. Require source hashes, Python syntax and the complete offline suite to pass. Tests use disposable synthetic data, not your private records. Keep the complete result if a check fails.
5. Run **04_FIRST_TIME_SETUP.bat** and confirm NEW data. It refuses any nonempty destination, creates the existing compatible ledger schema with no old records/key/settings, and verifies an independent initial backup inside private_backups. This is a backup of new data, not your old history.
6. Run **01_START_COINCAT.bat**. Confirm **CoinCat v80.0**. On a fresh start no Coinbase key is loaded. Click **Import CDP Key JSON**, select the new downloaded Coinbase key JSON on your PC, then refresh/connect.
7. Key permissions must include **View + Trade**, with **Transfer OFF**, as required by the preserved permission checks. Both Ed25519 PEM/base64 and ECDSA signing are covered by offline tests of pinned coinbase-advanced-py 1.8.4. Windows DPAPI stores the selected vault locally for this Windows user/machine. No real key or account connection was tested in the cloud.
8. Review newly verified available holdings and exclusions. Staked/locked/reserved amounts are not funding. External purchase tax basis remains unknown unless independently established. Separately ARM Experimental SHADOW if desired; LIVE stays blocked.
9. Read AI Lab's immediate funnel and **Immediate opportunity details**. Five modeled-positive estimates can coexist with zero strict-qualified models and zero RAM conversions. Missing depth, fee units, preview inputs or prices have explicit reasons.

## Evidence limits

The primary conversion needs W>0 AND L>0 after modeled fee/slippage/rounding, with consistent independent USD mark paths. There is no $0.10 Experimental minimum and no historical-growth fallback. Top-of-book observations are not candidate-sized depth or fee-currency proof. Positive unverified estimates are display/research-only. Connected strict qualification remains unavailable pending the separate integrations described in docs/STRATEGY_AND_EVIDENCE.md. Synthetic successes are labeled synthetic; they do not establish fills or profit.

Use Auto Trader's existing one-button complete diagnostic export while the app remains open. A manual stop retains RAM results. Re-arming/restarting begins a new RAM session; no patch can recover an already discarded RAM session.

## Optional tools and recovery

- tools/ENABLE_GPU.bat installs/verifies optional CUDA PyTorch. GPU learning remains advisory.
- tools/DEBUG_START.bat supplies startup diagnostics.
- tools/RECOVER_PRIVATE_DATA.bat explicitly copies one complete verified old dataset or backup into an EMPTY destination. It preserves records and research, can copy the old encrypted vault, and never merges or overwrites. This is optional recovery, not part of fresh setup. Re-select your intended new key afterward.
- tools/CHECK_OLD_FOLDER.bat only inspects an old folder. It does not delete it. A new empty-data backup does not certify that an old populated dataset has been preserved.

Normal v80 startup uses only this folder's private_data. Recovery receipts may mention old source paths as audit history; those paths are not runtime dependencies. Keep private_data, private_backups and an additional backup on another drive. Remove old source folders/shortcuts manually only after the new build works and all wanted private records are backed up.
