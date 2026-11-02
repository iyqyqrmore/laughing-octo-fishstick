# CoinCat v95.0 decision chain

Explicit ETH modeling proposal → manual direct-ETH companions → authenticated
eligible product rules → at most three shared bounded REST books → frozen quote
and account-fee observations → immediate taker benchmark and independent maker
hypothesis → passive uncertain-fill observations → quantity-free diagnostics.

No broad USD scanner, future-horizon admission engine or cycle enumerator runs
in this flow. Pure legacy USD/native and 3–5-leg cycle calculators remain secondary
library capabilities; they never justify patient maker returns.

The canonical Decimal receipt owns both legs, fee-once accounting, product
minima/maxima/increments, source residuals and native dust. Maker uses exact limit
prices with zero taker-slippage stress. Taker uses actual bid/ask plus explicitly
assumed per-leg stress. Account maker/taker tiers come from the existing read-only
SPOT transaction-summary provider. Quote-currency fee debit is a labeled scenario;
actual fee currency and product-specific exceptions are NOT VERIFIED.

BUY entries rest below ask, SELL entries above bid. Entry offset and target are
manual research controls. The rounded exit target is solved to meet the requested
ETH percentage in the full-fill scenario after both fees. It is not a predicted
price. Inverse ETH-base products use SELL entry and BUY return; labels show ETH
per companion coin separately from actual product limit-price units.

HOLD always uses exactly the initial ETH, including unspent ETH. Non-ETH residue
remains explicit; ETH subtotal is not a complete return when dust remains.
No-fill retains the original ETH. Partial/unknown fills have no credited return.
Worst-case full-entry coin exposure can be lost entirely; a real holding could
outlast the observation horizon. Touches/crossings never establish fills.

Within a decision: quote age ≤30s, spread ≤0.25%, span ≤12s. A future independent
exit decision has its own valid quote; it is intentionally separated in time.
Frozen setups invalidate on relevant ETH funding, selected eligibility/rules,
applied controls or verified fee changes. Unrelated account changes do not reset
them. Missing/invalid observations pause the original clock. Monotonic bounded
read-only recovery never infers touches through gaps; STOP cancels retries and
evaluation and rejects stale Tk results. Last-good prices/fees have explicit
export-time validity labels.
LiveBroker.submit still raises unconditional LiveBlocked as its first statement.
