"""Forward original Telegram messages to targets."""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from app.config import coerce_telethon_chat

logger = logging.getLogger(__name__)


class Forwarder:
    async def forward_original(
        self,
        client: TelegramClient,
        message: Message,
        targets: list[str],
    ) -> None:
        for raw in targets:
            target = coerce_telethon_chat(raw)
            try:
                await client.forward_messages(target, message)
            except Exception:
                logger.exception("Failed to forward message %s to %r", message.id, target)
