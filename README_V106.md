# CoinCat v1.06 — M0 fee check only

ETH-BTC is the only order market in this patch. M1–M5 are not implemented.
The existing v1.05 app, AGENTS.md and protected modules are unchanged.

From your existing CoinCat Windows folder, using its installed dependencies:

```bat
.\.venv\Scripts\python.exe -m v106.fee_check
```

The checker reads the saved key under your current Windows user, or the standard
`COINBASE_API_KEY` and `COINBASE_API_SECRET` environment variables if both are set.
An existing `COINCAT_DATA_DIR` is respected. Never paste keys into chat.
Uses the pinned 1.8.4 SDK and GETs only: SPOT transaction summary, ETH-BTC product
rules and its current pricebook. It never reads balances or fills,
submits orders, cancels orders, starts a strategy or changes the live block.

Output: `v106_out/fees.json` (ignored by Git), UTC capture time, authenticated
maker/taker rates, two-leg rate sums, native increments/min/max and gross minimum
BUY at BID / SELL at ASK in ETH and BTC. The quote minimum can require more ETH
than the base increment alone suggests. Minimum notional excludes fees and is
not a funded/accepted exchange order. Rate sums exclude spread and price changes;
they are not an exact realized round-trip settlement. No future fee is debited.
Coinbase One is not used to infer discounts or commission currencies/precision.

`VERIFIED` / exit 0 means all M0 reads/calculations passed, not trading permission.
`PARTIAL` or `UNVERIFIED` / exit 1 leaves unavailable fields null with fixed errors;
no guessed fee is substituted. Exit 2 means the output could not be saved.
If the cloud has no saved key/network access, run locally and provide the fee
output or fees.json, never credentials. Native Windows/API truth is then checked.

New-code tests only (synthetic responses; no HTTP):

```bat
.\.venv\Scripts\python.exe -m unittest discover -s v106/tests -v
```

Stop after M0. Review the authenticated numbers before M1.
