# CoinCat v70.6.1 — preserve stopped SHADOW diagnostics

Stopping the experiment preserves its modeled wallet, counters and last marks
in RAM. The combined diagnostics should include those results while disarmed.
This maintenance patch repairs a reporting failure; selection and trading
behavior remain the v70.6 rules. **LIVE POST remains unconditionally blocked.**

* A disappearing SQLite WAL/SHM or other transient file can raise FileNotFoundError
  between the report's file-existence check and size read. The old combined
  SHADOW generator discarded its entire output when its last storage check failed.
  Reproduce this deterministically using a synthetic WAL removed between reads.
* Retry storage metadata once, inside diagnostics only. No invented zero usage,
  repeated polling, network requests or change to financial/storage gates.
  A persistent error remains explicitly unavailable.
* Collect route research, Snowball, experimental wallet results, passive forward
  learning, strategy observations and decision/storage as separate subsections
  within the existing SHADOW section. A failed subsection cannot discard the
  successful results. The parent report remains INCOMPLETE when any part fails.
* Isolate passive learner queries from the experimental wallet report. A research
  query failure cannot hide retained conversion counts, fees and value vs HOLD.
* Include only vetted code basename/function/line breadcrumbs for export failures,
  without exception messages, paths, locals, balances or account identifiers.
* Label the validated SHADOW stop reason separately, identify whether an
  experimental session was previously started, and include latest cost-selection
  and passive-update counts in the health section as additional context.

A synthetic disappearing-file regression now completes with the retained wallet
report. Persistent storage, research and route-report failures preserve other
results and correctly flag the export incomplete. The complete offline suite,
GUI export, source/ZIP integrity and unchanged trading arithmetic are checked;
see VERIFICATION.txt. The uploaded failure's exact code origin was absent from
that older report, so this reproduction does not uniquely prove its PC-side cause.

If your v70.6 app is still open with results, export again while disarmed before
closing or re-arming. Re-arming resets the modeled session; restarting loses
session RAM. Passive public learning persists separately in the research DB.

Use START_HERE.md to install this full source in a clean folder and import the
currently active complete private_data. No real financial data, lot IDs, schemas,
keys or settings were changed. All positive approved native funding, acquired-coin
reuse, current-cost scenarios, scan speed, budgets, fees and LIVE blocks are retained.
