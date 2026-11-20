# Dependencies and evidence limits

CoinCat uses the Python standard library and Tcl/Tk. The Coinbase SDK
(`coinbase-advanced-py` 1.8.4) is used only to build JWTs for fixed-origin
GET requests. Its versions and artifact hashes, including its unused transport
dependencies, are pinned in requirements.lock. Authenticated reads use the
Windows trust store or the host's standard HTTPS trust store.

CoinCat branding and the dark Tk palette are taken from the project's v1.06
source. The archived comparison policies originate in the same branch. Public
trade evidence, estimated commissions, native receipts and mark-to-market
results have different evidence scopes. See the strategy and research reports
for the shadow assumptions and connected acceptance still required.
