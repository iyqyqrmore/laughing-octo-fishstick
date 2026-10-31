# v92 Phase 1 — native ETH cycle evaluator

Local successor branch: `coincat-v92`, checkpoint e0c9b35. The existing installation,
USD scanner, GUI, financial modules and release identity are unchanged. This is
an isolated callable research module, not a completed v92 release or connected
GUI feature. No commits, source pushes, environment publication or orders occur.

`app/coincat_eth_evaluator.py` provides `enumerate_cycles`, `evaluate_cycle`,
`rank_cycles`, and the quantity-free `public_cycle_report` projection. No client,
credentials, network requests, financial writes or execution adapter are used.
Callers supply an eligible product catalog, verified product rules, quotes,
observation times and a proposed exact Decimal ETH amount. Passing such inputs
is not proof of independently reconciled funding or exchange settlement.

Enumeration starts/ends in ETH, uses 3–5 legs, repeats no intermediate asset or
product, and fixes ETH as the root to remove rotation duplicates. Reverse cycle
orientations remain distinct because bid/ask direction and economics differ.
Two-leg immediate reversals and retracing tree walks are omitted. Deterministic
limits bound cycles and search expansions; truncation is explicit and never
claimed as exhaustive market coverage. Longer cycles remain outside this model.

Every leg uses the unchanged canonical Decimal receipt at full native input,
with existing product constraints, 0.9% default estimated fee and fixed 15bps
modeled slippage. No fit search is added. No extra profit floor is applied. The
legacy receipt's cap/rate parameters use a documented unit-budget adapter:
cap=input quantity, rate=1. This cancels algebraically to the full native budget;
it is not a USD exchange rate or assumed peg. The approximate USD-notional field
is removed from these receipts to prevent that misinterpretation. BUY and SELL
native amounts and fees still come exclusively from canonical receipt math.

Only cycle quote dependencies must fit the existing 30s freshness, 0.25% spread
and 12s synchronization limits. Balances must be no older than 120s. No ETH-USD
or account-wide valuation is required. A Coinbase-reported USD portfolio figure
can remain a separate display but is not cycle profit or earned ETH. The existing
USD scanner and dollar-based reserve reference retain their existing semantics.

Full-size constraint failures are BLOCKED. Missing/unusable dependencies or
unconverted non-ETH residue remain UNKNOWN; they never receive profit ranks.
Initial ETH rounding residue remains ETH and is included in final ETH. Complete
estimates compare final ETH against HOLD of the same starting ETH. Unrelated
holdings cancel from this isolated comparison and are not liquidated or revalued.
Both positive and nonpositive complete estimates are ranked. Finding no positive
cycle is a valid research result. Depth, actual fee currency, sequential-leg risk
and settlement remain unverified; every result remains execution-ineligible.

Private caller results contain native quantities; only `public_cycle_report`
should be used for public exports. It exports routes, controlled blocker codes,
evidence limits and aggregate counts, omitting native amounts and receipts.
The existing eight-section GUI export is unchanged and does not yet include it.

Validation: Python 3.11.17, hash-locked dependencies; 30 tests passed with HTTP
forbidden (11 new evaluator cases, five existing topology cases and fourteen
existing full-balance cases). No GUI/full-suite/native-Windows release validation
is claimed for this increment. The previous focused GUI run had nine setup errors
because no display is available. The existing v91 manifest remains unchanged;
these new development files are not a packaged/verified v92 release archive.

Next: add immutable snapshot integration within the existing quote budget and
GUI/diagnostic presentation; test STOP and queued-result handling; then full
regression and native Windows verification. Phases 2–4 remain reconciliation,
reserve/cashflow design and prolonged read-only observation. No actual asset
allocation, harvesting, transfer or live-order permission follows from this model.
