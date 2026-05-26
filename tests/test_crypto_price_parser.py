import unittest
import sys
import types

crypto_price_service = types.ModuleType("app.services.crypto_price_service")
crypto_price_service.ASSET_ALIASES = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "эфир": "ETHUSDT",
}
sys.modules.setdefault("app.services.crypto_price_service", crypto_price_service)

from app.services.crypto_price_parser import (
    looks_like_crypto_price_query,
    try_parse_crypto_price,
)


class CryptoPriceParserTest(unittest.TestCase):
    def test_bare_ticker_is_price_query(self) -> None:
        parsed = try_parse_crypto_price("btc")

        self.assertTrue(looks_like_crypto_price_query("btc"))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.asset, "btc")
        self.assertEqual(parsed.vs_currency, "usdt")

    def test_russian_price_query_finds_asset_alias(self) -> None:
        parsed = try_parse_crypto_price("сколько сейчас стоит эфир")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.asset, "эфир")

    def test_non_price_text_is_ignored(self) -> None:
        self.assertFalse(looks_like_crypto_price_query("объясни что такое asyncio"))
        self.assertIsNone(try_parse_crypto_price("объясни что такое asyncio"))


if __name__ == "__main__":
    unittest.main()
