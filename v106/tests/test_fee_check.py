"""M0 tests only. Synthetic GET responses; no account or network access."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import io
import json
import unittest

from v106 import fee_check as m

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
EMPTY_ENV = {"COINBASE_API_KEY": "", "COINBASE_API_SECRET": ""}
KEY = dict(name="organizations/synthetic/apiKeys/synthetic", privateKey="TEST_ONLY_PRIVATE_KEY_" * 3)


class Client:
    def __init__(self):
        self.session = Mock()
        self.calls = []
        self.fee = dict(fee_tier=dict(maker_fee_rate="0.005", taker_fee_rate="0.009"))
        self.product = dict(product_id="ETH-BTC", product_type="SPOT", base_currency_id="ETH", quote_currency_id="BTC",
            base_increment="0.00000001", quote_increment="0.00000001", price_increment="0.000001",
            base_min_size="0.00000001", quote_min_size="0.00001", base_max_size="100", quote_max_size="10",
            status="online", view_only=False, trading_disabled=False, cancel_only=False, private_field="MUST_NOT_EXPORT")
        self.book = dict(pricebook=dict(product_id="ETH-BTC", time=NOW.isoformat(),
            bids=[dict(price="0.028457", size="1")], asks=[dict(price="0.028459", size="1")]))

    def get_transaction_summary(self, **kwargs):
        self.calls.append(("get_transaction_summary", kwargs))
        if isinstance(self.fee, Exception):
            raise self.fee
        return deepcopy(self.fee)

    def get_product(self, **kwargs):
        self.calls.append(("get_product", kwargs))
        return deepcopy(self.product)

    def get_product_book(self, **kwargs):
        self.calls.append(("get_product_book", kwargs))
        return deepcopy(self.book)


class M0(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def collect(self):
        return m.collect(self.client, clock=lambda: NOW)

    def test_current_authenticated_rates_and_sums_use_only_three_gets(self):
        report = self.collect()
        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(D(report["fees"]["maker_rate"]), D(".005"))
        self.assertEqual(D(report["fees"]["taker_percent"]), D(".9"))
        self.assertEqual(D(report["fees"]["round_trip_percent_sums"]["maker_maker"]), D(1))
        self.assertEqual(D(report["fees"]["round_trip_percent_sums"]["taker_taker"]), D("1.8"))
        self.assertEqual([n for n, _ in self.client.calls], ["get_transaction_summary", "get_product", "get_product_book"])
        self.assertEqual(self.client.calls[0][1], dict(product_type="SPOT"))
        self.assertEqual(self.client.calls[1][1]["product_id"], "ETH-BTC")
        self.assertEqual(self.client.calls[2][1], dict(product_id="ETH-BTC", limit=1))
        self.assertNotIn("MUST_NOT_EXPORT", json.dumps(report))

    def test_zero_fee_is_reported_only_when_api_supplies_it(self):
        self.client.fee["fee_tier"].update(maker_fee_rate="0", taker_fee_rate="0.001")
        result = self.collect()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(D(result["fees"]["round_trip_percent_sums"]["maker_maker"]), 0)

    def test_both_native_minimums_and_precision_apply_at_bid_and_ask(self):
        result = self.collect()
        for side in ("BUY", "SELL"):
            order = result["minimum_orders"][side]
            q, p, gross = (D(order[k]) for k in ("quantity_eth", "price_btc_per_eth", "notional_btc"))
            self.assertGreater(q, D(self.client.product["base_increment"]))
            self.assertGreaterEqual(q, D(self.client.product["base_min_size"]))
            self.assertGreaterEqual(gross, D(self.client.product["quote_min_size"]))
            self.assertEqual(q * p, gross)
            self.assertEqual(q % D(self.client.product["base_increment"]), 0)
            self.assertEqual(p % D(self.client.product["price_increment"]), 0)
            if side == "BUY":
                self.assertLess(p, D(".028459"))
            else:
                self.assertGreater(p, D(".028457"))

    def test_native_base_minimum_can_dominate_quote_minimum_and_maxima_are_retained(self):
        self.client.product.update(base_increment=".001", base_min_size=".005", quote_min_size=".0001")
        self.client.book["pricebook"].update(bids=[dict(price=".02", size="1")], asks=[dict(price=".021", size="1")])
        result = self.collect()
        self.assertEqual(D(result["minimum_orders"]["BUY"]["quantity_eth"]), D(".005"))
        self.assertEqual(D(result["minimum_orders"]["SELL"]["notional_btc"]), D(".000105"))
        self.assertEqual(result["product"]["base_max_size"], "100")

    def test_minimum_exceeding_exchange_maximum_does_not_create_an_invalid_ticket(self):
        self.client.product["base_max_size"] = ".00001"
        result = self.collect()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["minimum_orders"])
        self.assertIsNotNone(result["fees"])

    def test_missing_nonfinite_float_and_invalid_rates_never_use_a_default(self):
        for value in (None, "NaN", "Infinity", "-0.005", "1", 0.005, True):
            with self.subTest(rate=value):
                self.client.fee["fee_tier"]["maker_fee_rate"] = value
                result = self.collect()
                self.assertEqual(result["status"], "PARTIAL")
                self.assertIsNone(result["fees"])
                self.assertIsNotNone(result["minimum_orders"])

    def test_missing_rules_or_wrong_product_leaves_rules_unknown_without_hiding_fee_truth(self):
        for update in (dict(product_id="BTC-ETH"), dict(base_increment=None), dict(quote_min_size="0")):
            with self.subTest(update=update):
                self.client.product = dict(Client().product, **update)
                result = self.collect()
                self.assertIsNotNone(result["fees"])
                self.assertIsNone(result["product"])
                self.assertIsNone(result["minimum_orders"])

    def test_private_sdk_error_is_not_printed_or_saved(self):
        self.client.fee = RuntimeError(KEY["privateKey"])
        result = self.collect()
        self.assertEqual(result["errors"], ["AUTHENTICATED_SPOT_FEES_UNAVAILABLE"])
        self.assertNotIn(KEY["privateKey"], json.dumps(result))

    def test_missing_credentials_saves_nulls_utc_and_never_creates_a_private_vault(self):
        with TemporaryDirectory() as folder, patch.dict(m.os.environ, EMPTY_ENV), patch.object(m, "data_root", return_value=Path(folder) / "absent"):
            path = Path(folder) / "out" / "fees.json"
            with patch.object(m, "client_from_credentials") as factory, redirect_stdout(io.StringIO()) as console:
                self.assertEqual(m.main(["--output", str(path)]), 1)
            factory.assert_not_called()
            result = json.loads(path.read_text())
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertIsNone(result["fees"])
            self.assertTrue(result["checked_at_utc"].endswith("Z"))
            self.assertFalse((Path(folder) / "absent").exists())
            self.assertIn("UNKNOWN", console.getvalue())
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_saved_key_is_reused_and_session_closes_on_success_and_fee_permission_failure(self):
        with TemporaryDirectory() as folder, patch.dict(m.os.environ, EMPTY_ENV), patch.object(m, "data_root", return_value=Path(folder)):
            (Path(folder) / "coinbase_key.dpapi").write_bytes(b"SYNTHETIC_VAULT")
            for allowed in (True, False):
                self.client.fee = Client().fee if allowed else PermissionError("PRIVATE_FEE_PERMISSION_ERROR")
                with patch.object(m, "load_encrypted", return_value=KEY) as vault, patch.object(m, "client_from_credentials", return_value=self.client) as factory:
                    result = m.run(clock=lambda: NOW)
                vault.assert_called_once_with()
                factory.assert_called_once_with(KEY)
                self.assertEqual(result["status"], "VERIFIED" if allowed else "PARTIAL")
            self.assertEqual(self.client.session.close.call_count, 2)

    def test_incomplete_environment_key_does_not_fall_back_to_another_saved_identity(self):
        with patch.dict(m.os.environ, dict(COINBASE_API_KEY=KEY["name"], COINBASE_API_SECRET="")), patch.object(m, "load_encrypted") as vault:
            result = m.run()
        self.assertEqual(result["errors"], ["BOTH_COINBASE_ENVIRONMENT_VALUES_REQUIRED"])
        vault.assert_not_called()

    def test_complete_environment_credentials_reuse_the_existing_key_parser(self):
        with patch.dict(m.os.environ, dict(COINBASE_API_KEY=KEY["name"], COINBASE_API_SECRET=KEY["privateKey"])), patch.object(m, "load_encrypted") as vault:
            self.assertEqual(m.credentials_from_local(), KEY)
        vault.assert_not_called()

    def test_session_close_failure_cannot_leak_an_sdk_error(self):
        self.client.session.close.side_effect = RuntimeError(KEY["privateKey"])
        with patch.object(m, "credentials_from_local", return_value=KEY), patch.object(m, "client_from_credentials", return_value=self.client):
            result = m.run(clock=lambda: NOW)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn(KEY["privateKey"], json.dumps(result))


if __name__ == "__main__":
    unittest.main()
