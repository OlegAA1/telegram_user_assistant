"""Natural-language private messages for allowed senders (intent → remind or LLM)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser

from app.config import Settings
from app.services.llm_service import LLMService
from app.services.llm_router import LLMRouter
from app.services.reminder_store import ReminderStore
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)

UNKNOWN_REPLY = (
    "Не понял команду. Можешь написать: напомни в 23:30 открыть сайт "
    "или использовать /ask и /remind."
)

HELP_REPLY = """Доступные команды:

? — показать эту памятку
/ask вопрос — спросить локальную Qwen/Ollama
/cloud вопрос — спросить OpenRouter (расходует cloud-лимит)
/analyze текст — глубокий анализ через OpenRouter
/search запрос — поиск/актуальная информация (если включён web search)
/provider — показать модели, режимы и лимиты

Напоминания:
/remind 2026-05-21 18:30 текст — поставить напоминание на дату/время
/remind in 45m текст — напомнить через 45 минут
/remind list — список напоминаний
/remind cancel ID — отменить напоминание

Обычный текст без команды:
напомни мне в 23:30 открыть сайт — ассистент попробует сам понять и создать напоминание
напиши код для Telethon — локальная Qwen
что сегодня с биткоином? — web/current intent
"""


def assistant_natural_predicate(event) -> bool:
    if not event.message:
        return False
    if not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    raw = (event.message.message or "").strip()
    if not raw:
        return False
    if raw.startswith("/"):
        return False
    return True


def _extract_json_object(raw: str) -> dict | None:
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


async def handle_assistant_natural(
    event,
    *,
    settings: Settings,
    llm: LLMService,
    router: LLMRouter,
    reminders: ReminderStore,
    search: WebSearchService,
) -> None:
    if not settings.ask_sender_ids:
        return
    if not event.message or not event.is_private or event.sender_id not in settings.ask_sender_ids:
        return
    if getattr(event.message, "out", False):
        return

    user_text = (event.message.message or "").strip()
    if not user_text or user_text.startswith("/"):
        return
    if user_text == "?":
        await event.reply(HELP_REPLY)
        return

    uid = int(event.sender_id)
    chat_id = int(event.chat_id)

    raw_llm = ""
    try:
        raw_llm = await llm.intent_detection(user_text)
    except Exception:
        logger.exception("intent_detection failed, fallback to ask_llm")
    parsed = _extract_json_object(raw_llm) if raw_llm else None

    if not isinstance(parsed, dict):
        logger.info("Intent fallback to ask_llm (invalid JSON)")
        result = await router.ask_local(user_text)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return

    intent = str(parsed.get("intent", "unknown")).strip().lower()

    if intent == "create_reminder":
        dt_text = (parsed.get("datetime_text") or parsed.get("when") or "").strip()
        body = (parsed.get("reminder_body") or parsed.get("body") or "").strip()
        if not dt_text or not body:
            logger.warning("create_reminder missing fields: %s", parsed)
            result = await router.ask_local(user_text)
            await event.reply(result.text or result.error or "Пустой ответ модели.")
            return

        tz = ZoneInfo(settings.reminder_tz)
        dp_settings = {
            "TIMEZONE": settings.reminder_tz,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(tz),
        }
        when = dateparser.parse(dt_text, languages=["ru", "en"], settings=dp_settings)
        if when is None:
            await event.reply(
                f"Не удалось разобрать время «{dt_text}». "
                "Попробуй явнее, например: «сегодня в 23:30», или /remind.",
            )
            return
        if when.tzinfo is None:
            when = when.replace(tzinfo=tz)
        fire_utc = when.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if fire_utc <= now_utc:
            await event.reply("Получилось время в прошлом. Уточни дату или время.")
            return

        rid = reminders.add(uid, chat_id, body, fire_utc)
        local_str = fire_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        today = datetime.now(tz).date()
        fire_date = fire_utc.astimezone(tz).date()
        hm = fire_utc.astimezone(tz).strftime("%H:%M")
        if fire_date == today:
            human_when = f"сегодня в {hm}"
        elif fire_date == today + timedelta(days=1):
            human_when = f"завтра в {hm}"
        else:
            human_when = local_str
        logger.info("assistant create_reminder id=%s user=%s at=%s", rid, uid, local_str)
        await event.reply(f"Ок, напомню {human_when}: {body}")
        return

    if intent in {"ask_llm", "local_ask"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_local(q)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return

    if intent in {"cloud_ask", "deep_analysis"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_cloud(q)
        await event.reply(result.text or result.error)
        return

    if intent == "web_search":
        q = (parsed.get("query") or parsed.get("text") or user_text).strip()
        results = await search.search(q)
        if not results:
            if not settings.enable_web_search:
                await event.reply("Для актуальной информации включи ENABLE_WEB_SEARCH или используй /cloud.")
                return
            result = await router.ask_cloud(
                f"Пользователь запросил актуальную информацию: {q}\n"
                "Web search provider пока не подключён. Объясни, что нужен search provider.",
            )
            await event.reply(result.text or result.error)
            return
        snippets = "\n\n".join(
            f"{i}. {item.get('title', 'Untitled')}\n{item.get('url', '')}\n{item.get('snippet', '')}"
            for i, item in enumerate(results[:5], start=1)
        )
        result = await router.ask_cloud(f"Summarize web results for: {q}\n\n{snippets}")
        await event.reply(result.text or snippets)
        return

    await event.reply(UNKNOWN_REPLY)
