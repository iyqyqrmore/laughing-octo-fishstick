# CoinCat v91.0 — full-balance immediate scanner

One policy: rank eligible direct swaps by their greatest positive immediate
after-cost USD wallet advantage versus holding. Each proposal uses the full
verified AVAILABLE source balance, with modeled fees and exchange rounding
inside that balance. There are no portfolio budget controls, fractional size
trials or $0.10 profit floor. Nonpositive routes remain HOLD.

AI Lab is a passive observer. It reports findings in plain text every three
minutes and never chooses trades or changes sizing. One screen provides key
import, connection/refresh, start scanning, STOP and diagnostics, with views
for available balances, ranked swaps and passive notes.

**This build does not execute real swaps.** It displays positive estimates as
unverified and makes no order calls. The production broker remains blocked
pending durable order/fill accounting, reconciliation and restart recovery.
The UI says this explicitly and does not offer a mock trading or ARM button.

Read [START_HERE.md](START_HERE.md), [build details](docs/BUILD_V91.md) and
[cleanup record](docs/RETIRED_COMPONENTS.md). Existing financial records,
backup/import compatibility, tax basis and private data are preserved.
Historical releases, shadow modes and GPU experiments remain in Git history.
