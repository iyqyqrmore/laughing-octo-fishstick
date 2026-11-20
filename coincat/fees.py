"""Authenticate the current spot fee schedule and report separate fee comparisons."""

import argparse
import json

from .market import Coinbase, MarketUnavailable
from .money import native_math


@native_math
def comparison(schedule):
    maker, taker = schedule.maker * 100, schedule.taker * 100
    return {
        "one_leg_maker_percent": str(maker),
        "one_leg_taker_percent": str(taker),
        "two_separate_maker_transactions_rate_sum_percent": str(2 * maker),
        "two_separate_taker_transactions_rate_sum_percent": str(2 * taker),
        "mixed_maker_taker_rate_sum_percent": str(maker + taker),
        "two_leg_basis": "Hypothetical research comparison only. Rate sums exclude price changes and spread.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules", action="store_true", help="Include public native ETH-BTC rules for research"
    )
    args = parser.parse_args()
    client = Coinbase()
    try:
        schedule = client.fees()
    except (MarketUnavailable, KeyError, TypeError, ValueError, ImportError):
        print(json.dumps({"status": "UNVERIFIED", "fees": None}, indent=2))
        return 1
    report = {"status": "VERIFIED", "product_type": "SPOT", "fees": comparison(schedule)}
    if args.rules:
        try:
            report["public_eth_btc_rules"] = {
                key: str(value) if value is not None else None for key, value in vars(client.rules()).items()
            }
        except (MarketUnavailable, KeyError, TypeError, ValueError):
            report["public_eth_btc_rules"] = None
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
