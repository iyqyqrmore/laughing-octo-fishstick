> CoinCat v1.05 archive: this document describes a historical release or compatibility path. Current behavior and Windows steps are in [START_HERE.md](../START_HERE.md) and [INTELLIGENT_TRADER_V1_05.md](INTELLIGENT_TRADER_V1_05.md). Historical versions and record identifiers below are preserved.

# November 4 historical fee evidence

The shared statement contains seven Advanced Trade rows on November 4 in
America/Chicago. Other dates and nontrade activity are excluded from this
trade-only arithmetic check. The supplied detailed API evidence covers one
matching ETH-BTC SELL. Its reported maker execution, size, price, gross,
commission scalar and after-fee total agree with the unique statement native
fields/time. This is a field/time corroboration, not a CSV-to-order-ID join.

The statement notes support exact native gross/net arithmetic for all seven
rows. Five have a derived 0.5% quote deduction; two have a derived 0.9% deduction.
These percentages describe those historical note differences. They do not
establish maker/taker classification for the other six trades, a universal future
fee rate, exchange-native fee currency or complete account reconciliation.
The single supplied API fill does not report its commission currency. It remains
UNKNOWN even though the quote-flow arithmetic is corroborated. Its fill waiting
time also does not identify queue position or calibrate a maker-fill model.

Available evidence therefore supports **7 statement trades, 1 native API/CSV
match, 1 reported liquidity classification, 0 explicit API fee currencies**.
Audit coverage is PARTIAL_EVIDENCE. Full opening/closing account, deposits,
staking/other balance activity and lot/tax reconciliation remain UNKNOWN.
Detailed native amounts, financial notes and personal identities stay in the
private local report outside source control and source ZIPs.

`tools/AUDIT_MANUAL_FILLS.bat` and the dashboard audit action use CoinCat's locally
saved key for bounded GET-only history reads. They sweep fill cursors, including
fills of GTC orders created before November 4, then read each full native order
and fills. Scope, duplicate/cursor/coverage and native settlement checks remain
binding. Exhausting the bounded read budget cannot produce a complete audit.
Each collected receipt is appended to the separate observation history, preserving
raw API evidence and revisions. The detailed audit is saved privately beside it.
No preview, order creation, edit, cancellation or financial-ledger write exists
in this collector. No key or account read was performed from this cloud session.

Repeat the local audit once connected. Resolve absent receipt, currency,
liquidity, mismatched net and incomplete pagination evidence individually.
Never overwrite a missing native fee currency with a guessed quote unit.
Current projected maker fees come from the authenticated current account tier;
actual settlements use supplied native commissions once. Historical statement
rates do not become live settings or proof of future profitable trading.
