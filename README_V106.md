# CoinCat v1.06 — M0, candle export and M2 backtests only

M0 locally verified: maker 0.5%, taker 0.9%, maker two-leg rate sum 1.0%.
M2 uses 0.5% maker and a 1.0% maker stress case; no taker/market fallback.
No paper or live runner is implemented or authorized to run in this patch.
AGENTS.md, protected execution/accounting/security/store modules remain unchanged.
The v1.05 GUI has history, Tk lifetime and consistent public-snapshot fixes;
its old trials/benchmarks remain intact and do not run the v1.06 strategies.

From the existing CoinCat folder with its pinned dependencies (SDK 1.8.4):

```bat
.\.venv\Scripts\python.exe -m v106.fee_check
.\.venv\Scripts\python.exe -m v106.export_candles
.\.venv\Scripts\python.exe -m v106.backtest
```

M0 uses the saved Windows key or COINBASE_API_KEY + COINBASE_API_SECRET;
COINCAT_DATA_DIR is respected. No key is needed by M1 or M2. Never share keys.
M1 exports closed ETH-BTC, BTC-USD and ETH-USD public candles at 1h/5m, up to
730 days. USD pairs are references only. Pages include at most 350 response bars;
the inclusive endpoint is excluded whether closed or open. Requests are paced.
Progress prints saved rows/date; a full export can take 30+ minutes.
Optional --start / --end accept UTC dates or offset timestamps; --days defaults 730.
Rerun the same command to resume; first observations win, corrections are logged.

v106_out/data contains six CSVs, gaps.csv, conflicts.csv, export_state.json and
export_summary.json. NO_CANDLE_RETURNED means a requested missing bar;
NOT_FETCHED means an unsuccessful/unattempted download, not a proven market gap.
No missing candles are synthesized. Data/output is ignored by Git.
M2 waits for a COMPLETE export and the verified fees.json. A failed/absent export
produces NOT EVALUATED, never a fabricated GO/NO-GO verdict or simulated market data.

M2 preregistration 78f70fa; direction amendment 4dc4ca8; GO amendment eed34e2.
HOLD50 is unchanged initial 50/50 inventory, zero trades/fees; its no-trade alias
is not an independent baseline. BAND, RATIO and both ROUNDTRIP variants compare to it.
60 days train / next unseen 30 days; no selection on test/stress outcomes.
Wallet/HOLD/open cycles carry across test windows, preserving open losses.
ROUNDTRIP uses total ETH/BTC (including reservations) at native BID/ASK mid:
ETH weight <=50% means BUY; >50% SELL. Freeze side at cycle start; no tolerance.
<=50% source, entry chase, partial-size exits and exact fee-derived break-even.
ROUNDTRIP_ALTERNATING starts BUY, flips on completion, reuses ROUNDTRIP training
parameters; all other rules match. No losing liquidation or extra direction knob.
Only margin, entry ticks and max_hold_days are optimized for ROUNDTRIP.
Exit target stays frozen; an explicit max_hold_days removes margin only.

OHLCV cannot supply historic BID/ASK/queues: backtest touch is a declared
close +/- one native tick proxy. Only next-bar trade-through >=1 tick can fill;
volume bounds partial fills, and gaps never create fills. Not calibrated execution.
Fees accrue once per filled leg in BTC under a stated simulation assumption.
Reports include fees as % total starting portfolio, native fees, losses, cycles,
misses, entry replaces/cancels, drawdown and USD/BTC advantage versus HOLD50.
BUY-/SELL-first counts, exit durations, net profit, fees and stuck/open time are
split for each variant and fee scenario. Daily counts/full ledger are in the JSON.
GO requires >=10 unseen windows, >=60% wins, >=1% initial-portfolio net advantage
and nonnegative 2x-fee advantage. Otherwise NO-GO; BAND passing is a hypothesis.

Read v106_out/backtest_report.md and backtest_results.json. Stop after M2 for review.
Fast offline rerun: .\.venv\Scripts\python.exe tools\RUN_OFFLINE_TESTS.py --v106
Native Windows/real market results remain unverified until those local runs finish.
