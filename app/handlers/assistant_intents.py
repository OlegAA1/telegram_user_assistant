"""Intent helpers for the private conversational assistant."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

REMINDER_ACTION_KEYWORDS = (
    "напомни",
    "напомнить",
    "напоминание",
    "напоминания",
    "напоминаний",
    "будильник",
    "отмени",
    "отменить",
    "удали",
    "удалить",
)

COMMAND_ACTION_KEYWORDS = REMINDER_ACTION_KEYWORDS + (
    "помощь",
    "команды",
    "что ты умеешь",
    "статус",
    "здоровье",
    "health",
    "ollama",
    "tailscale",
    "сервер",
    "нагрузка",
    "load",
    "модель",
    "провайдер",
    "provider",
    "диалоги",
    "каналы",
    "группы",
    "пользователи",
    "подпишись",
    "подписаться",
    "добавь канал",
    "join",
    "/join",
)

ACTION_UNCLEAR_REPLY = (
    "Похоже, ты просишь выполнить действие, но я не смог безопасно распознать его. "
    "Напиши конкретнее, например: «покажи напоминания», «отмени #3» или «проверь health»."
)


def looks_like_reminder_action_text(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in REMINDER_ACTION_KEYWORDS)


def looks_like_command_action_text(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in COMMAND_ACTION_KEYWORDS)


def extract_json_object(raw: str) -> dict | None:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        idx = s.index("{")
    except ValueError:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[idx:])
    except json.JSONDecodeError as exc:
        logger.warning("Intent JSON parse failed: %s", exc)
        return None
    return obj if isinstance(obj, dict) else None


async def classify_assistant_intent(llm: LLMService, user_text: str) -> dict | None:
    try:
        raw_llm = await llm.intent_detection(user_text)
    except Exception:
        logger.exception("intent_detection failed")
        return None
    return extract_json_object(raw_llm) if raw_llm else None
