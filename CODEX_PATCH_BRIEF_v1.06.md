# CoinCat v1.06 patch brief: ETH-BTC rebalancer, paper first, then tiny live

**Audience:** Codex. **Owner:** the user. **Read this fully before writing code.**
This brief supersedes the v1.05 research goals in `AGENTS.md` for this patch only. Do not edit or delete `AGENTS.md`; add nothing to it.

---

## 1. What the owner actually wants (plain words)

- A small, simple, automatic spot trader on **Coinbase (Coinbase One account)** using the **Advanced Trade API**, trading **watched markets only**
- Small account (hundreds of dollars, not thousands). Fees matter more than anything else.
- The only success measure is: **after all fees, is the portfolio worth more than if the owner had just held 50/50 BTC and ETH with no trading, over 30 days?**
- "A few dollars a day" is a hope, **not a target**. A result of "no strategy beats HOLD after fees" is an acceptable and useful answer. In that case say so plainly and recommend HOLD.
- The owner does not want more safeguards, more dashboards, or more documents. The owner wants to know if a simple strategy has an edge, then run it live with tiny size.

## 2. What we learned from v1.05 (do not repeat these)

- v1.05 is a Windows shadow/research app: 5 coins, 14 directions, 6 horizons, 168-hour trials. It has **no automatic live path**. Per its own docs, `LiveBroker.submit` raises `LiveBlocked`.
- All 658 rejections in the supplied capture were `FORECAST_HISTORY_INSUFFICIENT` (history ready for 1 of 5 references). The bot mostly just HOLDs.
- The entry gate stacks penalties (risk aversion, concentration, 2.58x uncertainty, adverse-selection allowance, a 672-way multiplicity allowance). With small edges and assumed fees near 0.50% (the docs' example estimate), almost nothing can qualify. There is no meaningful knob to "balance".
- The forecaster (12-nearest-analog on 24h returns) is unvalidated. The docs themselves say "no demonstrated edge".
- Most recent effort went into tests, docs and safeguards rather than testing whether any signal works.

## 3. Scope

### In scope
1. Verify the real fee tier (read-only).
2. Export ETH-BTC candle history to CSV.
3. A small backtest harness with three strategies and a pre-registered go/no-go rule.
4. A paper runner using the same strategy code as live.
5. A live runner behind explicit flags, with hard caps, for tiny size only.
6. One daily summary

###(BTC-USD and ETH-USD may be used as **price references only**).

- Multi-horizon forecasting, analog models, 168-hour trial clocks, new GUI windows, tray/minimize work, new monitor extensions.
- New markdown files beyond this brief and one short `README_V106.md` (max 60 lines).
- Editing protected modules (ManualExecution, LimitOrderServices, native receipt/fee-unit code, FIFO/tax/state/key/backup modules, TrialStore/TrialClock). Import them; do not modify them.
- Any change that weakens an existing safeguard.

### Size budget
New code target: **under ~1,500 lines** in a new folder (`v106/`), plus tests. If you need more, stop and ask.

## 4. Milestones (do them in order; stop and report after each)

### M0: Fee truth (GET-only)
- `v106/fee_check.py`: read the account's current fee tier (Advanced Trade transaction summary) and watched market product details (base/quote increments, min and max sizes).
- Print: maker rate, taker rate, **round-trip cost** (maker+maker and taker+taker), and the minimum watched market order in both ETH and BTC.
- Do not assume Coinbase One changes the Advanced rate. Report what the API says.
- **Acceptance:** output is saved to `v106_out/fees.json`. Nothing is traded.

### M1: Data export
- `v106/export_candles.py`: pull **closed** public candles for watched markets, plus BTC-USD and ETH-USD (for USD valuation), at 1h and 5m, for as long as the API allows up to 2 years. Page at most 350 bars per request with polite pacing.
- Write CSVs to `v106_out/data/`. Never fill missing bars. Write a `gaps.csv` listing gaps. Conflicting duplicate bars: keep the first, log the conflict.
- **Acceptance:** row counts and date range printed; gaps reported; re-run is idempotent.

### M2: Backtest harness
- `v106/backtest.py` plus `v106/strategies.py`. Three strategies, nothing else:
  1. **HOLD50**: buy and hold 50/50 by value at the start. This is the baseline.
  2. **BAND**: target 50/50 by USD value. Rebalance only when drift exceeds `band` (default grid 3%, 5%, 8%). Trade back toward target with a post-only limit at the touch.
  3. **RATIO**: z-score of log(ETH/BTC) against a rolling mean. Act only when `|z| > k` (grid 1.5, 2.0, 2.5) **and** the expected move exceeds 2x the round-trip fee. Otherwise no trade.
- **At most 3 tunable parameters per strategy and a small grid.** No other knobs.
- **Fill model (conservative):** a maker limit fills only if the next bar trades **through** the limit price by at least 1 tick. Otherwise it is a **miss**. Orders cancel after N bars (default 2 on 5m). Misses count and are reported; they stay in the denominator. No taker fallback in the backtest. Use the **actual fee rates from M0**. Also run a stress case with fees **doubled**.
- **Walk-forward only:** choose parameters on a training window, evaluate on the next unseen window (for example 60 days train, 30 days test, rolling). Never report in-sample results as the headline.
- **Report, per test window and in aggregate:** net value change versus HOLD50 in USD **and** in BTC terms, fees paid, trades, misses, max drawdown, time in market.
- **Pre-registered go/no-go (commit this rule before running):** GO only if the strategy beats HOLD50 after fees in **at least 60% of test windows**, the aggregate advantage is positive, **and** the aggregate is still non-negative under doubled fees. Otherwise NO-GO.
- **Acceptance:** `v106_out/backtest_report.md` with the table and the GO/NO-GO verdict per strategy. If every strategy is NO-GO, say so at the top of the report and stop. Do not proceed to M3 without owner review.

### M3: Paper runner
- `v106/paper_runner.py`: runs the **same strategy code** as live against live public data (REST, optionally the WebSocket market channel), with the same conservative fill model. Logs every decision, order, simulated fill, fee and miss to SQLite (`v106_out/paper.sqlite3`).
- Must survive restart without inventing fills for downtime.
- **Acceptance:** runs unattended for 24 hours in a supervised check; daily summary (M5) is produced.

### M4: Live runner (off by default)
- `v106/live_runner.py`. Starts only if **all** are true: environment variable `V106_LIVE=1`, a `v106_live.json` config exists, the API key is trade+view only (refuse if it reports transfer/withdraw permission), and the manual live-block setting is acknowledged. Otherwise it exits with a clear message.
- Reuse the existing manual order layer (precision, caps, idempotent `client_order_id`, reconciliation, unknown-POST lock) if it can be called without modifying protected files. If it cannot, use the pinned `coinbase-advanced-py` SDK directly and say so in the report.
- **Hard caps (config, with these defaults; owner edits the file):**
  - max order notional: `$25`
  - max daily notional: `$100`
  - max trades per day: `6`
  - max open orders: `1`
  - daily loss halt: `2%` of starting value, then stop until the owner restarts
  - post-only limit GTC only, no market orders
- **Safety behavior:**
  - On start: list open orders and balances, and reconcile before placing anything.
  - Unknown order state means halt, never retry a POST.
  - A `STOP` file in the working folder cancels open orders and exits.
  - Never log keys. Read the key from the existing key store or an environment variable only.
- **Staged rollout:** stage 1 uses only the exchange minimum order size for 3 days; stage 2 uses the caps above. The owner promotes the stage by editing the config, not the code.
- **Acceptance:** unit tests cover fee math, fill model, every cap, STOP file and unknown-state halt. **Do not place a real order in the development environment.** First live order happens only on the owner's machine.

### M5: Daily summary
- One file per day, `v106_out/daily_YYYY-MM-DD.md` (max 25 lines): portfolio value, HOLD50 value on the same prices, difference in USD and BTC, fees paid, trades, fills, misses, any halt or error.
- A running 30-day scoreboard: cumulative difference versus HOLD50 after fees.

## 5. Success criteria (for the owner)

After **30 days of paper** and then **30 days of tiny live**:

- Cumulative net value **minus HOLD50 is zero or positive after all fees**, in USD terms and in BTC terms.
- No cap breach, no unreconciled order, no unexplained halt.
- Fill rate and miss rate reported honestly.
- If the result is negative or flat, the recommendation is HOLD and the project stops. That counts as a successful experiment.

## 6. Working rules for Codex

- Do the milestones in order. After each, post a short result: what was built, the numbers, and any surprise.
- Do not tune on test windows. Do not rerun with new parameters after seeing the verdict and present it as the original result.
- Report losing and flat results as prominently as winning ones.
- Do not add safeguards, docs, or features that were not asked for. If you think one is needed, ask the owner in one sentence.
- Keep Decimal math for money. Use UTC everywhere.
- Add unit tests only for the code in `v106/`. Do not rewrite the 649 existing tests.
- Tell the owner honestly which parts were **not** verified (no live account, no Windows native test).

## 7. Owner decisions (defaults used if not changed)

| Decision | Default |
|---|---|
| Starting capital for live | owner to state, for example `$200` |
| Strategy to take live | whichever passes M2 GO/NO-GO; if several pass, simplest |
| Daily loss halt | 2% |
| Max order notional | $25 |
| Band / z threshold | chosen by walk-forward only |
| Pair | ETH-BTC only |

## 8. Reference facts

- Advanced Trade REST base: `https://api.coinbase.com/api/v3/brokerage`. Order types include market, limit, stop-limit and bracket. WebSocket has public market data and a private user channel.
- Pinned SDK in this repo: `coinbase-advanced-py 1.8.4` (see `app_requirements.lock`).
- Candle requests are limited to 350 bars per page.
- Spot is long-only: the strategy can only change the mix of BTC and ETH, it cannot avoid a market-wide drop. Judge it against HOLD50, not against zero.
- Every trade is a taxable event in many jurisdictions. Keep the CSV/SQLite logs as records.

## 9. One-line prompt to start Codex

> Read `CODEX_PATCH_BRIEF_v1.06.md` and do M0 only. Report the fee tier, round-trip cost, and minimum watched market order, then stop and wait.
