# CoinCat v70.1.1 — shadow startup valuation hotfix

V70.1 introduced a regression: the shared quote merger removed books wider than
the 25-basis-point trading spread limit before portfolio/shadow valuation could
apply its established valuation policy. A holding could therefore have a fresh
conservative portfolio USD mark and still trigger the generic "Missing portfolio
valuations or unresolved balance mismatch" message when starting SHADOW.

This failure was reproduced with synthetic data before fixing it. The screenshot
alone cannot establish whether the owner's actual account also has a balance
mismatch, a genuinely missing book, or an unsupported USD path.

## Changes

* The shared merger retains the newest structurally valid quote. Consumers apply
  their own valuation or trading limits. A newer wide quote displaces an older
  tight quote, so old attractive prices cannot hide current market conditions.
* Shadow startup uses the existing portfolio valuation policy: conservative
  bid/inverse-ask USD marks, up to three listed legs, with the existing 20% display
  spread ceiling. This is an observed valuation, not guaranteed executable depth.
  Wide-spread books are NOT made eligible for a trade.
* Whole-wallet frozen-HOLD/current valuation and required mark acquisition use the
  same valuation policy. Urgent trading candidates still use the 25-bps spread
  limit, current narrow quotes, fees, product rules and available balances.
  Freshness and synchronization limits remain in place for whole-wallet outcomes.
* Both shadow modes now use a common startup check. Only enrolled, enabled,
  available quantities seed the model wallet; an unrelated excluded account
  asset does not make that authorized wallet unpriceable. No enrolled holding is
  silently omitted merely because its price is missing.
* Startup warnings distinguish `USD_VALUATION_INCOMPLETE`, `BALANCE_MISMATCH`,
  `BALANCES_STALE`, `EMERGENCY_STOP_ACTIVE`, and invalid/no eligible balances.
  Missing-price warnings name the affected symbols and path reason locally,
  without printing quantities, keys, or tax basis. They do not invent prices or
  resolve mismatches automatically.
* The portfolio display also uses newest valid quote precedence instead of
  blindly overlaying older portfolio-source quotes.

LIVE submission, production FIFO, private-state schema, the conversion planner,
Snowball trade economics and portfolio reconciliation source are unchanged.
No private user records, credentials, or connected APIs were used during this fix.

## Verification and update

**308 offline tests passed**, including 13 new synthetic regressions, plus the
GUI smoke and 18/18 diagnostic export under Linux Python 3.11.17/Xvfb. Windows,
CUDA and the owner's connected account remain unverified. See
`VERIFICATION_V70_1_1.txt` for the recorded output.

Close older CoinCat processes, extract this source into a new `CoinCat_v70_1_1`
folder, run setup, then `03_VERIFY_COINCAT_V70.bat`, and launch normally. The GUI
title must show **v70.1.1**. The private data directory remains
`%APPDATA%\CoinCatV70`; do not run two versions against it at the same time.
No new private-data migration or reset is needed for this source hotfix.

If ARM EXPERIMENT is still blocked, use the new specific warning to distinguish
an actual price-data problem from a balance shortfall. Do not clear or rewrite
tax lots or disable the startup checks to make the warning disappear.
