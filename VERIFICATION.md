# CoinCat v1.07 verification

| Check | Result |
|---|---|
| Fresh CPython 3.11.17 Linux dependency environment | 12 packages installed from the SHA-256 lock |
| Source manifest and Python 3.11 compilation | Verified on the source tree and extracted release ZIP |
| Disposable one-leg and SQLite checks | BUY and SELL, exact native fee, HOLD, partial fill, trade-through, evidence gap, order restart, receipt deduplication, child/campaign expiry and carried budget passed |
| Matched replay with synthetic data | All seven parameter scenarios completed across two chronological holdout windows; HOLD advantage stayed zero |
| Linux Tk 9.0, virtual display | Dashboard opened, displayed HOLD and signed forecast values, resized to the minimum dimensions, and closed |
| Native Windows acceptance | Pending |
| Coinbase public market data and authenticated fee/fill acceptance | Unverified. The cloud network proxy denied Coinbase connectivity and the current account schedule was unavailable |
| Real market comparison | NOT EVALUATED |

The release contains no automated test files. Disposable checks used synthetic
data with exchange networking disabled. The historical receipt example supplied
only observed fields; exact fee accounting was checked with synthetic amounts.
The Linux Tk check did not exercise native Windows window decoration or key
configuration. No actual order endpoint was exercised.
