"""Access control and triggers for manual scam-check (group-only)."""

from __future__ import annotations

import logging
import re

from app.config import Settings

logger = logging.getLogger(__name__)

_CHECK_CMD_RE = re.compile(r"^/check(?:@\S+)?(?:\s+post)?\s*$", re.IGNORECASE)
_CHECK_PHRASE_RE = re.compile(
    r"^(?:проверь\s+(?:пост|ссылки)|это\s+скам\??|скам\??)\s*$",
    re.IGNORECASE | re.UNICODE,
)

MSG_NO_GROUP_CONFIGURED = "SCAM_CHECK_GROUP_ID не задан в .env."
MSG_WRONG_CHAT = "Проверка постов доступна только в специальной группе."
MSG_DM_REDIRECT = (
    "Для проверки постов перешли пост в специальную группу и напиши /check "
    "или «проверь пост»."
)
MSG_NO_FRESH_POST = (
    "Не нашёл свежий пост для проверки. Перешли пост в эту группу и напиши /check."
)
MSG_POST_SAVED = (
    "Пост сохранил. Напиши /check или «проверь пост», чтобы проверить ссылки."
)
MSG_CHECKING_LINKS = "Проверяю ссылки…"


def is_scam_check_trigger(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _CHECK_CMD_RE.match(raw):
        return True
    if raw.startswith("/"):
        return False
    return bool(_CHECK_PHRASE_RE.match(raw))


def is_allowed_sender(settings: Settings, sender_id: int | None) -> bool:
    return bool(settings.ask_sender_ids and sender_id in settings.ask_sender_ids)


def is_manual_scam_enabled(settings: Settings) -> bool:
    return settings.enable_manual_scam_check


def is_group_configured(settings: Settings) -> bool:
    return settings.scam_check_group_id is not None


def event_chat_id(event) -> int | None:
    if event.chat_id is None:
        return None
    return int(event.chat_id)


def is_scam_check_group_chat(event, settings: Settings) -> bool:
    gid = settings.scam_check_group_id
    if gid is None:
        return False
    cid = event_chat_id(event)
    return cid is not None and cid == gid


def log_wrong_chat(event, settings: Settings) -> None:
    logger.info(
        "scam check ignored: wrong chat chat_id=%s expected=%s sender_id=%s",
        event_chat_id(event),
        settings.scam_check_group_id,
        getattr(event, "sender_id", None),
    )


def log_no_group_configured() -> None:
    logger.info("scam check skipped: no group configured")


def log_pending_saved(*, owner_id: int, chat_id: int, message_id: int, forwarded: bool, links: int) -> None:
    logger.info(
        "pending post saved: owner_id=%s chat_id=%s message_id=%s forwarded=%s links=%s",
        owner_id,
        chat_id,
        message_id,
        forwarded,
        links,
    )


def log_scam_check_started(*, owner_id: int, message_id: int, links: int) -> None:
    logger.info(
        "scam check started: owner_id=%s message_id=%s links=%s",
        owner_id,
        message_id,
        links,
    )
