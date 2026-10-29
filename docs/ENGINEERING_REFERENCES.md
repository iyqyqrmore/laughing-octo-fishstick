# Public engineering references — reviewed October 29, 2026

These primary sources support specific engineering requirements. They do not
establish repeatable profitable Coinbase spot swaps. No source code from these
projects was copied, imported or installed in CoinCat.

- [CCXT Manual — order books](https://github.com/ccxt/ccxt/wiki/Manual#order-book):
  explains bid/ask quantities and that an exchange-generated order-book timestamp
  may be absent. CoinCat keeps local request/evaluation time separate from
  verified exchange-event time; recent local activity is not such verification.
- [Freqtrade backtesting documentation](https://github.com/freqtrade/freqtrade/blob/develop/docs/backtesting.md):
  documents fee assumptions, dynamic-pairlist historical limitations, and the
  backtest assumption that orders can fill without slippage inside a candle's
  range. CoinCat keeps modeled results distinct from actual fills and validates
  real-time eligible scope separately from historical observations.
- [Hummingbot fee data model](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/core/data_type/trade_fee.py):
  represents explicit percentage-fee tokens and token-denominated flat fees.
  CoinCat's connected evidence work must establish the actual debit currency
  and USD conversion, rather than infer it from an account tier or an amount.

The pasted research also mentioned public issue numbers, profitability figures
and an Arbitrage Inspector project without an exact repository link. Those
specific claims were not independently verified for this patch and are not
used as acceptance evidence. This review establishes the documentation points
above, not the accuracy of every claim in the pasted text.

Priorities retained for follow-up: consistent alternative valuation paths;
distinct-direction/complete-frame coverage; candidate-sized bid/ask depth with
native product rules; verified non-placing fee-preview semantics; and separately
approved shadow-versus-real reconciliation with durable ambiguous-outcome
recovery. Documentation from other strategies does not replace CoinCat's own
canonical planner, receipt calculation or tests.
