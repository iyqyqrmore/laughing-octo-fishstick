# v91.0 decision chain

Development overlay: read-only ETH measurements follow USD ranking, and passive
settings advice follows observation. Neither changes selection or funding. The
reserve mixer is a proposed calculator; actual earned/protected/working ETH
allocation remains UNKNOWN. See docs/ETH_FARMER_DESIGN.md for precise scope.

Verified available balances → authenticated eligible direct products → bounded
fair public quote requests → one canonical full-native receipt per direction →
one consistent source/destination USD mark policy → rank W descending → show
best positive unverified estimate, otherwise HOLD. AI Lab observes afterward and
never alters the decision, size, costs, funding or application settings.

W is output native quantity times its current USD mark minus the actual native
source debit times its current USD mark. Remaining source is retained, so this
is the same incremental wallet difference as valuing both complete portfolios.
Fees/slippage are already embedded in the one canonical receipt; do not subtract
them twice. Exchange rounding leaves explicitly reported native dust.

CONSISTENT_WALLET_MARKS chooses shortest observed USD paths and conservative
bid/inverse-ask proceeds without looking at candidate profitability. A direct
USD market is permitted to mark that asset consistently, including for HOLD;
source valuation must not be weakened via a lower indirect path to manufacture
a gain on selling directly to USD. A non-USD conversion cannot serve as its own
mark path. Stale, circular, missing, wide or unsynchronized frames are unpriced,
not economic losses. Candidate-specific alternative-path retry remains future
work; the scanner does not opportunistically select a favorable fallback.

The former L hypothetical-liquidation comparison is available to canonical
library callers but is not calculated or required by this owner's W-only
policy. There is no portfolio budget, $0.10 floor, momentum history prerequisite,
forward-profit override, synthetic qualification, RAM FIFO or simulated wallet.
One full available quantity is reviewed; max/min failures never trigger a fit.

A positive estimate is not a fill or certified profit. Depth, fee currency and
exchange event time remain unverified; the UI and diagnostics state this. Actual
order submission remains blocked by the preserved production broker.
