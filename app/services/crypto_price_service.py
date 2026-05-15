"""Crypto spot prices via CoinGecko API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)


class CryptoPriceError(Exception):
    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# User alias -> CoinGecko id
ASSET_ALIASES: dict[str, str] = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "биткоин": "bitcoin",
    "биткоина": "bitcoin",
    "битка": "bitcoin",
    "биток": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "эфир": "ethereum",
    "эфира": "ethereum",
    "эфиру": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "солана": "solana",
    "соланы": "solana",
    "ton": "the-open-network",
    "toncoin": "the-open-network",
    "тон": "the-open-network",
    "тона": "the-open-network",
    "bnb": "binancecoin",
    "binancecoin": "binancecoin",
    "xrp": "ripple",
    "ripple": "ripple",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "доги": "dogecoin",
    "догикоин": "dogecoin",
    "usdt": "tether",
    "tether": "tether",
}

SYMBOL_BY_ID: dict[str, str] = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "the-open-network": "TON",
    "binancecoin": "BNB",
    "ripple": "XRP",
    "dogecoin": "DOGE",
    "tether": "USDT",
}


class CryptoPriceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve_asset_id(self, asset: str) -> str:
        key = (asset or "").strip().lower().replace("ё", "е")
        if not key:
            raise CryptoPriceError("Пустой тикер монеты.", code="unknown_asset")
        asset_id = ASSET_ALIASES.get(key)
        if not asset_id:
            raise CryptoPriceError(
                "Не понял, какую монету проверить. Например: цена btc, цена eth, цена sol",
                code="unknown_asset",
            )
        return asset_id

    async def get_price(self, asset: str, vs_currency: str = "usd") -> dict[str, Any]:
        if not self._settings.enable_crypto_price:
            raise CryptoPriceError(
                "Цены криптовалют отключены: ENABLE_CRYPTO_PRICE=false.",
                code="disabled",
            )

        asset_id = self.resolve_asset_id(asset)
        vs = (vs_currency or self._settings.default_crypto_vs_currency or "usd").strip().lower()
        if vs not in {"usd", "rub", "eur"}:
            vs = self._settings.default_crypto_vs_currency or "usd"

        base = self._settings.coingecko_base_url.rstrip("/")
        url = f"{base}/simple/price"
        params = {"ids": asset_id, "vs_currencies": vs}
        headers: dict[str, str] = {"Accept": "application/json"}
        api_key = (self._settings.coingecko_api_key or "").strip()
        if api_key:
            if "pro-api.coingecko.com" in base:
                headers["x-cg-pro-api-key"] = api_key
            else:
                headers["x-cg-demo-api-key"] = api_key

        timeout = aiohttp.ClientTimeout(total=int(self._settings.coingecko_timeout or 30))

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        logger.warning(
                            "CoinGecko returned non-JSON (status=%s)",
                            response.status,
                        )
                        raise CryptoPriceError(
                            "Не смог получить цену через CoinGecko. Попробуй позже.",
                            code="api_error",
                        ) from None

                    if response.status >= 400:
                        logger.warning(
                            "CoinGecko error: status=%s body=%s",
                            response.status,
                            str(data)[:500],
                        )
                        raise CryptoPriceError(
                            "Не смог получить цену через CoinGecko. Попробуй позже.",
                            code="api_error",
                        )
        except CryptoPriceError:
            raise
        except Exception:
            logger.exception("CoinGecko request failed")
            raise CryptoPriceError(
                "Не смог получить цену через CoinGecko. Попробуй позже.",
                code="api_error",
            ) from None

        if not isinstance(data, dict):
            raise CryptoPriceError(
                "Не смог получить цену через CoinGecko. Попробуй позже.",
                code="api_error",
            )

        coin = data.get(asset_id)
        if not isinstance(coin, dict):
            raise CryptoPriceError(
                "Не смог получить цену через CoinGecko. Попробуй позже.",
                code="api_error",
            )

        raw_price = coin.get(vs)
        if raw_price is None:
            raise CryptoPriceError(
                "Не смог получить цену через CoinGecko. Попробуй позже.",
                code="api_error",
            )

        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            raise CryptoPriceError(
                "Не смог получить цену через CoinGecko. Попробуй позже.",
                code="api_error",
            ) from None

        symbol = SYMBOL_BY_ID.get(asset_id, asset_id.upper()[:6])
        return {
            "asset_id": asset_id,
            "symbol": symbol,
            "vs_currency": vs,
            "price": price,
            "source": "CoinGecko",
        }


def format_crypto_price_reply(data: dict[str, Any]) -> str:
    symbol = str(data.get("symbol") or "?")
    price = float(data["price"])
    vs = str(data.get("vs_currency") or "usd").lower()
    source = str(data.get("source") or "CoinGecko")

    if vs == "usd":
        body = f"{symbol} сейчас стоит примерно ${price:,.2f}"
    elif vs == "rub":
        body = f"{symbol} сейчас стоит примерно {price:,.2f} RUB"
    elif vs == "eur":
        body = f"{symbol} сейчас стоит примерно €{price:,.2f}"
    else:
        body = f"{symbol} сейчас стоит примерно {price:,.2f} {vs.upper()}"

    return f"{body}\nИсточник: {source}"
