"""Private /ask command: only allowed Telegram user ids (Ollama)."""

from __future__ import annotations

import logging
import re

from app.config import Settings
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

_ASK_PATTERN = re.compile(r"^/ask(?:@\S+)?\s*(.*)$", re.DOTALL)
ASK_EMPTY_REPLY = "Напиши вопрос после /ask"


def ask_command_predicate(event) -> bool:
    """Private incoming (not from our account) messages that start with /ask."""
    if not event.message:
        return False
    if not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith("/ask")


async def handle_owner_ask(
    event,
    *,
    settings: Settings,
    router: LLMRouter,
) -> None:
    allowed = settings.ask_sender_ids
    if not allowed:
        return
    if not event.message or not event.is_private or event.sender_id not in allowed:
        return
    if getattr(event.message, "out", False):
        return

    raw = (event.message.message or "").strip()
    m = _ASK_PATTERN.match(raw)
    if not m:
        return

    query = (m.group(1) or "").strip()
    logger.info(
        "/ask from sender_id=%s chat_id=%s query_len=%s",
        event.sender_id,
        event.chat_id,
        len(query),
    )
    if not query:
        await event.reply(ASK_EMPTY_REPLY)
        return

    try:
        result = await router.ask_local(query)
        if not result.text:
            await event.reply(result.error or "Модель вернула пустой ответ. Проверь LLM и логи.")
            return
        await event.reply(result.text)
    except Exception:
        logger.exception("/ask failed for sender_id=%s", event.sender_id)
        await event.reply("Ошибка при обращении к LLM. Смотри логи сервиса.")
