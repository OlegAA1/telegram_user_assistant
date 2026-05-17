"""Archive messages from chats selected for daily summaries."""

from __future__ import annotations

import logging

from telethon import utils

from app.config import Settings
from app.services.daily_summary_store import DailySummaryStore

logger = logging.getLogger(__name__)


def _entity_title(entity) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(entity, "username", None)
    return f"@{username}" if username else str(getattr(entity, "id", "unknown"))


async def archive_summary_message(event, *, settings: Settings, store: DailySummaryStore) -> None:
    message = event.message
    if not message:
        return
    text = (event.raw_text or "").strip()
    has_media = bool(getattr(message, "media", None))
    if has_media and settings.summary_store_media:
        logger.warning("SUMMARY_STORE_MEDIA=true is reserved; media download is not implemented")
    if not text and not has_media:
        return

    chat = await event.get_chat()
    sender = await event.get_sender()
    chat_id = int(utils.get_peer_id(chat))
    sender_id = int(getattr(sender, "id", 0)) if sender is not None else None
    sender_name = _entity_title(sender) if sender is not None else ""
    store.save_message(
        chat_id=chat_id,
        chat_title=_entity_title(chat),
        chat_username=str(getattr(chat, "username", "") or ""),
        message_id=int(message.id),
        message_date=message.date,
        sender_id=sender_id,
        sender_name=sender_name,
        text=text,
        has_media=has_media,
    )
