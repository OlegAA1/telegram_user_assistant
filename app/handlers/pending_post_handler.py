"""Save forwarded / link posts for later manual /check."""

from __future__ import annotations

import logging

from app.config import Settings
from app.handlers.check_post_command import check_post_predicate
from app.handlers.owner_commands import is_owner_slash_command
from app.services.link_extractor import extract_from_message, message_text
from app.services.pending_post_store import PendingPostStore, serialize_entities

logger = logging.getLogger(__name__)

_SAVED_REPLY = "Пост сохранил. Напиши «проверь пост» или /check, если нужно проверить ссылки."


def _is_forwarded(message) -> bool:
    if getattr(message, "fwd_from", None):
        return True
    if getattr(message, "forward", None):
        return True
    return False


def _forward_title(message) -> str | None:
    fwd = getattr(message, "fwd_from", None)
    if fwd:
        name = getattr(fwd, "from_name", None)
        if name:
            return str(name)
    forward = getattr(message, "forward", None)
    if forward:
        chat = getattr(forward, "chat", None)
        if chat and getattr(chat, "title", None):
            return str(chat.title)
        sender = getattr(forward, "sender", None)
        if sender:
            title = getattr(sender, "title", None) or getattr(sender, "first_name", None)
            if title:
                return str(title)
    return None


def pending_post_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    if check_post_predicate(event):
        return False

    raw = (event.message.message or "").strip()
    if is_owner_slash_command(raw):
        return False
    if raw == "?":
        return False

    msg = event.message
    if _is_forwarded(msg):
        return True
    if extract_from_message(msg):
        return True
    return False


async def handle_pending_post(
    event,
    *,
    settings: Settings,
    pending_store: PendingPostStore,
) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    if not settings.enable_manual_scam_check:
        return
    if not pending_post_predicate(event):
        return

    msg = event.message
    text = message_text(msg)
    owner_id = int(event.sender_id)

    pending_store.save(
        owner_id=owner_id,
        message_id=int(msg.id),
        chat_id=int(event.chat_id),
        text=text,
        forward_title=_forward_title(msg),
        entities_json=serialize_entities(getattr(msg, "entities", None)),
    )
    logger.info(
        "Pending post saved owner_id=%s message_id=%s forwarded=%s links=%s",
        owner_id,
        msg.id,
        _is_forwarded(msg),
        len(extract_from_message(msg)),
    )
    await event.reply(_SAVED_REPLY)
