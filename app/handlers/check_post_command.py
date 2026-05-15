"""Manual scam check: /check and natural-language triggers."""

from __future__ import annotations

import logging
import re

from app.config import Settings
from app.handlers.owner_commands import is_owner_slash_command
from app.services.pending_post_store import PendingPostStore
from app.services.scam_check_service import ScamCheckService

logger = logging.getLogger(__name__)

_CHECK_CMD_RE = re.compile(r"^/check(?:@\S+)?(?:\s+post)?\s*$", re.IGNORECASE)
_CHECK_PHRASE_RE = re.compile(
    r"^(?:проверь\s+(?:пост|ссылки)|это\s+скам\??|скам\??)\s*$",
    re.IGNORECASE | re.UNICODE,
)

_NO_POST_REPLY = (
    "Не нашёл свежий пост для проверки. Перешли пост и напиши: проверь пост"
)


def check_post_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    raw = (event.message.message or "").strip()
    if not raw:
        return False
    if _CHECK_CMD_RE.match(raw):
        return True
    if raw.startswith("/"):
        return False
    return bool(_CHECK_PHRASE_RE.match(raw))


async def handle_check_post_command(
    event,
    *,
    settings: Settings,
    pending_store: PendingPostStore,
    scam_check: ScamCheckService,
) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return

    raw = (event.message.message or "").strip()
    if not (_CHECK_CMD_RE.match(raw) or _CHECK_PHRASE_RE.match(raw)):
        return

    owner_id = int(event.sender_id)
    post = pending_store.get_fresh(owner_id)
    if post is None:
        await event.reply(_NO_POST_REPLY)
        return

    logger.info("Manual scam check requested owner_id=%s message_id=%s", owner_id, post.message_id)
    try:
        message = await event.get_message()
    except Exception:
        message = event.message

    result = await scam_check.check_post(post, message=message)
    await event.reply(result)
