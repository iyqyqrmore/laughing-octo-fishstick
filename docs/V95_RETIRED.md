# v95 retirement inventory

Source checkpoint: `8b5d2c168376d339f4ede372f24de3cff3667aaf` and independent
source archive preserve the previous build. No private data or backups removed.

Retired from the active build:

- `app/coincat_passive_lab.py`
- `app/coincat_research_admission.py`
- `app/coincat_settings_advisor.py`
- `offline_tests/test_quote_coverage.py`
- `offline_tests/test_research_scheduler.py`
- `offline_tests/test_v91_passive_lab.py`
- `offline_tests/test_v92_cycle_integration.py`
- `offline_tests/research_replay.py`
- `offline_tests/research_replay_baseline.json`
- `offline_tests/deadline_contention_baseline.json`

The broad legacy Scanner.scan orchestration and select_books deadline scheduler
were removed. Pure full-balance/canonical arithmetic and 3–5-leg ETH-cycle
libraries/tests remain secondary source capabilities. The old multi-horizon
experiments, giant dashboard, cycle dashboard and their UI assertions are obsolete.
Shared GET-spacing/backoff/error-redaction regressions were carried into
`test_v95_transport.py`. Protected-file byte checks remain in release-core tests.
Allocation/editor and native-model safeguards remain; a legacy editor-scroll
assertion now checks actual accessible content because the shorter v95 shell no
longer necessarily needs outer scrolling at minimum size. No failing economic or
financial assertion was relaxed. Current behavior is tested by the v95 suite.

Current source docs replace superseded v80–v92 release/planning narratives; all
historical docs remain in Git. Redundant 630/720/930/1100 banners were removed;
the original 520 banner and Windows icon remain. Historical module/DB identifiers
are compatibility names and are intentionally retained.

Retained cases were renamed to current-purpose modules: test_v95_release_core,
test_v95_installation, test_native_receipts and test_eth_cycle_evaluator. The
old scanner/GUI module became gui_fixtures (no obsolete tests discovered there).
The original 189-case baseline is preserved in its log; v95 has a different,
explicitly scoped 152-case suite, including 32 direct-growth/transport cases.
