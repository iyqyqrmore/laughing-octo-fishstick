# ETH-BTC comparison report

**Market result: NOT EVALUATED.** The development environment could not reach
Coinbase through its network proxy. No synchronized candle export or current
authenticated fee schedule was provided. Relative-value edge versus HOLD
and fill calibration remain unverified. No actual order was submitted.

`python -m research.backtest` produces a chronological matched report after
verified inputs become available. The opening portfolio is a common $200
50/50 ETH/BTC research seed, or the same explicit starting ETH and BTC
quantities supplied to all strategies. The seed, wallet and unresolved losses
carry across 30-day held-out periods. Previous 60-day training periods select
v1.06 parameters; forecast training separates chronological fitting and
validation within the available lookback. HOLD50, BAND, RATIO, ROUNDTRIP
and ROUNDTRIP_ALTERNATING are v1.06 comparisons. The latter two are
research-only. Their strategy policies are retained as comparison source
with shared v1.07 settlement and replay-evidence limits. Historical v1.06
results are unaffected.

The observed baseline is 0.50% per conditional fill. Hypothetical cases use
0.40%, 0.25%, 0.15%, and 0.10%. The doubled fee is 1.00%. Adverse execution
uses the baseline fee, three ticks of strict trade-through and at most 0.1%
of bar volume. The other scenarios require one tick beyond the modeled limit
and use at most 1% of bar volume. Order books are approximated using the last
closed native candle plus or minus a tick; only subsequent contiguous bars
can provide fill evidence. Five-minute candles cannot reconstruct individual
trades, book depth, queue positions, 30-second reviews or exact fill times.
The replay adapts order handling to the available bar cadence; runtimes can
produce different orders.

The detailed JSON includes each policy's net and fee-adjusted gross USD
advantage, positive and total windows, drawdown, fills, nonfills and open
unfilled orders, modeled native commissions, mean first-fill time, ending
concentration by asset, modeled reserved seconds and forecast outcome
accuracy and coverage. The separate scenarios hold dates, inputs and
starting portfolio fixed. Gross adds incurred BTC commissions back at the
final BTC-USD mark. Fill times and reservation time are bar-level measures.
No missing bar is interpolated and an open position is marked at the end.
