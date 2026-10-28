"""Compatibility import alias; active startup uses coincat_launcher."""
from coincat_launcher import main, ensure_private_data
if __name__=='__main__':raise SystemExit(main())
