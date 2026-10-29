# CoinCat v91.0 setup and testing

This branch includes an **ETH Farmer development preview** on the preserved v91
base. Read docs/ETH_FARMER_DESIGN.md and docs/ETH_DESIGN_VERIFICATION.md. Mixer
reserve/reference values are proposed and RAM-only; they do not earmark funds.
No keys or production data are needed for its synthetic tests. The v91 test
count below describes the original release; the development count is recorded
in ETH_DESIGN_VERIFICATION.md. Keep your working Windows installation separate.

1. Extract into a separate new source folder. Preserve your working installation,
   private_data and private_backups. Do not overlay a running app or share one
   dataset between running versions.
2. Use normal Windows Python 3.11. Run 02_SETUP_COINCAT.bat, then
   03_VERIFY_COINCAT.bat. Dependencies are hash locked; plotting and GPU training
   are no longer part of this application. Expect 72 distinct offline tests.
3. For a NEW dataset only, run 04_FIRST_TIME_SETUP.bat and explicitly confirm.
   It refuses a nonempty destination and verifies an independent initial backup.
   Optional existing-data recovery remains under tools and never merges or
   overwrites a dataset. A fresh key/data setup does not recover old financial
   history. Keep your old records and offline backups.
4. Start with 01_START_COINCAT.bat. Import the CDP JSON key locally on your PC;
   Windows DPAPI stores it for this user/machine. Never send the key in chat.
   Existing permission checks require View/Trade with Transfer disabled; the
   application still cannot submit orders.
5. Connect / refresh, then Start scanning. Inspect the full available balances
   and priced/eligible direction coverage. Existing explicit asset exclusions
   are honored. There is no smaller-size fit search: product-size failures are
   recorded and skipped, with rounding dust retained.
6. Read the best currently priced immediate estimate and the ranked alternatives.
   W must be positive; there is no absolute dollar floor. Fees, spread and the
   0.15% modeled slippage reserve are included in the canonical receipt once.
   Actual depth impact, execution fees and fills remain unverified.
7. AI Lab writes passive notes about every three minutes. These are measured
   proposal counts and later hypothetical price comparisons, not a trained
   predictor, executed trades or realized profit. No AI recommendation gates
   the scanner. Missing future observations expire as missed, not losses.
8. STOP prevents subsequent scans and discards an in-flight scan result. Current
   findings remain on screen. Export diagnostics while the app remains open;
   the simplified report has eight current sections, replacing obsolete
   shadow/pilot/GPU audits. Counts and notes are RAM-only across this session.

REAL SWAPS REMAIN UNAVAILABLE. Completing actual automatic trading requires
verified native fill/fee accounting, stable order identities, duplicate
prevention and ambiguous-outcome restart recovery. This release does not remove
the unconditional production order block or claim that risk acceptance supplies
those missing capabilities.
