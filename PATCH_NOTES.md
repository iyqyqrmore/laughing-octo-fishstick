# CoinCat v90.1 — research measurement and reporting

Based on clean v90.0 commit b32a539c29bb5b1b9e8ffb61e25c5cc7f5340597.

- Link urgent discovery and Experimental consumer by process-unique cycle ID and separate observation timestamps.
- Reconcile cumulative submitted, pre-consumer rejected and reviewed sizes within each manually armed session. STOP retains totals; a new ARM starts fresh.
- Measure each eligible product/direction's selection, evaluation and last complete modeled pricing frame. Export distinct directions/events over 60 seconds, never-complete and overdue counts, and market-quote breakdowns.
- Keep selected directions with no costed receipt separate from unpriced costed routes and from size outcomes. All sizes are measured before display truncation.
- Identify archived advisory comparisons and Validated-track dollar floors separately from primary immediate W>0 AND L>0 policy.
- Timestamp readiness and health sections and preserve stale, missing and clock-conflicting heartbeat observations.

No path-selection, economic, funding, risk, fee, financial-schema or live-order policy changes.
Connected depth/fee evidence, alternative-path fallback and manual real execution remain pending.
See docs/V90_1_REPORTING_PATCH.md for definitions and tests, and docs/ENGINEERING_REFERENCES.md for public references.
