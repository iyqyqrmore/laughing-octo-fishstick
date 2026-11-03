# CoinCat v1.01 — Auto Maker Rotation, PAPER ONLY

Start one bounded simulated ETH portfolio from the normal scanner workflow.
Seven product tabs expose fourteen directions, with shared inventory/reservations,
post-only paper orders, partial fills, patient ETH returns, qualified rotations,
HOLD and persistent restart reconciliation. Default kickoff is the explicitly
chosen ETH→BTC SELL; there is no requirement for a profitable cycle forecast.
Automatic paper opt-in starts off. A saved checkbox never resumes on relaunch.

For a new paper session, **Session settings → Order policy → Short-lived / net
ETH target** offers 120-second orders, bounded market-move cancellation and a
fresh decision after confirmed cancellation. It keeps the net ETH target;
unavailable targets mean HOLD with visible exposure/losses. Replacements use
the existing order budget and retain the original campaign/session deadline.
Patient target remains the default; existing sessions are not reconfigured.

The existing chart, mixer, manual allocation, journal, read-only research, local
monitor v3 and larger transparent upper-header logo remain. No actual orders,
authenticated previews, transfers, financial records or real allocations change.
LiveBroker.submit still raises LiveBlocked immediately.

The current data is BBO, without sized queue/depth. Simulated executions use
clearly labeled seeded stress assumptions with delay, sustained strict quote
penetration, synthetic queue depletion and partial/non-fill behavior. A touch
alone never fills. This is an uncalibrated PAPER experiment, not exchange
matching evidence or a demonstrated profitable predictor. Open marked losses,
fees, idle/reserved funds, unknown valuations and missed horizons remain visible.

Read [START_HERE.md](START_HERE.md), then
[the paper trial, defaults and policy](docs/AUTO_PAPER_V1_01.md).
[Independent feedback](docs/AUTO_PAPER_FEEDBACK.md) explains the objections;
[VERIFICATION.txt](VERIFICATION.txt) records actual checks and platform limits.
The source base is published v100 commit ebe4fd7. The owner authorized committing
and pushing the completed build as v1.01; installation and deployment remain separate.

**Paper gains are simulated and never account profit. NO DEMONSTRATED EDGE.**
