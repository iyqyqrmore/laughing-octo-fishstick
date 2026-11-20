# CoinCat v1.07

CoinCat compares a modeled ETH/BTC portfolio with holding the same opening
quantities. It proposes independent ETH-BTC maker orders and simulates eligible
fills when sufficient public trade evidence is present. **Live trading is disabled.**

## Start on Windows

1. Install 64-bit CPython 3.11 with Tcl/Tk and the Python launcher.
2. Extract the GitHub source ZIP to a fresh folder. Retain your older folders
   and any private data or backups separately.
3. Run `02_SETUP_COINCAT.bat` to install the hash-locked optional authentication
   dependency and verify the source. `03_VERIFY_COINCAT.bat` verifies the source
   offline using only Python's standard library.
4. Open `01_START_COINCAT.bat`. Copy the actual starting ETH and BTC quantities
   from your portfolio, confirm **Freeze opening HOLD**, then **Start shadow**.
   Closing the window exits. Restart opens paused and preserves the ledger.

The fresh SQLite database is `private_data/v107/one_leg.sqlite3` relative to the
extracted folder. CoinCat reads no database, settings or credential files from
other builds. Keep that folder private. The opening quantities are permanent
for that database. A separate installation starts a separate benchmark.

## Read-only Coinbase configuration

For proposals, make available a Coinbase Advanced Trade view-only API key in
the environment that starts CoinCat. The variables are `COINBASE_API_KEY` and
`COINBASE_API_SECRET`. Use the Coinbase key format accepted by the SDK (verify
the key type with Coinbase for Advanced Trade). The app never saves the key.
Without an authenticated maker rate, the dashboard can mark the portfolio and
will HOLD. It takes no account fee rate from Coinbase One membership.

From the installation folder in Windows Command Prompt with those variables set:

```bat
.venv\Scripts\python.exe -m coincat.fees --rules > private_data\v107\fees.json
.venv\Scripts\python.exe -m coincat.history --output private_data\v107\market --days 120
.venv\Scripts\python.exe -m research.backtest --data private_data\v107\market --fees private_data\v107\fees.json --output private_data\v107\comparison
```

First launch creates `private_data/v107`. The export can take several minutes;
use a fixed `--end YYYY-MM-DD` to resume the same range. The optional
`--interval 60` or `--interval 3600` exports one-minute or hourly candles. The
v1.07 forecast and matched comparison use the five-minute stream. Recent closed
bars are fetched during connected shadow operation. History gates each forecast
independently. The immediate path works with synchronized books and a verified
fee while historical evidence is still accumulating.

To reconcile actual fills independently, run
`.venv\Scripts\python.exe -m coincat.receipts`. To reconcile a specific historical
ETH-BTC order including order status and recorded filled size, append
`--order <Coinbase UUID>`. Aggregate output omits Coinbase IDs and amounts.
Actual receipt records stay in the local database.

## Verify on native Windows

1. Run the offline verification from an extracted source package and launch it.
   Check the window icon, tabs, Windows minimize behavior, close, and restart.
2. With a view-only key, check that ETH-BTC, ETH-USD and BTC-USD are fresh and
   the fee verification reports the current spot rates. Disconnect and confirm
   that further proposals stop. Reconnect and explicitly resume as needed.
3. Observe HOLD and, if an opportunity appears, check LIMIT GTC Post Only
   proposal amounts, source reservations and native increments. A simulated
   fill should follow eligible evidence only. Compare a partial fill commission
   to its filled quantity. The actual Coinbase account should receive no order.
4. Pause or restart and verify the same opening portfolio, filled amounts and
   fees. Review any unresolved shadow remainder before resuming. Acknowledgment
   releases its shadow reservation without recording a fill.
5. Check that the 1h, 6h and 24h changes populate only after the corresponding
   observations exist. Compare net modeled value against the frozen HOLD using
   synchronized marks on both holdings.

See [strategy](STRATEGY.md), [fees](FEE_ACCOUNTING.md), [research](RESEARCH_REPORT.md),
[release notes](RELEASE_NOTES.md), and [verification](VERIFICATION.md).
