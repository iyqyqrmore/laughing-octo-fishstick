"""Read-only Coinbase Advanced Trade data and native product rules."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .money import FeeSchedule, decimal

PRODUCT = "ETH-BTC"
BASE, QUOTE = PRODUCT.split("-")
PRODUCTS = (PRODUCT, "ETH-USD", "BTC-USD")
API = "/api/v3/brokerage"
HOST = "https://api.coinbase.com"


class MarketUnavailable(ValueError):
    pass


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("Exchange timestamp lacks timezone")
    return stamp.timestamp()


@dataclass(frozen=True)
class Rules:
    base_step: Decimal
    price_step: Decimal
    quote_step: Decimal
    base_min: Decimal
    quote_min: Decimal
    base_max: Decimal | None
    quote_max: Decimal | None

    def __post_init__(self):
        if any(amount is not None and amount <= 0 for amount in vars(self).values()):
            raise MarketUnavailable("Invalid native product limits")
        if (self.base_max is not None and self.base_max < self.base_min) or (
            self.quote_max is not None and self.quote_max < self.quote_min
        ):
            raise MarketUnavailable("Conflicting native product limits")

    @classmethod
    def from_product(cls, data):
        if data.get("product_id") != PRODUCT or data.get("product_type") != "SPOT":
            raise MarketUnavailable("ETH-BTC native spot product unavailable")
        if (data.get("base_currency_id", BASE), data.get("quote_currency_id", QUOTE)) != (BASE, QUOTE):
            raise MarketUnavailable("Native currency mismatch")
        flags = ("trading_disabled", "cancel_only", "view_only", "is_disabled", "auction_mode")
        if any(data.get(key) not in (False, None) for key in flags):
            raise MarketUnavailable("Native maker trading restricted")
        if str(data.get("status", "")).lower() not in ("online", "active", "trading"):
            raise MarketUnavailable("Native product is not reported online")
        keys = (
            "base_increment",
            "price_increment",
            "quote_increment",
            "base_min_size",
            "quote_min_size",
            "base_max_size",
            "quote_max_size",
        )
        values = [decimal(data[key]) for key in keys[:5]]
        values.extend(decimal(data[key]) if data.get(key) not in ("", None) else None for key in keys[5:])
        return cls(*values)


@dataclass(frozen=True)
class Book:
    bid: Decimal
    ask: Decimal
    at: float

    @property
    def midpoint(self):
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class Frame:
    at: float
    native: Book
    eth: Book
    btc: Book
    rules: Rules

    @property
    def marks(self):
        return {BASE: self.eth.midpoint, QUOTE: self.btc.midpoint}

    def fresh(self, now):
        stamps = (self.native.at, self.eth.at, self.btc.at, self.at)
        return all(-2 <= now - stamp <= 15 for stamp in stamps) and max(stamps) - min(stamps) <= 12


@dataclass(frozen=True)
class Trade:
    trade_id: str
    at: float
    price: Decimal
    size: Decimal


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Coinbase:
    """Fixed-origin GETs only. The JWT helper has no exchange transport."""

    def __init__(self):
        self.opener = build_opener(NoRedirect())
        self.key = os.environ.get("COINBASE_API_KEY")
        self.secret = os.environ.get("COINBASE_API_SECRET")
        self.cached_rules = None

    @property
    def has_credentials(self):
        return bool(self.key and self.secret)

    def _get(self, path, query=None, *, authenticated=False):
        headers = {"Accept": "application/json", "Cache-Control": "no-cache"}
        if authenticated:
            if not self.has_credentials:
                raise MarketUnavailable("Read-only Coinbase credentials unavailable")
            from coinbase import jwt_generator

            try:
                uri = jwt_generator.format_jwt_uri("GET", path)
                token = jwt_generator.build_rest_jwt(uri, self.key, self.secret)
            except Exception:
                raise MarketUnavailable("Coinbase JWT signing failed") from None
            headers["Authorization"] = "Bearer " + token
        url = HOST + path + ("?" + urlencode(query) if query else "")
        try:
            with self.opener.open(Request(url, headers=headers, method="GET"), timeout=7) as response:
                data = response.read(4_000_001)
            if len(data) > 4_000_000:
                raise MarketUnavailable("Coinbase response exceeds size limit")
            return json.loads(data, parse_float=Decimal)
        except HTTPError as error:
            error.close()
            raise MarketUnavailable(f"Coinbase read returned HTTP {error.code}") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise MarketUnavailable("Coinbase read unavailable") from None

    def rules(self):
        now = time.time()
        if self.cached_rules and 0 <= now - self.cached_rules[0] < 300:
            return self.cached_rules[1]
        raw = self._get(f"{API}/market/products/{PRODUCT}", {"get_tradability_status": "true"})
        result = Rules.from_product(raw)
        self.cached_rules = (now, result)
        return result

    def book(self, product_id):
        raw = self._get(f"{API}/market/product_book", {"product_id": product_id, "limit": 1})["pricebook"]
        if raw["product_id"] != product_id:
            raise MarketUnavailable("Book product mismatch")
        book = Book(
            decimal(raw["bids"][0]["price"]), decimal(raw["asks"][0]["price"]), timestamp(raw["time"])
        )
        if not 0 < book.bid < book.ask:
            raise MarketUnavailable("Invalid bid or ask")
        return book

    def snapshot(self):
        rules = self.rules()
        native, eth, btc = (self.book(product) for product in PRODUCTS)
        now = time.time()
        frame = Frame(now, native, eth, btc, rules)
        if not frame.fresh(now):
            raise MarketUnavailable("Stale or unsynchronized market books")
        return frame

    def trades(self):
        raw = self._get(f"{API}/market/products/{PRODUCT}/ticker", {"limit": 100})["trades"]
        if not isinstance(raw, list) or len(raw) > 100:
            raise MarketUnavailable("Unexpected public trade page")
        result = {}
        for item in raw:
            if item.get("product_id") != PRODUCT:
                raise MarketUnavailable("Unexpected public trade product")
            trade = Trade(
                str(item["trade_id"]), timestamp(item["time"]), decimal(item["price"]), decimal(item["size"])
            )
            if not trade.trade_id or trade.trade_id == "None" or min(trade.price, trade.size) <= 0:
                raise MarketUnavailable("Invalid public trade")
            if trade.trade_id in result and result[trade.trade_id] != trade:
                raise MarketUnavailable("Conflicting public trade")
            result[trade.trade_id] = trade
        return sorted(result.values(), key=lambda trade: (trade.at, trade.trade_id))

    def fees(self):
        raw = self._get(f"{API}/transaction_summary", {"product_type": "SPOT"}, authenticated=True)
        tier = raw["fee_tier"]
        return FeeSchedule(decimal(tier["maker_fee_rate"]), decimal(tier["taker_fee_rate"]))

    def candle_page(self, product, start, end, granularity):
        if product not in PRODUCTS:
            raise ValueError("Unsupported candle product")
        return self._get(
            f"{API}/market/products/{product}/candles",
            {"start": start, "end": end, "granularity": granularity, "limit": 350},
        )["candles"]

    def receipt_page(self, cursor=None, order=None):
        query = {"product_ids": PRODUCT, "limit": 100}
        if order:
            query["order_ids"] = order
        if cursor:
            query["cursor"] = cursor
        return self._get(f"{API}/orders/historical/fills", query, authenticated=True)

    def order_receipt(self, order):
        return self._get(f"{API}/orders/historical/{order}", authenticated=True)["order"]
