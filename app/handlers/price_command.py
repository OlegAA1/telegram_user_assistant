"""Private /price command for allowed senders."""

from __future__ import annotations

import logging
import re

from app.config import Settings
from app.services.crypto_price_service import (
    CryptoPriceError,
    CryptoPriceService,
    format_crypto_price_reply,
)

logger = logging.getLogger(__name__)

_PRICE_PATTERN = re.compile(r"^/price(?:@\S+)?\s*(.*)$", re.DOTALL)


def price_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith("/price")


async def handle_price_command(
    event,
    *,
    settings: Settings,
    crypto: CryptoPriceService,
) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return

    raw = (event.message.message or "").strip()
    m = _PRICE_PATTERN.match(raw)
    if not m:
        return

    args = (m.group(1) or "").strip().split()
    if not args:
        await event.reply("Напиши монету после /price, например: /price btc")
        return

    asset = args[0]
    vs = settings.default_crypto_vs_currency

    try:
        data = await crypto.get_price(asset, vs)
        await event.reply(format_crypto_price_reply(data))
    except CryptoPriceError as exc:
        await event.reply(exc.message)
    except Exception:
        logger.exception("/price failed for sender_id=%s", event.sender_id)
        await event.reply(
            "Не смог получить цену через Binance. "
            "Возможно, такой пары нет или Binance временно недоступен.",
        )
