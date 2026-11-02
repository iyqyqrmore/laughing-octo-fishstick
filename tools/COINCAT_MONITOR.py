"""Start CoinCat's local read-only monitor without loading the trading SDK."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from coincat_monitor_server import main

if __name__=='__main__':raise SystemExit(main())
