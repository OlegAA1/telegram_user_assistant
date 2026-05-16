"""Forward original Telegram messages to targets."""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.tl.custom.message import Message
from telethon.tl.types import Channel, Chat

from app.config import coerce_telethon_chat

logger = logging.getLogger(__name__)


def _source_message_url(chat: Channel | Chat | object | None, message: Message) -> str:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message.id}"

    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        return ""
    raw_id = str(chat_id)
    if raw_id.startswith("-100"):
        return f"https://t.me/c/{raw_id[4:]}/{message.id}"
    return ""


class Forwarder:
    async def forward_original(
        self,
        client: TelegramClient,
        message: Message,
        targets: list[str],
    ) -> None:
        try:
            source_chat = await message.get_chat()
        except Exception:
            logger.exception("Failed to resolve source chat for message %s", message.id)
            source_chat = None
        source_url = _source_message_url(source_chat, message)

        for raw in targets:
            target = coerce_telethon_chat(raw)
            try:
                forwarded = await client.forward_messages(target, message)
                if source_url:
                    reply_to = getattr(forwarded, "id", None)
                    await client.send_message(
                        target,
                        f'<a href="{source_url}">CREATOR</a>',
                        link_preview=False,
                        parse_mode="html",
                        reply_to=reply_to,
                    )
            except Exception:
                logger.exception("Failed to forward message %s to %r", message.id, target)
