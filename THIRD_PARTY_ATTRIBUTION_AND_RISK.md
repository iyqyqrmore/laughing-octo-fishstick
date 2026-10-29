# Dependencies and evidence limits

CoinCat uses the official coinbase-advanced-py 1.8.4 SDK and requests, with exact
transitive versions and artifact hashes in app_requirements.lock. The SDK's own
cryptographic and websockets dependencies remain. Retired plotting/GPU libraries
and external trading-bot frameworks are not installed by this build.

No external bot strategy code was copied. Historical engineering references in
docs/ENGINEERING_REFERENCES.md discuss timestamp/fee/simulation pitfalls; they
do not establish live profitability or authorize exchange calls.

Local request time is not verified exchange-event time. Account-tier fees are
not actual fill-fee currency evidence. The 0.15% slippage reserve is an assumption.
Positive modeled USD advantage is not an executable guarantee, fill or profit.
The preserved broker blocks orders. Linux offline tests do not certify native
Windows key storage, real account behavior, production settlement or recovery.
