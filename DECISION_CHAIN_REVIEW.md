# v70.3 decision-chain review

All replay prices, quantities, funding and fees in automated tests and benchmarks
are synthetic. No account keys, Coinbase calls or production ledger writes occur.

| Stage | Contract | Verification |
| --- | --- | --- |
| Portfolio / fuel | Sources use the smaller of enrolled and available native quantities. Exclusions remain binding. Evolved SHADOW inventory funds its own follow-on decisions. | Independent receipts; queued-wallet and late-exclusion regressions. |
| AI Lab / decision | Eligible, listed, fundable one-order products; fresh books, authenticated fee evidence and numeric rules. Rank all costed sizes before clipping. | Restricted/offline/missing-rule cases; later funding asset wins; cache parity and expiry. |
| Auto Trader / movement | Explicitly armed RAM SHADOW. Recheck approvals, source FX units, inventory, per-order/exposure/turnover/attempt caps and idempotency. | Actual urgent producer-to-consumer replay; stale/excluded/exhausted decisions blocked; no-op not counted. |
| P&L / diagnostics | Same-time whole-wallet value minus frozen-quantity HOLD. Fees embedded once. Missing FX never becomes zero. | Independent quantities/deltas, complete 18-section export, hourly counts and mark age. |

## Receipt and P&L math

Let f be the authenticated taker fee estimate, s = 0.0015 the slippage stress,
i the base increment, and r[A] the conservative USD mark per unit of asset A.
These estimates do not establish executable depth, exact fee rounding, maker
fills, actual fee currency or actual slippage. Amount math uses Decimal.

For a listed BASE-QUOTE BUY, the source is QUOTE:

```text
quote_budget = min(available_quote, order_USD_cap / r[QUOTE])
base_received = floor_to_increment(quote_budget / (ask * (1+s) * (1+f)), i)
quote_spent = base_received * ask * (1+s) * (1+f)
source_residual = available_quote - quote_spent
turnover_USD = quote_spent * r[QUOTE]
```

For a SELL, the source is BASE:

```text
base_spent = floor_to_increment(min(available_base, order_USD_cap / r[BASE]), i)
quote_received = base_spent * bid * (1-s) * (1-f)
source_residual = available_base - base_spent
turnover_USD = base_spent * r[BASE]
```

Check exchange minima/maxima on the resulting native quantities. One conversion
has one fee in its receipts. A SELL must not treat base quantity as quote units.
USDC uses observed USD books, never an assumed peg. Canonical receipts are applied
through the production settlement arithmetic inside a separate :memory: FIFO DB.

```text
HOLD_USD(t) = sum(starting_quantity[A] * mark[A,t])
MODEL_USD(t) = sum(current_model_quantity[A] * mark[A,t])
model_vs_HOLD(t) = MODEL_USD(t) - HOLD_USD(t)
```

Residuals remain in MODEL; original quantities remain frozen in HOLD. Both use
the same current marks and timing policy. Fees and slippage already change the
modeled quantities; subtracting estimated fees again would double-count them.
The provisional experimental score applies repeated observed momentum to actual
net destination receipts, then adds the immediate marked change. This is a
ranking assumption, not a learned return distribution or prediction.

Snowball separately compares hypothetical liquidation proceeds of the changed
slice, applying comparable exit friction to each USD mark path. Those valuation
exits are not additional orders in the conversion. Its estimate can differ from
gross wallet mark-to-market P&L. Neither is confirmed realized Coinbase P&L,
verified tax basis or an executable profit guarantee.

## Speed and frequency evidence

The profiled comparison uses 804 listed products, 23 funding assets, three
synthetic destinations and the same 207 exploratory size attempts. Both runs
include the background SELL advisory; urgent mode defers that advisory.

| Measurement | v70.2 | v70.3 |
| --- | ---: | ---: |
| Profiled planner wall time on this cloud host | 7.710s | 0.263s |
| USD-conversion helper invocations | 1,466 | 51 |
| Returned shortlist | First 6 | Best 12 after ranking all costed proposals |

Run `python -B tools/benchmark_decision_chain.py --profile` to repeat the current
synthetic workload. Timing varies with host load and profiling overhead. This
excludes HTTP, authentication, GUI scheduling and fills. It does not imply the
same speedup on Windows or a live exchange.

The actual urgent producer-to-consumer test advances an artificial clock through
12 opportunities, five minutes apart. All 12 qualified one-leg model receipts
reach the wallet and P&L within that simulated hour. At constant prices, the
result is negative after costs, correctly. A separate 150-conversion replay
proves that retained outcomes no longer stop the session after 144 lifetime
records. These are capacity/accounting checks, not measured real-time fills.

The existing urgent loop targets five-second checks, with at most 16 REST books,
rate budgeting and a six-second collector deadline. Required portfolio refresh
and reconciliation come first. Slow/retried requests and Windows load can still
increase latency. Diagnostics report completed-event latency percentiles,
request/planner time, approved scope and separate urgent/broad ages. Background
candles and GPU training are not prerequisites for experimental decisions.
Validated SHADOW retains its independent chronological held-out requirements.

Saved attempts and daily conversion turnover remain independent of wallet size.
Per-order/exposure limits still cannot exceed verified fuel. Ten conversions/hour
throughout a day needs an attempt cap of at least 240/24h and enough turnover for
the total input USD mark. Defaults of 12 attempts/day and $30/day turnover were
not raised automatically. No frequency target overrides current eligibility,
costs, budgets or required fresh information.

## Local verification still needed

The cloud cannot establish current Coinbase opportunities or this PC's execution
latency. Run 03_VERIFY_COINCAT.bat in the clean new folder, import the verified
private dataset using the existing local workflow, connect read-only, and review
new diagnostics while SHADOW runs. Keep modeled and actual results separate.
Real submission remains blocked pending existing execution, recovery, loss-floor,
fee/depth and independently observed-edge requirements. No private financial
schemas, tax lots or user state were rewritten by this patch.
