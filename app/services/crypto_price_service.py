"""Crypto spot prices via Binance public API (no API key)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from app.config import Settings
from app.services.crypto_assets import ASSET_ALIASES

logger = logging.getLogger(__name__)

_UNKNOWN_ASSET_MSG = "Не понял монету. Примеры: btc, eth, sol, ton, bnb"
_API_ERROR_MSG = (
    "Не смог получить цену через Binance. "
    "Возможно, такой пары нет или Binance временно недоступен."
)


class CryptoPriceError(Exception):
    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class CryptoPriceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve_binance_symbol(self, asset: str) -> str:
        key = (asset or "").strip().lower().replace("ё", "е")
        if not key:
            raise CryptoPriceError("Пустой тикер монеты.", code="unknown_asset")
        symbol = ASSET_ALIASES.get(key)
        if not symbol:
            raise CryptoPriceError(_UNKNOWN_ASSET_MSG, code="unknown_asset")
        return symbol

    async def get_price(self, asset: str, vs_currency: str = "usdt") -> dict[str, Any]:
        if not self._settings.enable_crypto_price:
            raise CryptoPriceError(
                "Цены криптовалют отключены: ENABLE_CRYPTO_PRICE=false.",
                code="disabled",
            )

        asset_key = (asset or "").strip().lower().replace("ё", "е")
        binance_symbol = self.resolve_binance_symbol(asset)

        vs = (vs_currency or self._settings.default_crypto_vs_currency or "usdt").strip().lower()
        if vs not in {"usdt", "usd"}:
            raise CryptoPriceError(
                "Сейчас поддерживается только пара к USDT (например: /price btc).",
                code="unsupported_currency",
            )

        base = self._settings.binance_base_url.rstrip("/")
        url = f"{base}/api/v3/ticker/price"
        params = {"symbol": binance_symbol}
        timeout = aiohttp.ClientTimeout(total=int(self._settings.binance_timeout or 30))

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        logger.warning(
                            "Binance returned non-JSON for symbol=%s status=%s",
                            binance_symbol,
                            response.status,
                        )
                        raise CryptoPriceError(_API_ERROR_MSG, code="api_error") from None

                    if response.status >= 400:
                        logger.warning(
                            "Binance error: symbol=%s status=%s body=%s",
                            binance_symbol,
                            response.status,
                            str(data)[:300],
                        )
                        raise CryptoPriceError(_API_ERROR_MSG, code="api_error")
        except CryptoPriceError:
            raise
        except Exception:
            logger.exception("Binance request failed for symbol=%s", binance_symbol)
            raise CryptoPriceError(_API_ERROR_MSG, code="api_error") from None

        if not isinstance(data, dict):
            raise CryptoPriceError(_API_ERROR_MSG, code="api_error")

        raw_price = data.get("price")
        if raw_price is None:
            raise CryptoPriceError(_API_ERROR_MSG, code="api_error")

        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            raise CryptoPriceError(_API_ERROR_MSG, code="api_error") from None

        return {
            "asset": asset_key or asset.strip().lower(),
            "symbol": binance_symbol,
            "price": price,
            "vs_currency": "USDT",
            "source": "Binance",
        }


def format_crypto_price_reply(data: dict[str, Any]) -> str:
    binance_symbol = str(data.get("symbol") or "")
    base = binance_symbol.replace("USDT", "") if binance_symbol.endswith("USDT") else binance_symbol
    price = float(data["price"])
    source = str(data.get("source") or "Binance")
    formatted = f"{price:,.2f}".replace(",", " ")
    return f"{base} сейчас стоит примерно {formatted} USDT\nИсточник: {source}"
