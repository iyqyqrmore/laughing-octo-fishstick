# CoinCat v1.05 decision and authority chain

`coincat_start → coincat_launcher → SpotApp` loads Manual Spot and independent 24h / multi shadow identities. No legacy automatic controller/live dispatcher initializes. Authentication creates a client, not an automatic grant.

One worker prioritizes actual owned manual reconciliation. After in-flight work, overdue history gets a bounded 30s scheduling opportunity; other slots handle native/portfolio/manual display and history. A native wave uses at most 16 paced GETs: scope, fee/account if due, seven books, five USD refs and public trades for one active pair (rotated if both trials need tapes). History uses separate bounded pages; cached quotes never become fresh executable quotes through display.

ForecastHistory retains DIRECT_24H_ANALOG_V1. CandleCache adds DIRECT_SHORT_ANALOG_V1 with chronological direct labels and independent readiness. ForecastBundle verifies shared closed endpoints, keeping gaps/corrections for review. Immediate uses synchronized current references, actual limit, after-fee wallet and disclosed rest risk.

IntelligentPolicy retains 24h; MultiPolicy ranks supported six horizons × 14 directions with bounded native sizes and fixed exploratory multiplicity allowance. Both use common canonical one-leg projection and require positive supported after-cost risk-adjusted advantage. USD references are not extra order markets.

Each MakerShadowTrader has one finite shared wallet/local order. Reservations, partials, UNKNOWN, original budgets/expiry/retries and fee-once settlement reconcile before replacements. TrialStore/Clock preserve original HOLD/168 valid hours. Switching views does not start/reset/migrate. Independent live trials are unpaired.

OrderExplanation privately previews source budget→native ticket, economics, conditional execution and authority. No submit/cancel/replay/grants. Missing original historical data stays UNKNOWN.

Actual manual path remains ManualExecution→LimitOrderServices with default-ON block, explicit-click nonce, permissions/caps/freshness/precision/reconciliation and unknown POST lock. Manual OFF never grants automatic real authority. New shadow modules have no SDK write adapter.

Strict public projections→monitor validator→read-only localhost helper expose fixed facts/counts. Amounts/forecasts/IDs/receipts/paths stay private. Old viewers never resume controllers. See [module map](docs/V1_05_MULTI_MODULE_MAP.md), [multi policy](docs/MULTI_HORIZON_V1_05.md) and [24h baseline](docs/INTELLIGENT_TRADER_V1_05.md).
