# v1.04 legacy retirement and dependency map

Default entry remains `01_START_COINCAT.bat` → `coincat_start` →
`coincat_launcher` → `coincat_spot_app`. The historical `coincat_app.main` now
forwards to the same workspace; it no longer constructs the research controller.

| Component | Active v1.04 responsibility | Retired / retained compatibility |
|---|---|---|
| `coincat_spot_app` / `coincat_spot_market` | Seven native manual tabs, authenticated GET data, trial UI scheduling | No research allocation/adaptive controller prerequisites |
| `coincat_order_services` | Shared native tickets, owned order binding, inventory semantics, native fill flows, authenticated manual execution services | No automatic-live grant; shadow authorization rejected |
| `coincat_spot_execution` | Durable explicit-click manual lifecycle; separate identity journal | Same blocked startup, caps, unknown-create lock, cancel/partial/remainder behavior |
| `coincat_execution_limits` | Pure unchanged manual cap definition and precision decorator | Re-exported by `coincat_live_beta` for historical callers |
| `coincat_sdk_logging` | Pure SDK redaction filter | Re-exported by old beta controller without importing it in default UI |
| `coincat_trial_store` / `coincat_trial_clock` | Isolated versioned atomic model/clock and restart protocol | No financial tables or legacy session reuse |
| `coincat_shadow_source` / `coincat_portfolio_policy` | GET-only seven-market observation, fourteen native portfolio decisions | Replaces ETH-cycle/.01 admission for this trial only |
| `coincat_shadow_trader` | One hypothetical wallet, proposals, explicit replay settlement and recovery | No old automatic controller or exchange write client |
| `coincat_trial_ui` / `coincat_tray` | Private 168-hour dashboard and native Windows tray | Manual layout/transparent logo retained |
| `coincat_paper_public` | Pure frozen legacy monitor projection | Removes monitor dependency on old automatic paper manager |
| `coincat_monitor` / server | Strict optional shadow aggregate extension; existing manual/imported counts | Retains older v3 extensions for archived workflows |
| `coincat_fee_audit` / local audit tool | Day-scoped statement/API evidence; saved-key GET-only collector | Does not rewrite raw fees, tax records or future settings |
| `coincat_auto_paper`, beta controller/UI, old workspace | Not imported by default Manual Spot entry | Historical tests, explicit replay tools and private journals preserved |

The default import graph excludes `coincat_live_beta`, `coincat_beta_controller`,
`coincat_beta_ui`, `coincat_auto_paper` and `coincat_workspace`. Shared limits,
logging and legacy public projection were extracted instead of importing an
execution controller to obtain small utility functions. There is no new broker
with guessed fee units or a second independent native settlement calculator.

Protected financial/FIFO/state/transfer, key, import/lot/lock/single-instance
code, locked dependencies and artwork remain unchanged from the published base.
Historical presentation expectations advance to v1.04. The portable-verifier
fixture also copies the two new modules inspected by its AST checks; its original
assertions and all financial assertions remain intact. No private journals, tax records, backups, reports,
monitor credentials or uploaded evidence are packaged or deleted. Storage cleanup
remains report-only. Old historical identifiers are compatibility names, not
requirements to install an old release directory.

Manual and trial authorization remain separate. The shared write service accepts
only a consumed per-click manual grant while its manual journal is SENDING.
It rejects shadow grant types before reaching the SDK. Unknown manual creates
remain bound to their original CID; retries are not introduced by extraction.
No autonomous live authorization, automatic real submit/cancel, taker fallback,
forced ETH liquidation or unattended pilot is implemented in this patch.
