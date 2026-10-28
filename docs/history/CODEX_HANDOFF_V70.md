# CoinCat v70.0 — Complete Codex Development Handoff

**Date:** 27 October 2026  
**Owner's objective:** Continuously improve the TOTAL authorized/enrolled Coinbase spot portfolio USD value by opportunistically rotating between any eligible directly traded coins, with one exchange order per conversion. **Never equate more trades with more money.**  
**Status:** Fresh v70.0 *source-development baseline* of verified v60.18 behavior. NOT a live trading release. New v70 file names/isolated state path are for Codex onboarding; **LIVE POST remains BLOCKED**. No significant new trading strategy was introduced in the v70 version bump. No guaranteed opportunities, wins or profits.

## 1. Start here, engineering invariants

- Prioritize **immediate independently measurable USD HOLD vs SWITCH advantage**, accounting for fees, spreads, slippage, source/destination size increments and residual holdings. An apparent gain is NOT realized arbitrage unless achievable on executable depth, with synchronized bids/asks and full round-trip liquidation comparisons. Treat mismatched or stale marks as unverified, not profit.
- Preserve a **single canonical Coinbase Advanced Trade SPOT product registry, REST bid/ask store, route planner and broker path**. All catalog-eligible direct products (USD, USDC, USDT, BTC, ETH etc. quote assets) may be discovered and ranked; do not artificially restrict to 24 on-chain EVM swap pairs. No mandatory USD bridge. BUY and SELL are the book side chosen for *the same one-order asset conversion*.
- Portfolio holdings are **funding inventory**, not the universe ranking. An eligible enrolled available balance can be used up to its verified liquid amount (subject to fees, exchange product rules and explicit future LIVE limits); the candidate-size planner examines 10/25/50/75/100% and dollar sizes. Preserve user exclusions, staked/locked/reserved restrictions, precise Decimal, and tiny dust.
- The discretionary 10% BUY reserve and the misleading $5 ordinary SELL research cap were removed in v60.17/v60.16. Do not reintroduce them. Do not remove actual Coinbase order minima, data integrity rules, no-overdraft checks, or safeguards.
- **Experimental SHADOW** (v60.13+) is isolated, in-memory, unvalidated what-if trading. It can bypass seven-day historical evidence for *hypothetical* fast momentum and strict immediate-advantage candidates, but may still reject cost-inefficient trades. Records modeled FIFO and 5/15/60-minute outcomes. **Validated SHADOW** keeps independent chronological held-out requirements. Neither submits real orders, and neither grants LIVE authority.
- **AI Lab learning is retrospective/advisory**: score observed real later outcomes, losing scenarios, model-vs-HOLD performance; do not let the seven-day training gate stall fast experimental research. Minimum validated evidence historically: 35 independent hourly windows over 7 calendar days, chronological out-of-sample; do not misrepresent correlated training labels as independence. GPU is observe-only.
- Source Windows Tkinter application: Windows 11-class PC, Python 3.11.9, 16 logical AMD Ryzen CPU threads, NVIDIA RTX 4060/CUDA, SQLite, Coinbase Advanced Trade REST/WebSocket, single-process lock. A source-only, no EXE build.
- **Unconditional live broker block:** `app/coincat_live.py` `LiveBroker.submit` must start with a `raise LiveBlocked(...)`. Do not alter or bypass this. LIVE remains DISARMED by default. No live POST pilot without separate reviewed evidence and the owner's explicit later authorization.
- Preserve the owner's **real ledgers** (private `$APPDATA` files), existing acquisition/disposal history, tax-basis unknown flags, enrollment, DPAPI-protected credentials, and legacy performance baseline separate from tax cost. No source release ZIP should contain private databases, `.venv`, raw credentials, logs or API keys.

## 2. Where we are now — version history and active architecture

- v60.10: authentic full catalog with paginated Coinbase product eligibility and unlisted-pair exclusion. One direct order per rotation. `coincat_v6010_registry.py`, `coincat_rotation_autopilot.py`.
- v60.11.1: fixed ordinary BUY research screen erroneously assuming 2 orders: `research_screen(..., legs=1)`; 0.9% account taker + 0.15% assumed slippage = 1.05% per direct conversion **before spread**. A separate *later* exit incurs another real fee. Fees must not be double deducted from planned receipts or HOLD/SWITCH estimates.
- v60.12: History percent = maturity, not win rate. Decision labels Small, Costs, USD?, Hold, S.Ready. Unlisted pairs must not masquerade as valid conversion routes.
- v60.13: Experimental SHADOW independent modeled FIFO with no network POST. Separate wallet and outcomes. **Some FX marks missing in experimental wallet P&L**; see issue list.
- v60.14: ranked rising-market scout, falling-market capacity retained for SELL, dynamic destination shortlist ~4–12. Earlier absolute momentum ranked plunging coins ahead of rising coins; corrected. Broad discovery remains.
- v60.15: strict Snowball immediate USD comparison using synchronized conservative REST bids/asks; experimental entries can use strict positive dollar estimate or independent provisional momentum; one-order advisor replaces 2.13% round-trip display.
- v60.16: ordinary SELL/HOLD preview uses min(enrolled quantity, verified available balance), rather than legacy $5 cap; crypto-quote per-asset checks. Main planner already considered full source inventory.
- v60.17: removed extra discretionary 10% BUY-side reserve; still count modeled fees, precision, market rules and available inventory.
- v60.18: bounded between-scan `FAST SNOWBALL` WebSocket alert → at most 16 REST books, up to 3 fundable candidates, ~15-second attempted interval when worker available, 45-second unchanged-alert cooldown → **same** planner + both SHADOW tracks. Not a guaranteed 15-second trade cadence, not professional HFT.
- v70.0: clean Codex-ready source based on the above. Version identity upgraded; no LIVE feature unlocked; compatibility module names, fixture data contracts, and SQLite schema intentionally unchanged.

Flow: authenticated Coinbase products + enrolled balance ledger → broad public WebSocket ticker_batch/heartbeat scouting → bounded urgent or adaptive focused authenticated REST bid/ask fetch → one `coincat_rotation_autopilot` planner through `coincat_v605_shadow_bridge` → strict Snowball comparator `coincat_snowball.py` → experimental/validated FIFO -> 18-section read-only combined diagnostics + AI Lab learning. **WebSocket last trades are discovery only, never order execution prices.**

## 3. Latest actual user diagnostics supplied (v60.17, 2026-10-27 22:36:15 UTC)

This file is earlier than v60.18's new FAST path. It therefore establishes the **pre-fast-path benchmark**, not proof of new v60.18 performance. Export had **18/18 complete sections**. Summary:

| Observation | Latest reported |
| --- | ---: |
| Authenticated eligible spot markets | 811, from 929 raw products |
| Fresh public changed trade tickers | 427, WebSocket connected and heartbeat fresh |
| Deep studied in last scan | 96 pairs, REST quote errors 0 |
| Distinct observed quote pairs within 24h | 720 |
| Strict-price eligible enrolled funding assets | 16 / 23 reviewed, 7 withheld for stale/wide USD books |
| Latest route checks | 1,053 attempts, 86 cost/size-feasible, 967 blocked |
| Last displayed modeled routes | 12; **12 immediately negative after costs** |
| Strict Snowball synchronized, comparable routes | 2 / 12; 10 missing/stale books |
| Positive Snowball immediate-estimate routes | **0**; best delta approximately **-$0.00195** |
| Experimental SHADOW FIFO conversions | **2** hypothetical one-order receipts (not real Coinbase fills) |
| Experimental modeled exchange fees | ~$0.3126 |
| 5-minute experimental outcomes | 2 matured, **both negative**; 15-minute: 1 matured, negative |
| Experimental portfolio USD vs HOLD | **NOT VERIFIED — FX MARK MISSING** |
| Independently validated full-portfolio forward alpha | **0** |
| Production multi-currency POST | BLOCKED |

**Interpretation:** The two FIFO conversions establish the experimental trade plumbing, NOT a profitable system. Both observed 5-minute follow-up outcomes were negative. The experimental net-portfolio comparison is missing a USD mark. The 12 displayed routes lost immediate value; no independently verified immediate Snowball opportunity was found in that snapshot. Public WebSocket stream conditions were relatively healthy; quote freshness for synchronized Snowball comparison needs attention.

## 4. Windows verification incident — user-supplied v60.18 log

User reported: source hashes **162/162** passed, Python syntax and GUI smoke passed, but **offline suite failed 1/268**:

```
FAIL test_v6015_snowball.SnowballResearch.test_source_matches_single_engine_and_gui_label
assertIn('SNOWBALL • COST & USD ADVANTAGE', src)
```

The failure log includes local installed `coincat_app.py` source where the Snowball heading is **mojibake** `SNOWBALL â€¢ COST & USD ADVANTAGE`, although the original v60.18 full-source ZIP packaged in this chat contains correct Unicode `SNOWBALL • COST & USD ADVANTAGE`. The old Windows verification was **NOT ALL PASS**, despite hashes reporting pass. Treat as an encoding/mixed-install incident pending diff of copied files, use clean v70 folder and test exact bytes, manifest, and on-Windows `unittest` before working further. Never remove the assertion just to hide corrupted source. Do not declare Windows verification passed until the user runs it.

## 5. High-priority actionable engineering backlog for Codex

1. **Prove valuations**: experimental FIFO USD mark missing despite portfolio 23/23 holdings valued; include virtual newly acquired assets in fresh synchronized REST USD price requests, trace FX missing by category without private amounts. Never silently value them at zero, never invent data. Ensure HOLD and switched wallets use precisely same timestamp and conservative liquidation rates. Test trace across multiple hypothetical sequential conversions.
2. **Prove live order pipeline**: production cross-currency FIFO accounting with exact fee asset/unit, cost-basis preservation, full/partial fills, canonical idempotence, paginated Coinbase order reconciliation, ambiguous-submit/crash/power-loss recovery, independent portfolio-wide USD loss floor. Synthetic tests alone do not unlock LIVE.
3. **Audit FAST SNOWBALL under actual Windows loads**: latency percentile (alert age, REST request time, latest book skew, planner time, SHADOW accepted/rejected), API rate limits and UI responsiveness. Ensure urgent path truly invokes the canonical planner and is not silently skipped by busy full scans or duplicates; throttle/backoff gracefully.
4. **Trading economics**: only label *immediate* advantage after synchronized, conservative, executable-side USD liquidation and all conversion fees/spread/slippage, depth/partial-fill sensitivity; distinguish marked value, realizable liquidity and realized P&L. One-order route fees are charged ONCE; a later actual exit is another order and may incur additional costs.
5. **Decision funnel**: detected upward alerts → available source/destination direct pair → REST books fresh → eligible size → actual source fee + spread → positive immediate advantage or independent provisional momentum → experimental FIFO. Report typed rejection counts; distinguish event alert vs full scan, no duplicated candidate counting.
6. **Forward evaluation**: record what would have happened if all nonexecuted top proposals were taken, benchmark against same-time HOLD at 5/15/60m with survivorship guards, no lookahead. Continuous after-cost, sample-size-aware readout, confidence intervals, catastrophic slippage cases. False positives and adverse selection matter more than maximizing trade count.
7. **Review other bottlenecks**: stale/vs verified catalog, quote data and 8-observations/12-minute ordinary BUY gating; 45min research cohort (not a block on urgent path); 5% broad stream acknowledgment vs requested subscriptions; GPU startup stalls; UI progress bars showing 0 despite active research. Remove only demonstrably redundant *research* restrictions, never market/risk or reconciliation gates.
8. **Security/reproducibility**: move source into version control (ignore private data, `.venv`, credentials); readable `README`, `AGENTS.md`, pinned dependency hashes if possible, module boundaries, deterministic fixtures. Keep Python 3.11 compatibility and one 18-section diagnostics button.

## 6. Acceptance criteria, before any later LIVE review

- Green: Python 3.11 parse and deterministic offline test suite, GUI smoke, SHA256/ZIP integrity, no private state writes during verification, clean Windows run and durable application startup.
- Green: Complete individual USD fund/fee marks with stale/missing/restricted states explicit, one-order receipt/fill mathematical reconciliation, independently observed HOLD vs SWITCH performance.
- Green: local Coinbase **read-only** product/order/fee/preview coverage with explicitly authorized GETs, precise increments/minima, no assumptions from synthetic evidence.
- Green: production ledger parity (both old and new lots) exact Decimal, fee-unit settlement, crash-safe intent/ack/recovery, partial-fills, paginated history, no duplicate/excess orders, independent portfolio loss-floor FAIL CLOSED.
- Green: later reviewed positive after-cost results and supervised bounded pilot proposal with explicit owner approval. Keep all-spot POST disabled until *every* required gate is certified; do not let Codex change that during the initial audit.

## 7. Codex workflow and user collaboration

**First Codex task:** inspect the repository and `AGENTS.md`, verify the source manifest, create a local git repository without private credentials, and run the full isolated suite. Summarize anything unverified separately from observed results. Do not modify the production source/state until a diff+test plan is approved. Then prioritize reproducible fix to experimental missing USD mark and FAST path latency/coverage evidence. All changes via small reviewable commits/patches and deterministic tests; the user's strategy questions continue in ChatGPT.

**Windows development:** use a dedicated folder (example `Desktop\CoinCat_v70`) and a fresh `.venv`, never extract over v60. On first launch copy verified private state *only after confirmation*, using the v70 launcher, into `%APPDATA%\CoinCatV70`; v60 stays untouched. For pure Codex tests, set `COINCAT_DATA_DIR` to a disposable temporary directory; never pass live keys to CI or remote sessions. The v70 source intentionally retains historical internal filenames and v60-state marker **format** for backwards-compatible source/SQLite handling; this is not an order authorization.

**Final reminder:** CoinCat is research software, not a licensed HFT firm; actual profits are uncertain, and rapid rotation can worsen after-fee outcomes. Never state experimental FIFO receipts or historical observations are real successful trades.
