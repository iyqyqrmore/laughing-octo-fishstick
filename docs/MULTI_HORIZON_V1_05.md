# CoinCat v1.05 — multi-horizon policy and evidence

## Independent identity and baseline

MULTI_HORIZON_ONE_LEG_V1 owns separate frozen settings, HOLD, wallet, clock, journal and trial ID at `research_data/intelligent_multi_v105/active.sqlite3`. The retained 24-hour baseline remains at its existing path. No migration/reset/reinterpretation of old records. Switching views is not a start/stop. Each trial has one finite shared wallet and one active local order. Independent live trials are NOT PAIRED.

The goal is risk-adjusted total USD portfolio value versus original five-asset HOLD after current-leg costs. Small positive scores can qualify. Losses/no-fills/drawdowns stay. No fixed profit floor, forced ETH return, alternation, liquidation or trade cadence.

## Direct horizons and evidence

| Horizon | Closed history / actual labels | Features |
|---|---|---|
| Immediate | Synchronized current USD references, native limit and after-fee wallet; 61 minute observations for resting risk | Zero future mean; positive conservative marked flow required. Not a future prediction. |
| M5 / M15 | 4,320 aligned minute observations; actual 5/15-bar forward returns | 5m/30m changes, 60m volatility |
| M30 / H2 | 2,880 aligned five-minute observations; actual 6/24-bar forward returns | 30m/2h changes, 6h volatility |
| H24 | Existing 2,400 aligned hours; actual 24h returns | Retained direct-24h model/folds |

Short forecasts use nonoverlapping UTC horizon origins, at least 64 matured training labels, at most 256 recent training labels, twelve analogs and training-only scaling. Each of sixteen validation and sixteen holdout predictions trains only on labels ended by its origin. Require twelve available predictions per fold. Outliers beyond eight training deviations, extreme returns, gaps or stale inputs HOLD. No scaled/extrapolated return labels.

Provenance records parameters, canonical history digest, feature/training endpoints, analog origins, chronological maturity and model/naive/HOLD errors. Current fitting uses matured labels only. Historical residual covariance/bias and a declared variance floor estimate uncertainty. Scored folds are not untouched prospective trading evidence. Forecasts remain UNVALIDATED_RESEARCH_ESTIMATE; calibrated coverage is not claimed.

Prospective predictions are registered before outcomes, separately by horizon. Every USD reference must be fresh and at/after the due time. Grace is 30s M5, 60s M15/M30 and 120s H2/H24. Missing the window is permanently UNKNOWN, never a favorable later quote. Samples overlap and are not independent significance evidence. Immediate has no future outcome; horizons do not mandate holding periods.

## Collection and diagnosis

Current waves retain seven native books/five USD references within sixteen GETs. A separate bounded job uses scope plus one candle GET, at most 350 bars. Actual manual reconciliation keeps priority; after in-flight work ends, overdue history gets a slot every 30s. Round-robin references/grids, alternating latest/bulk requests and per-reference retry windows prevent global starvation.

Minute/five-minute cache has explicit SQLite closure, identity/digest checks and a separate file. Hourly schema stays unchanged. Partial candles are excluded; missing bars stay gaps. Conflicting closed OHLC requires review, not overwrite. Volume-only changes do not rewrite prices. Shared endpoints differing over 0.2% across grids review the involved grids. An unavailable grid does not suppress others. Exhausted sparse intervals remain SPARSE_HISTORY; bar counts alone are not model readiness.

The supplied e5b8387 capture had native 7/7 and current USD 5/5, stored historical references 1/5, aligned 0, 47 reviews and all 658 rejections FORECAST_HISTORY_INSUFFICIENT. It did not disclose the actual inaccessible local cache cause. Code inspection established low-priority starvation/global retry/rolling-frontier risks; this update corrects those and exposes fixed per-reference bars/pages/alignment/jobs/failures/last-success/review progress without inventing client cache state.

## Selection, native costs and multiplicity

Review fourteen directions across supported horizons. Maker BUY at noncrossing BID/SELL at ASK, with configured tick improvement. Up to eight native sizes obey available unreserved source, signal/error/risk, source fraction, concentration, depth and native min/max/increments. Unaffordable/unjustified minimums HOLD; no forced upsize.

Common Decimal projection computes the after-entry wallet and expected incremental USD, then incremental volatility/concentration risk, forecast uncertainty and separately disclosed resting adverse-selection allowance. Rank positive risk-adjusted USD lower scores, not raw percent. Immediate additionally values credits at USD bids/debits at asks. A limit below an old last price is not profit.

Fixed multiplicity allowance covers 14 directions × 6 horizons × 8 sizes (672). Effective uncertainty multiplier is at least the frozen user setting and a normal Bonferroni-style value with family alpha 0.01. Correlated non-normal empirical errors/model misspecification mean this is **exploratory, not a calibrated confidence guarantee**. No tuning on forward comparison outcomes. Unsupported/nonpositive scores HOLD.

One own native commission enters the wallet per filled leg. Authenticated rate plus declared quote-currency model is not settled currency/precision proof. Canonical settlement quarantines unknowns. No counterparty taker fee, forced reverse fee, prepaid future exit, arbitrary slippage or double-counted entry spread/fee. Risk allowances are not paid fees.

## Construction and historical limits

An ETH-BTC BUY source budget is all-in BTC. ETH base quantity is floored to native increment from `budget / (limit × (1 + maker rate))`. SELL source is ETH; own BTC commission reduces proceeds. Canonical native limits/precision/noncrossing/funding still apply.

Private explanation separates A native sizing/funding pass (not exchange acceptance/permission), B economic scores/reasons at six horizons, C public evidence versus UNKNOWN calibrated fill probability, D shadow-only authority. The inspector cannot submit/cancel/authorize/replay.

Reported November 9 BUY: 0.00496514 ETH at 0.028457 BTC/ETH. Gross from those numbers is 0.00014129298998 BTC; conditional 0.50% estimate is 0.0000007064649499 BTC. Actual unrounded commission/settlement, authenticated liquidity class, original books/rules/funds/queue and screen timezone are unavailable. One reported 65s fill cannot calibrate future fills. Historical economics stays UNKNOWN; no later data enters that recommendation.

## Lifecycle, recovery and performance

Reuse NEW/OPEN/PARTIAL/FILLED/CANCEL_PENDING/CANCELED/UNKNOWN. Defaults: 30s review, 120s assessment, 600s child, 1,800s original campaign, three replacements. Fills/remaining holds reconcile before replacement; original quantity/budget/expiry never reset. Inventory has no exit deadline. See [state machine](INTELLIGENT_TRADER_V1_05.md).

TRADE_THROUGH_QUEUE_V1 needs continuous anchored public prints, strict trade-through, declared queue depletion/participation/rest conditions. NO_FILL_OBSERVATION_V1 infers none. Both are uncalibrated; touch/candle/time/downtime cannot fill. Partial fees apply once on filled quantity, duplicates are idempotent and unknown receipt currency locks instead of retrying.

TrialStore/TrialClock integrity and closure remain unchanged. 168 valid hours persist, excluding offline/stale/partial/paused/suspended periods. Pause remains; original expiry ages during restart. Completion/report freezes, even with zero trades.

Private views show current/original HOLD USD, net USD/%, rolling 1/6/24h changes, drawdown/native fees/losses. New checkpoint display keeps recent eight terminal orders plus every active/unknown order; full immutable intent/receipt evidence stays in the journal. Chart cache ≤ 1,200 points retains original endpoint/full span and recent 25h five-minute detail, thinning only older display points. All recorded marks remain journaled. Counters/funds/fees/active campaign budgets/benchmark are never pruned.

Detailed new-policy decision/horizon/forecast/rejection observation blocks use a lossless canonical-JSON zlib/base64 envelope with byte length and SHA256. `coincat_multi_trader.decode_observation` verifies and restores every Decimal/value, rejecting corrupt or oversized decompression. This avoids repeating large research dictionaries uncompressed throughout the trial. Actual intents/receipts, wallet/fees, checkpoints and old trial records retain their existing formats. A regression measures real event sizes against the unchanged 1 GiB trial limit with observation/review frequencies and a conservative overhead allowance; no storage safeguard is relaxed.

Strict optional public extensions expose fixed codes/counts/readiness/per-horizon reasons/selected/forward/history progress only. No amounts, forecasts, native fees, paths, receipts or IDs. Old snapshots remain valid. Helper remains read-only.

## Paired studies and limits

`verification/multi_horizon_scenarios.py` generates seven fixed synthetic studies for HOLD/24h / multi/naive M15 with identical original wallets, native rules, fees, histories, times and public tape. Ninety seconds conditional execution precedes a withheld 2h path with inventory retained. Projections and actual conditional outcomes are separate. No-fill yields zero advantage/fees; flat/fee-blocked cases HOLD.

Fixed continuation net advantage: +0.75007957 USD for multi/24h; reversal: -5.22051802 USD. Shorter history permits multi H2 while hourly baseline correctly HOLDs. Naive M15 yields +0.66344120/-4.61751904 USD in the corresponding short-history cases. These synthetic 500 USD-portfolio results are not account values or calibrated returns. Two hours cannot mature a 24h forecast. This is a one-leg forward engineering study, not a continuous backtest or proof of selector superiority/profitability.

See [module map](V1_05_MULTI_MODULE_MAP.md), [Windows guide](../START_HERE.md) and [verification](../VERIFICATION.txt). Native Windows/connected acceptance, forecast/queue calibration and a prospective 168h market trial remain pending. Automatic real trading stays unavailable; actual default-ON/manual-click protections remain unchanged.
