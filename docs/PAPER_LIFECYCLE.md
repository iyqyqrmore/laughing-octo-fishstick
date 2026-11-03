# CoinCat v1.01 paper lifecycle

Current integration is documented in AUTO_PAPER_V1_01.md. The normal scanner
advances this engine only through a bounded opted-in shared paper session. Its
fourteen-view controller and explicit seeded stress provider are separate from
the declared replay and independent journal comparisons. Current base is v100
ebe4fd7; the owner authorized source push as v1.01 after verification. The
original deterministic replay expectations below remain unchanged.

The owner selected implementation using explicit simulation/replay events on
November 3, 2026. This source candidate builds on published journal commit
5e951db52c31f07f4b66c1f31b81829caed64300. It adds a durable offline execution
state machine and a scripted driver. It does not install on the running PC.

## Windows acceptance

1. Extract the candidate source ZIP into a separate folder. Preserve the working
   installation, private records and backups. No account or private dataset is
   needed for the replay.
2. Run `02_SETUP_COINCAT.bat`, then `03_VERIFY_COINCAT.bat`. Require passing source
   hashes and all isolated tests; inspect any skip and its host-specific reason.
3. Run `tools\RUN_PAPER_REPLAY.bat`. Alternatively:

   ```text
   .venv\Scripts\python.exe -B tools\PAPER_LIFECYCLE_REPLAY.py --synthetic
   ```

   The trace must show ETH→BTC partial filling, cancellation pending, a final fill
   winning that race, then an automatically requested BTC→SOL order. SOL also
   fills in two explicitly supplied partials. One redelivered fill is ignored.
   Expected fictitious wallet: 0 ETH, 0 BTC, 2 SOL after the declared 1% toy fees.
   Expected counts: 2 terminal paper orders, 4 simulated fills, 0 real orders,
   0 verified exchange fills. These sizes, rates and prices are fixture inputs,
   never recommended account defaults or evidence of market performance.
4. The replay leaves SOL held at session expiry. Restart must display
   RECONCILIATION_REQUIRED and zero pending dispatches, then PAUSED after an exact
   explicit replay snapshot. It must not resume automatically. The temporary
   paper database is deleted when this demonstration exits.
5. To check the journal-display repair with an existing test dataset, use a
   complete independent verified copy following START_HERE, with other versions
   stopped. Reopen the app before starting research. A saved case must appear in
   both the main count and the local viewer. Diagnostics and monitor v3 must show
   the same aggregate count, without signals or native quantities. A read failure
   says UNAVAILABLE, never an empty-journal verdict. Do not share a running data
   folder or create a fresh financial dataset over existing records.

The replay is fully offline and uses a disposable database outside the account
dataset. Run the existing read-only supervised Windows checks separately for
DPAPI, single instance, DPI, STOP, connected observations and clean shutdown.
Linux/Xvfb evidence does not establish those native Windows results.

## Engine contract

`app/coincat_paper_engine.py` accepts only an explicit SIMULATION_ONLY setup and
EXPLICIT_SIMULATION or SIMULATED_REPLAY events. The recorded classification is
SIMULATED_ASSUMPTION. There is no live mode, Coinbase client, credential access,
network loop, production ledger or authenticated order/preview adapter.

`PaperLimits` requires explicit products, native per-order source caps, maximum
open and session order counts, original session expiry and a maximum fee fraction.
Only the existing seven products and five assets are eligible. Initial funding
is ETH only. `from_proposal` uses the existing working/manual/protected/excluded
funding contract; existing BTC/SOL balances cannot become initial funding. These
are simulation bounds, not new real allocation or risk settings.

Admission uses the existing frozen `Frame`, catalog permissions, actual native
rules, 30-second age, 0.25% spread, fresh fee tier and post-only tick/cross checks.
It calls the canonical `research_order` with exact Decimal native budgeting.
No second sizing/receipt implementation or USD bridge is introduced. Explicit
execution units use the existing `normalize_fill`; settlement applies those
supplied native debits/credits with the supplied fee exactly once.

Orders move through PENDING_NEW, OPEN, PARTIAL, PENDING_CANCEL and FILLED,
CANCELED or REJECTED. Unknown placement, cancellation, fee or contradictory
execution evidence puts the session in RECONCILIATION_REQUIRED. Reservations
precede outbound paper commands. Both the remaining source and known proceeds
of a nonterminal partial order stay locked; one wallet cannot fund competing
orders. Partial executions may be smaller than a full order's admission minimum,
but must respect the base increment and never exceed the planned total.

An explicit full fill can win a cancel race. A cancel acknowledgement releases
remaining reservations only when its cumulative quantity equals complete known
fill history and fees are settled. An unseen fill contradicting terminal totals
halts new intents and requires investigation; it cannot silently credit funds.
Unknown fee amount/currency credits no proceeds. Only explicit quote-currency
fee evidence is supported; rebates and other fee assets remain unresolved.

Price touches, elapsed time, OHLC, a planned receipt and a favorable later price
never create executions. All fills in the supplied replay are declared in its
input event sequence. This tests execution handling; it is not an exchange
matching model, historical queue replay or calibrated fill-probability model.

## Durable API and replay integration

Create an empty dedicated paper database with `PaperEngine.create`, then call
`start` once. An offline caller can `place` a qualifying paper intent or use
`ReplayDriver.advance(frame)` to run the expressly chosen scripted sequence.
The driver waits for each predecessor to fill completely; a rejected/canceled
step returns HOLD and requires a changed explicit script to pursue another path.
Ordinary steps inside that paper session need no repeated user confirmation.
The supplied script ends in HOLD; it is not a validated predictive selector.

The simulated venue consumes `pending_commands()`. Immediately before delivering
a command, call `mark_dispatched(..., at=...)` and deliver only when its result
contains `dispatch_permitted=True`. That grant is persisted before delivery.
Repeating the event or using a new event ID cannot grant another send. A crash
between that write and delivery has an unknown outcome, not permission to retry.
Expiry blocks new placements; pending paper cancels may dispatch while PAUSED.
STOP retains reservations and inventory; it is not a sale or confirmation of
exchange cancellation.

Feed explicit events through `ingest`. The exact event envelope is:

```python
{
    'event_id': 'delivery_1', 'source': 'SIMULATED_REPLAY',
    'kind': 'FILL', 'reference': 'seed', 'at': 1800000002,
    'data': {
        'venue_order_id': 'toy_seed', 'fill_id': 'toy_fill_1',
        'price': '1.01', 'size': '.4', 'size_in_quote': False,
        'commission': '.00404', 'fee_currency': 'BTC', 'liquidity': 'MAKER'
    }
}
```

Financial inputs must be Decimal, exact strings or integers, never binary floats.
ACK needs `venue_order_id`. CANCEL_ACK and REJECT need that identity and
`cumulative_base`; a never-accepted REJECT may have a null venue ID.
FEE_RESOLVED needs `fill_id`, `commission` and `fee_currency` for a previously
quarantined event. OUTCOME_UNKNOWN accepts only SUBMISSION_UNKNOWN,
CANCEL_UNKNOWN or TRANSPORT_GAP. Extra fields and unsupported provenance fail.
Delivery IDs and fill IDs are independently idempotent. Conflicting duplicates
halt the session. Events may arrive out of execution order, but new intents
cannot use a clock earlier than already processed evidence.

`tick` handles original order/session expiry without manufacturing fills or
liquidating inventory. `restore` keeps balances, partials, reservations and
deadlines, marks reconciliation required and offers no automatic resend.
`reconcile` requires an exact five-asset balance snapshot, all nonterminal orders,
matching identities, complete cumulative fill history and known fees. Unexplained
deposits, missing fills or unknown commissions cannot become profit or spendable
funds. Success leaves PAUSED; a separate session `start` is required. Expired
limits never renew through restart/reconciliation. Concurrent stale instances
must reload before any write or further spending.

The dedicated SQLite application ID refuses unrelated financial or research
files. Atomic state/event transactions use bounded JSON, exact Decimal encoding
and SHA256 corruption checks, never persisted code/pickle. Bounds: 64 session
orders, 16 open orders, 512 retained fill records, 4096 events, 512 KiB per encoded
payload and 32 MiB storage guard. Reaching a bound stops further writes and
requires review; it does not erase history. These bounds do not guarantee a
corrupt disk or untrusted caller can be automatically repaired.

## Current limits and discussion handoff

With Auto Paper off the GUI scanner makes read-only observations and observes
manually registered comparisons. Explicit Auto Paper opt-in enables a separate
shared controller; relaunch never resumes it. The local helper stays quantity-free monitor v3 and
cannot control the engine. Replay counters are separate from GUI/actual fills;
no simulated gain is exported as account profit. The startup repair restores
cached journal counts before scans and refreshes them on manual view/registration
or accepted scan, without database polling in heartbeats/exports.

The shared controller, fourteen views and labeled BBO stress provider are
implemented. Remaining work is calibrated observed queue/liquidity/fee evidence
and held-out market strategy validation. BBO alone cannot supply credible maker fills.
After-cost ETH stays UNKNOWN when sized exits, fee units or residual valuation
are missing. Unresolved events deliberately pause unattended progress. Patient
HOLD has no forced losing sale, recovery guarantee or demonstrated advantage.

For a ChatGPT discussion: CoinCat now has a tested offline execution lifecycle
using explicitly declared synthetic fills, including partial/cancel/restart
handling. It has a scanner-connected paper controller but no calibrated venue or demonstrated
predictor. The goal remains autonomous ETH growth within owner-approved limits,
with a single future live authorization rather than approval of each routine
trade. Execution correctness and strategy profitability need separate evidence.
LiveBroker.submit still raises LiveBlocked immediately. No live authorization,
account change, real allocation, PC installation or deployment accompanies this
candidate. The owner subsequently explicitly authorized this follow-up's source
commit/push; that instruction does not authorize connected execution or deployment.
