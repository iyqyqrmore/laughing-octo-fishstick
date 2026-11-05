# CoinCat v1.03beta — Manual Spot

CoinCat now opens a simpler manual trading workspace: **seven market tabs**, a
market dropdown and favorite star, exchange candle chart, red/green order book,
Buy/Sell limit ticket, orders, trade history and available balances. The previous
research and automatic controllers do not start with this workspace.

**Live orders blocked starts ON every launch.** Connect while blocked to read
markets and balances. After reviewing the beta caps, deliberately switch OFF;
your **Buy / Sell click can send a real Coinbase LIMIT GTC order**. There is no
extra research plan or predicted-profit requirement. There is no automatic
placement, liquidation, repricing or retry.

For ETH-BTC, prices are **BTC per ETH** and amounts are **ETH**. BUY at ASK with
Post Only OFF can fill immediately and incur taker fees. Post Only ON normally
uses BID for BUY and ASK for SELL; a crossing price is rejected. Fee estimates
use the authenticated account tier, with a fresh exchange preview before the
order. Missing historical commission units do not block a new manual ticket.
Realized settlement remains UNKNOWN unless its native evidence supports it.

The default beta caps are **$5 per order, .005 ETH-equivalent session turnover,
four submitted orders, one open order and 30 minutes**. A separate **2% fee
buffer/ceiling** is a risk limit, not an assumed exchange fee. Exchange native
minimums, precision, available source funds, portfolio and permissions still
apply. CoinCat never increases an entered amount to meet a minimum.

**Cancel & refresh ticket** waits for terminal cancellation and reported fills,
then prepares only the unfilled remainder at a fresh native price. Review it
and click to send a replacement. An ambiguous submission stays locked to its
original identity. Reblocking/closing requests cancellation of owned orders;
it never liquidates holdings or guarantees an offline exchange cancellation.

**Trade details / CSV** reads an order and its fills, then can corroborate native
settlement against a local statement using a unique market/side/quantity/price/
UTC-second match. It preserves raw API evidence and identifies field matching
separately from an order-ID join or account reconciliation. CSV deductions never
set future fee rates or establish a predictive trading edge.

Financial/FIFO/tax data, keys, backups, prior research records and the transparent
upper-right logo are preserved. Manual order identities use a separate journal.
Diagnostics and the optional read-only local monitor support this workspace and
export controlled counts/states without private amounts, IDs or raw responses.

Follow [START_HERE.md](START_HERE.md) and [the manual design/test guide](docs/MANUAL_SPOT.md).
The Windows resize-verification follow-up waits for native events before
measuring the requested window. After setup, `tools\VERIFY_MANUAL_WINDOW.bat`
runs a hash-checked nine-test quick check; the full verifier still runs all
487 tests. Application and trading behavior retain the previous build's bytes.
Cloud offline checks do not establish native Windows or connected acceptance.
No account order is placed from this development session. Branch:
`coincat-v1.03beta`; base for the resize follow-up: `2e9fa69`.
