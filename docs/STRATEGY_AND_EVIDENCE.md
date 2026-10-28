# v80.0 strategy and evidence contract

This release implements Milestone A of the controlled Strict Immediate Snowball handoff, renamed v80.0 by the owner. The user's explicit request authorizes a fresh source build, new-key first use and current-tree cleanup; it does not authorize LIVE or connected previews.

## Primary decisions

W is the immediate after-cost affected-wallet value change, including native source residuals and modeled fee debit. L is the comparable hypothetical source-HOLD versus destination-SWITCH USD exit difference. W>0 AND L>0 are required, with no absolute Experimental dollar floor and no favorable-future override.

States distinguish NOT_PRICED, ECONOMIC_NEGATIVE, ECONOMIC_ZERO, MODELED_POSITIVE_UNVERIFIED and STRICT_QUALIFIED_MODEL. Missing evidence retains the positive estimate and its blockers. Size reviews, distinct route/direction observations, time events, qualification and successful RAM posts are separate counts. Unchanged unrelated holdings cancel incrementally; complete portfolio P&L has its own synchronized-coverage gate.

Discovery uses approved available native assets and real listed BUY/SELL directions. It does not require movement or eight prior observations. Quote work remains fair, bounded and rate-limited; complete route dependencies are prioritized. This cannot guarantee observation of every fleeting discrepancy or a minimum profitable trade frequency.

The native receipt implementation is shared by the planner and optional size-aware model. Separate source/destination USD paths use conservative sides and observed stablecoin prices. Circular paths are excluded and valid alternatives retried, with a direct-USD fallback where appropriate. Retained native dust remains explicitly marked; comparable liquidation is not a claim that all dust became cash.

## Milestone A evidence limitation

Immediate discrepancy discovery, modeled positive-opportunity reporting and strict evidence gating. Live-observation strict qualification is unavailable until candidate-sized depth and candidate-specific fee/preview evidence integrations are completed and verified.

Normal app operation cannot opt into synthetic evidence. Offline fixtures can provide explicitly synthetic, frame-matched price levels and candidate-sized fee previews to exercise the real planner/consumer/FIFO/P&L chain. These tests demonstrate contracts, not observed exchange opportunities.

## Separate Milestone B proposal

1. Add bounded candidate-sized depth enrichment using Coinbase GET /api/v3/brokerage/market/product_book. Retain ordered price/size levels and actual timing/provenance; walk the relevant sides and sizes for entry and comparable exits. Truncated depth is not unlimited liquidity. Refresh and recompute a complete frame when evidence arrives.
2. Separately authorize a non-placing authenticated adapter for POST /api/v3/brokerage/orders/preview. This is an HTTP POST although it does not place an order. It must never reach create/edit/cancel or ARM endpoints. Match product, side, order type, rounded size, amount, fee currency and observation time. Numeric commission_total alone does not prove its debit currency; require verified response/contract semantics. Missing or unsupported units remain unqualified.
3. Verify actual connected responses and supported fee/depth semantics without modifying financial records. Account fee tier, ticker BBO, infrequent aggregate depth advisory and optional fields alone are insufficient. Even complete observed books/previews do not prove a future fill or profit.

No Milestone B network execution or new preview traffic is included in v80.0.

## Synthetic acceptance coverage

T01 reference BTC→ETH; T02 both checks/zero/forward override; T03 depth, rounding and fees; T04 static fair discovery; T05 consistent current dependency frames; T06 independent FX alternatives; T07 missing/insufficient evidence retained; T08 native receipts/residuals/limits; T09 partial startup; T10 acquired-coin reuse and failed/replayed posting; T11 funnel/economics; T12 advisory outcomes and prospective unknown/missed causes; T13 worker/STOP/report retention; T14 unconditional broker and no-network boundaries; T15 Python 3.11, complete GUI diagnostics and extracted-release integrity. VERIFICATION.txt records observed results and limits.
