# Copy/paste this as the first instruction to Codex

You are reviewing **CoinCat v70.0** in this folder. Before editing any source, read `AGENTS.md`, `CODEX_HANDOFF_V70.md`, and `START_HERE_V70.md` in full. Treat them as project requirements, not authorization to trade. This is a clean baseline of the v60.18 trading behavior, not a new certified live engine.

1. Verify SHA256 release integrity and run the isolated regression suite on Windows Python 3.11. Distinguish offline/synthetic and Windows-connected verified results. Investigate any failure; specifically check the historical UTF-8 mojibake issue around `SNOWBALL • COST & USD ADVANTAGE`. Do not merely relax the regression.
2. Map and audit the existing flow: WebSocket rising alerts → bounded between-scan authenticated REST book checks → one planner/fee screen → Snowball immediate-USD comparator → Experimental/Validated SHADOW → 18-section diagnostics; identify performance bottlenecks and false positives using measured latency.
3. Investigate experimental wallet vs frozen HOLD reporting `NOT VERIFIED - FX MARK MISSING` even when Coinbase portfolio valuation coverage is otherwise complete. Write a deterministic multi-conversion regression before implementing a fix.
4. Review the **remaining LIVE blockers** (multi-currency atomic FIFO, original tax lots, Coinbase fee currency/partial fills, ambiguous POST idempotent recovery, independent portfolio loss floor and verified execution costs). Produce a prioritized audit with PASS/BLOCKED/NOT VERIFIED gates, implementation plan, and tests.
5. Keep Coinbase order POST unconditionally **BLOCKED**, all real modes DISARMED by default and all private user financial data untouched. Don't place orders, rotate the user's coins, or make external calls with private credentials without direct, explicit authorization.

**Deliver first:** a concise code map, Windows test results, evidence-backed bottlenecks, and a small proposed patch plan. Do not implement a rewrite or enable real trading without explicit user approval.
