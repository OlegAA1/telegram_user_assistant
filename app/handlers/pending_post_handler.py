"""Save forwarded / link posts in the scam-check group for later /check."""

from __future__ import annotations

from app.config import Settings
from app.handlers.owner_commands import is_owner_slash_command
from app.handlers.scam_check_access import (
    MSG_POST_SAVED,
    is_allowed_sender,
    is_group_configured,
    is_manual_scam_enabled,
    is_scam_check_group_chat,
    is_scam_check_trigger,
    log_pending_saved,
)
from app.services.link_extractor import extract_from_message, message_text
from app.services.pending_post_store import PendingPostStore, serialize_entities


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
    if not event.message:
        return False
    if getattr(event.message, "out", False):
        return False
    if event.is_private:
        return False

    raw = (event.message.message or "").strip()
    if is_scam_check_trigger(raw):
        return False
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
    if not is_manual_scam_enabled(settings):
        return
    if not is_allowed_sender(settings, event.sender_id):
        return
    if not is_group_configured(settings):
        return
    if not is_scam_check_group_chat(event, settings):
        return
    if not pending_post_predicate(event):
        return

    msg = event.message
    text = message_text(msg)
    owner_id = int(event.sender_id)
    chat_id = int(event.chat_id)
    links = extract_from_message(msg)

    pending_store.save(
        owner_id=owner_id,
        message_id=int(msg.id),
        chat_id=chat_id,
        text=text,
        forward_title=_forward_title(msg),
        entities_json=serialize_entities(getattr(msg, "entities", None)),
    )
    log_pending_saved(
        owner_id=owner_id,
        chat_id=chat_id,
        message_id=int(msg.id),
        forwarded=_is_forwarded(msg),
        links=len(links),
    )
    await event.reply(MSG_POST_SAVED)
