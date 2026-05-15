"""Private /search command for allowed senders."""

from __future__ import annotations

import re

from app.config import Settings
from app.services.llm_router import LLMRouter
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

    results = await search.search(query)
    if not results:
        if not settings.enable_web_search:
            await event.reply("Web search выключен: ENABLE_WEB_SEARCH=false.")
            return
        result = await router.ask_cloud(
            f"Пользователь запросил актуальную информацию: {query}\n"
            "Web search provider пока не подключён. Объясни, что нужен внешний search provider.",
        )
        await event.reply(result.text or result.error)
        return

    lines = []
    for i, item in enumerate(results[:5], start=1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        snippet = item.get("snippet", "")
        lines.append(f"{i}. {title}\n{url}\n{snippet}")
    summary_prompt = (
        f"Summarize these web search results for query: {query}\n\n"
        + "\n\n".join(lines)
    )
    result = await router.ask_cloud(summary_prompt)
    await event.reply(result.text or "\n\n".join(lines))
