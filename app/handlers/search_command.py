"""Private /search command for allowed senders."""

from __future__ import annotations

from datetime import date
import re

from app.config import Settings
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU, SEARCH_SUMMARY_SYSTEM_RU
from app.services.llm_router import LLMRouter
from app.services.reply_context import get_replied_assistant_text
from app.services.web_search_service import WebSearchService

_SEARCH_PATTERN = re.compile(r"^/search(?:@\S+)?\s*(.*)$", re.DOTALL)


def search_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith("/search")


async def handle_search_command(
    event,
    *,
    settings: Settings,
    search: WebSearchService,
    router: LLMRouter,
) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    raw = (event.message.message or "").strip()
    m = _SEARCH_PATTERN.match(raw)
    if not m:
        return
    query = (m.group(1) or "").strip()
    if not query:
        await event.reply("Напиши запрос после /search")
        return

    reply_context = await get_replied_assistant_text(event)
    search_query = query
    if reply_context:
        search_query = f"{query}\n\nКонтекст предыдущего ответа ассистента:\n{reply_context[-1000:]}"
    reply_context_block = (
        f"Контекст предыдущего ответа ассистента:\n{reply_context}\n\n"
        if reply_context
        else ""
    )

    results = await search.search(search_query)
    if not results:
        if not settings.enable_web_search:
            await event.reply("Web search выключен: ENABLE_WEB_SEARCH=false.")
            return
        result = await router.ask_cloud(
            f"Пользователь запросил актуальную информацию: {query}\n"
            f"{reply_context_block}"
            "Web search (Tavily) не вернул результатов. Кратко ответь по общим знаниям "
            "и укажи, что данные могут быть неактуальны.",
            system=ASSISTANT_SYSTEM_RU,
        )
        await event.reply(result.text or result.error)
        return

    lines = []
    for i, item in enumerate(results[:5], start=1):
        title = item.get("title", "Без названия")
        url = item.get("url", "")
        snippet = item.get("snippet", "")
        published_date = item.get("published_date", "")
        score = item.get("score", "")
        meta = []
        if published_date:
            meta.append(f"published_date={published_date}")
        if score:
            meta.append(f"score={score}")
        meta_line = f"\nМетаданные: {', '.join(meta)}" if meta else ""
        lines.append(f"{i}. {title}\n{url}{meta_line}\n{snippet}")
    sources_block = "Найденные источники:\n\n" + "\n\n".join(lines)
    summary_prompt = (
        f"Сегодня: {date.today().isoformat()}\n"
        f"Запрос пользователя: {query}\n\n"
        f"{reply_context_block}"
        f"Результаты поиска:\n\n" + "\n\n".join(lines) + "\n\n"
        "Сделай краткую сводку на русском языке. Для актуальных запросов явно отдели "
        "подтвержденные свежими источниками факты от устаревших или неподтвержденных."
    )
    result = await router.ask_cloud(summary_prompt, system=SEARCH_SUMMARY_SYSTEM_RU)
    await event.reply(result.text or sources_block)
