# CoinCat v1.05 — multi-horizon change map

| Added modules | Purpose |
|---|---|
| coincat_candle_cache / history_backfill / history_public | Separate closed minute/five-minute cache, fair bounded history and strict public progress |
| coincat_horizon_forecast | Direct short labels/folds/provenance, independent readiness, immediate risk and cross-grid checks |
| coincat_multi_policy / multi_trader | Separate frozen trial, exploratory multiplicity allowance, native projection and prospective outcomes |
| coincat_multi_rejections / multi_public | Fixed per-horizon reasons/counts and amount-free projection |
| coincat_order_explanation / order_explanation_ui | Native source-budget preview and four answers; no order actions |
| multi_fixtures / new multi and explanation tests | Chronology, native math, expiry/recovery, history/closure, privacy and Tk |
| verification/multi_horizon_scenarios.py | Paired synthetic HOLD/24h / multi/naive comparisons |

Modified:

- forecast_history: optional bounded peek; default hourly schema/readiness preserved.
- intelligent_policy: factor existing pure Decimal projection into horizon helper; original 24h caller/numerics retained under existing tests.
- intelligent_source: optional independent forecast bundle over bounded GET-only source.
- maker_shadow: two optional policy hooks for selected-horizon counts/new-trial display cache; other policies retain behavior.
- spot_app: separate trial/cache, shared read-only frames, fair scheduling, checkpoint both on close; actual manual reconciliation stays first.
- intelligent_ui: selector, horizon/history/comparison views and private explanation; main market tabs unchanged.
- monitor / spot_public / monitor_server: strict optional multi/history extensions, compatible old snapshots, read-only display.
- runner / verifier / portable-folder fixture: include new modules/tests, reject duplicate discovery; no safety assertions retired.
- current guides / source builder / manifest / evidence: v1.05 update preserving current data.

No module or historical record is deleted. ForecastHistorySource remains an offline compatibility helper; supported app uses HistoryBackfill. Previously retired controllers stay inactive: see [earlier map](V1_05_RETIREMENT.md).

Actual submit/cancel, grants/caps, native receipt/fee/accounting, FIFO/tax, state/import/security/backups, single-instance, TrialStore/TrialClock and artwork remain unchanged and byte-compared to e5b8387. Shadow modules have no SDK write/preview path. Manual OFF retains explicit real-click meaning.

Only the new trial bounds display caches: recent terminal rows/older chart points, while full immutable journal/intents/receipts, full span endpoints, cumulative counters, benchmark/funds/fees and active/unknown/root-budget state remain. This does not delete financial journals, tax records or old trial history.

New research observation detail is losslessly compressed with a bounded SHA256-checked decoder in `coincat_multi_trader`. No information is rounded away. Receipt/intent/wallet/fee formats and the existing TrialStore cap are unchanged; earlier journals are never rewritten. Full detail remains recoverable for private audit.
