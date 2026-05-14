"""Owner-only /ask command in private chats (Ollama)."""

from __future__ import annotations

import logging
import re

from telethon import events

from app.config import Settings
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_ASK_PATTERN = re.compile(r"^/ask(?:@\S+)?\s*(.*)$", re.DOTALL)
ASK_EMPTY_REPLY = "Напиши вопрос после /ask"


def owner_ask_predicate(event: events.NewMessage.Event, owner_id: int) -> bool:
    if not event.is_private:
        return False
    if event.sender_id != owner_id:
        return False
    msg = event.message.message if event.message and event.message.message else ""
    return msg.lstrip().startswith("/ask")


async def handle_owner_ask(
    event: events.NewMessage.Event,
    *,
    settings: Settings,
    llm: LLMService,
) -> None:
    if settings.owner_id is None:
        return
    if not event.is_private or event.sender_id != settings.owner_id:
        return

    raw = (event.message.message or "").strip() if event.message else ""
    m = _ASK_PATTERN.match(raw)
    if not m:
        return

    query = (m.group(1) or "").strip()
    if not query:
        await event.reply(ASK_EMPTY_REPLY)
        return

    try:
        reply = await llm.generate_plain(query)
        if not reply:
            await event.reply("Модель вернула пустой ответ. Проверь LLM и логи.")
            return
        await event.reply(reply)
    except Exception:
        logger.exception("/ask failed for owner_id=%s", settings.owner_id)
        await event.reply("Ошибка при обращении к LLM. Смотри логи сервиса.")
