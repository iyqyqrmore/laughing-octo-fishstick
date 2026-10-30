# Research Scheduler & ETH Synchronization Patch

Read-only follow-up to `4c3a4c0c459adb1a3cfc419924c2a1cca16d3ee7` on
`coincat-eth-farmer-design`. CoinCat remains a v91-based immediate USD-W scanner,
not a validated ETH-profit selector. No production settings, private records,
native holdings, orders, previews, transfers or reserves are changed.

## Admission before observation

A proposed research observation now needs capacity for **all three** future
5/15/60-minute quote jobs before entering RAM. Each job must fit its existing
120-second observation window and the six-book research share. The forecast
charges complete fixed dependency sets, including ETH-USD when listed, with
shared products deduplicated within a service slot. It assumes the manual scan
pause plus the entire six-second collection deadline and one second of margin.
Three interleaved horizon turns leave room for fair service. This is a
conservative capacity forecast, not a guarantee of future connectivity/liquidity.

Reservations are atomic across all horizons. Existing commitments are
reforecast at the actual manual cadence. A failed conservative forecast blocks
new admissions; it never retroactively reclassifies an admitted observation.
Unusable current dependencies, transport errors/backoff, stale proposals,
excess dependency work, forecast saturation and the existing 512-row RAM limit
produce explicit **not admitted** decisions. These never become pending samples
or future misses. Source/destination direction order rotates independently of W;
the Lab never selects a trade or changes scanner decisions.

One distinct admission review is defined per direction per 300 seconds.
Repeated reviews of a refused observation increment a separate attempt counter,
not the distinct count. The decision ledger expires inactive entries and has a
4096-entry bound. Overflow is reported as untracked attempts rather than claimed
distinct observations. These are correlated reviews, not independent samples.

## Deadline fairness and failure evidence

Earliest expiry remains the normal priority. After two unserved passes, a
horizon receives a protected turn; EDF still orders jobs within that horizon.
This lets a larger hourly group run before short-window jobs consume all usable
space. The adversarial test keeps short-window work continuously due and proves
hourly service by the fourth pass, within 36 simulated seconds at default cadence.
Failed jobs have a bounded next-service delay instead of retrying every pass.

The same single collector still permits at most **16 books overall and six for
research**, four workers, 0.2 seconds between GET starts, a six-second collection
deadline and the existing server Retry-After backoff. Price age remains 30 seconds,
spread acceptance remains 0.25%, and synchronization remains **12 seconds**.
Quotes before a research horizon, circular/favorable replacement paths, missing
data and expired jobs cannot become completed negative outcomes.

Internal per-product error-class/status metadata attributes transport failures
without retaining response bodies or exception messages. Exports distinguish
distinct scheduled/deferred observations from service-pass attempts, completion,
misses, latest terminal blockers and actual failed-attempt causes per horizon.
A successful USD comparison with a missing ETH reference remains a USD completion
and a separately unpriced ETH comparison, with its own reference failure cause.
One shared GET can serve multiple correlated observations; job attempt counts
are not HTTP request counts or independent samples.

Scheduling evidence is committed only after the collector's STOP check. Frozen
per-scan diagnostics avoid mixing scheduling counters from another scan with
the displayed price snapshot. The same eight diagnostic sections remain, with
counts, timing and controlled reason codes; observation IDs, quantities, keys,
account IDs and private paths remain excluded. Lab notes stay plain text; full
telemetry is available in Export diagnostics.

## Coordinated ETH observations and allocation limits

ETH-USD, listed return-to-ETH routes and necessary USD marks are requested as
complete dependency groups, chosen without profitability inspection. The canonical
route topology is enumerated without fabricated prices. A complete account group
is preferred when it fits the remaining overall budget. Otherwise a single
per-asset group rotates through supported assets, always including ETH-USD.
These requests share the existing sixteen-book collector, after the research
allocation. Actual returned quote quality and timestamp span are checked; a
selected group is not automatically a synchronized measurement.

All price-quality rules and the canonical receipt remain unchanged. A large
account may require more books than can be obtained coherently under these limits.
Unsupported assets, unconverted dust, product restrictions and missing/skewed
quotes keep the complete ETH total **UNKNOWN**. Partial groups/subtotals are not
summed into a fabricated complete portfolio. Diagnostics separately report
known dependencies, structurally unsupported assets, selected-group timing,
actual synchronization and full-measurement state.

The measurement still covers **account-available assets**, excluding existing
explicit exclusions. It is not a reconciled CoinCat-only working allocation.
Manual/protected/settled/earned ETH and a cashflow-adjusted baseline stay UNKNOWN.
In particular, refreshing quotes cannot resolve 27 unconverted holdings by
inventing values or reclassifying them as bot capital or earned ETH.

## Unchanged economics and controls

The mixer and passive settings-advisor files match the preceding commit exactly.
The proposed $10/$20/$10 reserve class/calculator also retain their original source
and semantics. Only the existing manual scan interval is passed into the capacity
forecast; no control is changed automatically. USD ranking, native full-source
sizing, exclusions, fee-once accounting and all protected financial modules remain.

The observed 0.9% taker estimate and 0.15% modeled slippage per leg imply roughly
a 2.1% two-leg cost hurdle before additional spread/depth effects. The canonical
Decimal receipt applies actual compounding, rounding and residual rules. This patch
does not introduce that approximation as a threshold, reduce costs to invent an
edge, relax positive-W requirements, or claim fills/profit from future comparisons.
LiveBroker.submit retains its unconditional first-statement block.

## Synthetic evidence

The deterministic three-hour replay feeds nine initial product quotes plus
ETH-USD per twelve-second turn across 844 constant-price synthetic products.
Research uses the same six-book share. Unique requested products never exceed
fifteen per turn, below the sixteen-book limit. Proposals use the canonical
full-source calculation. The baseline was run from the exact preceding commit;
its aggregate fixture results are included for reproducibility.

| Matured admitted observations | Previous completed / missed | Updated completed / missed |
| --- | ---: | ---: |
| 5 minutes | 912 / 624 | 1469 / 0 |
| 15 minutes | 905 / 631 | 1387 / 0 |
| 60 minutes | 464 / 565 | 1012 / 0 |

The updated replay considered 8109 distinct admission candidates, admitted 1524
and explicitly did not admit 6585. Future-pending and not-admitted candidates are
excluded from completion-rate denominators, not silently counted as successes.
Raw RAM-capacity deferral attempts fell from 6568 to 3549 (about 46% fewer); the
maximum pending queue was still 512. Admission reduces predictable overload; it
does not eliminate all refusals or imply that the whole market was observed.

This is a healthy, deterministic synthetic load fixture with correlated constant
prices, not a connected benchmark or guarantee of 100% live completion. Separate
tests exercise outages, actual error attribution, repeated deferrals, changes of
cadence, hourly contention, oversized/missing ETH groups, STOP, redaction, and the
unchanged mixer/reserve/advisor. Windows/DPAPI, account semantics, execution depth,
fee currency, fills, production recovery, live performance and profit are unverified.

Reproduce in the prepared environment:

```sh
cd /workspace/laughing-octo-fishstick
.venv/bin/python -B VERIFY_SOURCE.py
PATH=/workspace/.local/usr/bin:$PATH xvfb-run -a .venv/bin/python -B tools/RUN_OFFLINE_TESTS.py
git diff --check
```

Tests use Python 3.11, hash-locked dependencies, disposable synthetic state and
HTTP forbidden during discovery/execution. Source-only packaging and independent
ZIP checksums exclude private data/backups, uploaded diagnostics, credentials,
environments, logs and bytecode. GitHub's generated ZIP has different container
metadata from the locally packaged ZIP; verify extracted source with its manifest.

Observed complete validation: **141 discovered / 141 distinct / 141 run**;
0 failures, 0 errors, 0 skips and 0 expected failures. This retains the prior
120 cases and adds 21 admission, fairness, transport, ETH-group and privacy cases.
Actual Tk controls, STOP, eight-section diagnostics, source syntax/integrity,
financial quantity/FIFO guards and offline SDK signing remain covered. The
separate 844-direction rotation fixture covered all directions over 55 passes /
432 simulated seconds, with only 64 currently priced at the end; historical
coverage is still not fresh coverage.

Fourteen protected/economic/control/lock files were compared byte for byte with
the preceding commit. The reserve class/calculator's original source segments
also match; their test hashes are independent of Python AST schema versions.
Transport budget, pooled TLS GET and quote-fetch bodies are unchanged; collection
changes retain only error-class/status attribution. The regenerated source
manifest contains 98 entries; the source ZIP contains 99 files including the
manifest. Publication is source-only on the existing development branch.
Environment activation and validation in a newly restored task remain separate.
