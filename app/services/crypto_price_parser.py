"""Deterministic crypto price intent detection (before LLM intent parser)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.crypto_price_service import ASSET_ALIASES

_PRICE_KEYWORDS_RE = re.compile(
    r"(?:^|\s)(?:цена|курс|стоимость)(?:\s|$)|"
    r"(?:^|\s)сколько\s+(?:сейчас\s+)?стоит\b|"
    r"(?:^|\s)какая\s+(?:сейчас\s+)?(?:цена|стоимость)\b|"
    r"(?:^|\s)какой\s+(?:сейчас\s+)?(?:курс|цена)\b",
    re.IGNORECASE | re.UNICODE,
)

_CURRENCY_RE = re.compile(
    r"\b(rub|руб(?:лей|ля|ль)?|₽|usd|доллар(?:а|ов|ах)?|\$|eur|евро)\b",
    re.IGNORECASE | re.UNICODE,
)

_STRIP_NOISE_RE = re.compile(
    r"\b(?:цена|курс|стоимость|сколько|стоит|сейчас|какая|какой|какие|"
    r"примерно|актуальн(?:ая|ый|ое)?|текущ(?:ая|ий|ее)?|в|на|у|за|монет[аы]?|"
    r"криптовалют[аы]?|коин[аы]?|токен[аы]?)\b",
    re.IGNORECASE | re.UNICODE,
)

# "btc rub", "eth usd" without price keywords
_TICKER_PAIR_RE = re.compile(
    r"^\s*([a-zа-яё0-9\-]+)\s+(rub|usd|руб(?:лей|ля|ль)?|доллар(?:а|ов|ах)?|\$)\s*$",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True)
class ParsedCryptoPrice:
    asset: str
    vs_currency: str


def _normalize(text: str) -> str:
    return (text or "").strip().lower().replace("ё", "е")


def _detect_vs_currency(text: str, default_vs: str) -> str:
    for m in _CURRENCY_RE.finditer(text):
        token = m.group(1).lower().replace("ё", "е")
        if token in {"rub", "руб", "рублей", "рубля", "рубль", "₽"}:
            return "rub"
        if token in {"usd", "доллар", "доллара", "долларов", "долларах", "$"}:
            return "usd"
        if token in {"eur", "евро"}:
            return "eur"
    return (default_vs or "usd").strip().lower()


def _find_asset_token(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    # Longest alias first (e.g. "the-open-network" before "ton")
    for alias in sorted(ASSET_ALIASES, key=len, reverse=True):
        pattern = rf"(?:^|[\s,.:;!?«»\"'(\[]){re.escape(alias)}(?:$|[\s,.:;!?»\"')\]])"
        if re.search(pattern, normalized):
            return alias

    # Remaining single token after stripping noise
    cleaned = _STRIP_NOISE_RE.sub(" ", normalized)
    cleaned = re.sub(r"[^\w\-]+", " ", cleaned)
    tokens = [t for t in cleaned.split() if t]
    for token in tokens:
        if token in ASSET_ALIASES:
            return token
    return None


def looks_like_crypto_price_query(text: str) -> bool:
    s = _normalize(text)
    if not s:
        return False
    if _PRICE_KEYWORDS_RE.search(s):
        return True
    if _TICKER_PAIR_RE.match(s):
        return True
    # Bare ticker with price context words nearby
    asset = _find_asset_token(s)
    if asset and any(w in s for w in ("цена", "курс", "стоит", "стоимость")):
        return True
    return False


def try_parse_crypto_price(text: str, *, default_vs: str = "usd") -> ParsedCryptoPrice | None:
    """Return asset + vs_currency if text looks like a crypto price request."""
    raw = (text or "").strip()
    if not raw or not looks_like_crypto_price_query(raw):
        return None

    vs = _detect_vs_currency(raw, default_vs)

    m = _TICKER_PAIR_RE.match(raw)
    if m:
        asset = m.group(1).strip().lower().replace("ё", "е")
        if asset in ASSET_ALIASES:
            return ParsedCryptoPrice(asset=asset, vs_currency=vs)

    asset = _find_asset_token(raw)
    if not asset:
        return None
    return ParsedCryptoPrice(asset=asset, vs_currency=vs)
