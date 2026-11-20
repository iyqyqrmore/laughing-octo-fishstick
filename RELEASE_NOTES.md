# CoinCat v1.07

- Built from the v1.06 research branch as a standalone Windows/Tkinter shadow
  application with a fresh SQLite schema and isolated data directory.
- Added market and fee reads, chronological forecasting, one-leg evaluation,
  bounded shadow execution, fill reconciliation, portfolio marks and rejections,
  and read-only historical Coinbase receipt reconciliation in `coincat/`.
- Retained the original icon, transparent logo, and Tk palette. Placed preserved
  v1.06 comparison policy source and the matched replay adapter in `research/`.
- Replaced the prior launch, setup and verification scripts with release-specific
  Windows scripts. Removed prior runtime controllers, legacy database readers
  and migrations, release scripts, and all automated test files from this
  release tree. The previous modules, records and reports retain their original
  Git revisions and on-disk locations.
- Live trading, order edits and cancellations on Coinbase, transfers, and
  withdrawals are unavailable. All displayed proposals and active order
  management in this application belong to shadow research.
