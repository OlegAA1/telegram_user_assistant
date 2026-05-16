"""Helpers for continuing private assistant conversations via Telegram replies."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

REPLY_CONTEXT_MAX_CHARS = 4000


async def get_replied_assistant_text(event, *, max_chars: int = REPLY_CONTEXT_MAX_CHARS) -> str:
    reply_id = getattr(event.message, "reply_to_msg_id", None)
    if not reply_id:
        return ""
    try:
        replied = await event.get_reply_message()
    except Exception:
        logger.exception("Failed to load replied message for assistant follow-up")
        return ""
    if not replied or not getattr(replied, "out", False):
        return ""

    previous = (getattr(replied, "raw_text", None) or getattr(replied, "message", "") or "").strip()
    if not previous:
        return ""
    if len(previous) > max_chars:
        previous = previous[-max_chars:]
    return previous


async def build_reply_followup_prompt(event, user_text: str) -> str:
    previous = await get_replied_assistant_text(event)
    if not previous:
        return ""
    return (
        "Пользователь отвечает реплаем на твой предыдущий ответ. "
        "Продолжи диалог с учетом контекста, не начинай заново.\n\n"
        f"Предыдущий ответ ассистента:\n{previous}\n\n"
        f"Новая просьба пользователя:\n{user_text}"
    )
