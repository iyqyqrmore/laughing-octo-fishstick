# v1.04 portfolio header and simpler market navigation

The transparent CoinCat artwork is unchanged. It now sits beside the portfolio
amount, with free space to its right, rather than against the far window corner.
A compact **Total portfolio · USD** occupies the area beside the workspace title.
Hover or focus the amount to see holdings, approximate USD values and the last
refresh time. The popup updates while open and scrolls when the list is long.

Seven market tabs select the active market. The redundant market dropdown and
favorite star are removed, along with their unused handlers. Existing private
favorite files are left intact. Every tab starts with **1h** candles; choosing a
different candle interval still changes that chart only. Trading policy sampling,
orders, fees and risk limits are unaffected by chart display intervals.

## Data source, scope and freshness

A separate display-only reader uses Coinbase SDK 1.8.4's authenticated
`get_portfolio_breakdown(portfolio_uuid=..., currency='USD')` GET endpoint. It
verifies view permission, portfolio identity and the USD denomination. It can
show non-watch assets such as VET/VTHO when Coinbase returns them. No additional
trading pair, product book or funding asset is enabled. The old native account,
available/held balance parser and five-asset shadow portfolio remain unchanged.
Display estimates never enter the manual execution or shadow funding data.

Reads use the app's existing bounded/paced single worker, below manual execution,
reconciliation and market scanning. The reader targets a 15-second refresh,
within the existing 16-call budget. An overdue display read gets a turn before
another ordinary chart refresh; execution, reconciliation and shadow scans
retain priority. Slow/high-priority work can defer it; values
older than 30 seconds, disconnected data and failed refreshes are labeled stale.
A different/unverified portfolio cannot retain a previous scope's displayed data.
No popup or render tick performs a network request on the Tk thread.

Coinbase's reported portfolio total is shown as an approximate USD reference,
before sale costs. Spot rows use reported total units, including holds once;
available amounts are not added again. Distinct accounts for one asset aggregate
once, duplicate account rows are not double counted, and missing values remain
UNKNOWN. If the overall total is unavailable but row valuations exist, the label
becomes **Priced subtotal**. Unpriced holdings remain listed. No known valuations
produces an unavailable amount, never a fabricated zero. A verified empty
portfolio can display zero. Missing or unlisted value and derivative coverage
mark the holdings list partial; the app never manufactures missing assets.

These are API-visible balances for the selected Coinbase portfolio. Other
portfolios, staking balances or assets not exposed to the key may differ from
the Coinbase mobile/web account-wide view. Reference position floats are accepted
only in this private display parser. Canonical exact financial inputs, fee units,
profit accounting and available-funds checks retain their existing rules.

Holdings/amounts remain in RAM and the private header/popup. No portfolio amounts,
asset list, account/portfolio identities or valuations are added to diagnostics,
the local monitor, journals, tax files or public exports by this feature.

## Windows acceptance

The owner-reported preceding SQLite cleanup build completed 543 tests in
1737.252s with zero failures/errors and one host-symlink capability skip. This
new UI patch requires its own fresh source verification and connected check.

1. Preserve the installed folder, private records and backups. Extract the new
   source separately and run **02_SETUP_COINCAT.bat**.
2. Run **tools\VERIFY_MANUAL_WINDOW.bat** for 14 focused window checks, then
   **03_VERIFY_COINCAT.bat** for all **556 distinct tests** / **191 source hashes**.
   Require zero failures/errors; the known host-symlink capability skip may remain.
3. Launch and connect while **Live orders blocked ON**. Confirm tabs-only market
   navigation, **1h** on every tab and the logo/total beside the title at normal,
   maximized and minimum 1040x780 sizes. Manual order controls must stay reachable.
4. Compare the total and hover with Coinbase's same selected portfolio. Confirm
   API-visible non-watch holdings appear, totals include held balances once,
   unpriced data stays unknown and the timestamp advances on refresh. A popup
   that remains open must show refreshed holdings without reopening it.
5. Disconnect/wait beyond freshness and confirm stale/unavailable labeling.
   Reconnect and confirm recovery. No financial/user-history file, trial ID,
   budget, fee setting or live permission should change from reading this header.

Cloud checks use synthetic data and make no Coinbase requests. Actual connected
endpoint permissions, available holdings and native Windows rendering still need
local acceptance. This patch does not authorize unattended live trading.
