# CoinCat v1.05 — intelligent 24-hour one-leg portfolio shadow

CoinCat studies whether exchanging one of BTC, ETH, SOL, LINK and ADA can improve total portfolio USD value after its own entry costs, relative to keeping current inventory. It measures modeled results against the **unchanged original five-asset HOLD portfolio**. This is an unvalidated research policy with conditional maker fills.

Start with [Windows installation and acceptance](START_HERE.md). The supported application is Manual Spot plus **Intelligent shadow…**. Seven native market tabs remain; charts default to 1h. The inset transparent logo, refreshed account portfolio total and private holdings hover are retained. Closing exits safely; tray and custom minimize behavior are removed, including the Windows minimize button.

First Start copies freshly read **available account holdings**, excluding holds, into a separate simulated wallet. This owner-selected baseline moves no real funds. A fictional $100-per-asset baseline is an optional choice before first Start. Baseline, model and risk settings freeze for that trial. v1.04 records stay separate in **History archive**.

The direct 24h model requires 2,400 aligned closed hourly observations from five read-only USD reference products. It uses historical 24h outcomes, chronological walk-forward validation, a final 14-day holdout and uncertainty estimates. It never scales ten-minute returns. Data/model insufficiency produces HOLD; a trial may complete 168 valid hours without a qualifying trade.

Only the seven native pairs can receive conditional orders: ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC and ADA-BTC. BUY ETH-BTC spends BTC for ETH; SELL spends ETH for BTC. The selector sizes and ranks all fourteen directions by positive expected risk-adjusted portfolio advantage. No fixed dollar gain, compulsory return to ETH, reverse-trade fee or forced cadence.

Each order is LIMIT GTC Post Only. Reviews are 30s, competitiveness reassessment 120s, child lifetime 600s, original campaign 1,800s and at most three replacements. One active order; reconciliation precedes replacement. An acquired asset has no mandatory holding deadline. Quotes, candles, time and downtime never create fills. The conditional queue provider requires continuous public-trade evidence; a no-inferred-fill provider is also available.

Own native commissions are modeled once per filled leg. Authenticated rates do not prove settled fee currency or precision. Unknown settlement locks the order for review. Portfolio advantage, forecast advantage, open losses, paid modeled fees and realized-account profit remain distinct. Public diagnostics/monitor export fixed labels and counts only; private detailed reports contain holdings and must remain local.

Actual live block defaults ON. Deliberately switching it OFF plus a manual Buy/Sell click retains the existing bounded real-order functionality. **The intelligent shadow has no automatic real-money authority**, even with the manual block OFF. This release changes no actual financial records, fee math, permissions, FIFO/tax, security or backup rules.

See [policy and state machine](docs/INTELLIGENT_TRADER_V1_05.md), [retirement/compatibility map](docs/V1_05_RETIREMENT.md), [verification](VERIFICATION.txt), and [discussion handoff](docs/V1_05_DISCUSSION_HANDOFF.md). Earlier documents carry archive banners; historical identifiers are preserved rather than relabeled.

Source branch: `coincat-v1.05`, based on `8cd633334f16257fc94fd47067f3e588e5fd2cf5`. Native Windows/DPAPI and connected acceptance, forecast accuracy, maker-fill calibration and actual 168-hour market performance remain unverified. Synthetic passing tests establish engineering behavior, not a profitable trading edge.
