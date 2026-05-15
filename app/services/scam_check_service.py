"""Manual scam/phishing check for a pending forwarded post."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.services.link_extractor import domain_from_url, extract_from_message, message_text
from app.services.openrouter_service import OpenRouterService
from app.services.pending_post_store import PendingPost
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ScamCheckService:
    def __init__(
        self,
        settings: Settings,
        *,
        search: WebSearchService,
        openrouter: OpenRouterService,
    ) -> None:
        self._settings = settings
        self._search = search
        self._openrouter = openrouter
        self._system_prompt = self._load_system_prompt()

    @staticmethod
    def _load_system_prompt() -> str:
        path = _PROJECT_ROOT / "prompts" / "scam_check_analysis.txt"
        if not path.is_file():
            raise FileNotFoundError(f"Scam check prompt not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    async def check_post(self, post: PendingPost, *, message=None) -> str:
        if not self._settings.enable_manual_scam_check:
            return "Ручная проверка постов отключена: ENABLE_MANUAL_SCAM_CHECK=false."

        if not self._settings.scam_check_use_openrouter:
            return "AI-проверка отключена: SCAM_CHECK_USE_OPENROUTER=false."

        if not self._openrouter.is_configured:
            return "OpenRouter не настроен, не могу сделать AI-проверку ссылок."

        links = extract_from_message(message) if message is not None else []
        if not links:
            links = _links_from_stored_text(post.text)

        if not links:
            return "В посте не нашёл ссылок для проверки."

        max_links = self._settings.scam_check_max_links
        links = links[:max_links]

        search_notes: list[str] = []
        web_enabled = self._settings.enable_web_search
        max_q = self._settings.scam_check_max_searches_per_link

        if web_enabled:
            for i, link in enumerate(links, start=1):
                domain = domain_from_url(link)
                queries = [
                    f"{domain} scam",
                    f"{domain} phishing crypto",
                ][:max_q]
                parts: list[str] = []
                for q in queries:
                    results = await self._search.search(q)
                    if not results:
                        parts.append(f"  • «{q}»: результатов нет")
                        continue
                    snippets = []
                    for r in results[:2]:
                        title = r.get("title", "")
                        url = r.get("url", "")
                        snip = (r.get("snippet") or "")[:200]
                        snippets.append(f"{title} ({url}): {snip}")
                    parts.append(f"  • «{q}»:\n    " + "\n    ".join(snippets))
                search_notes.append(f"Ссылка {i} ({link}):\n" + "\n".join(parts))
        else:
            search_notes.append(
                "Web search выключен (ENABLE_WEB_SEARCH=false). "
                "Проверка ограничена: только текст поста и список ссылок.",
            )

        forward_line = f"Источник пересылки: {post.forward_title}\n" if post.forward_title else ""
        user_prompt = (
            f"{forward_line}"
            f"Текст поста:\n{post.text or '(пусто)'}\n\n"
            f"Найденные ссылки ({len(links)}):\n"
            + "\n".join(f"{i}. {u}" for i, u in enumerate(links, start=1))
            + "\n\n"
            f"Результаты веб-поиска:\n"
            + "\n\n".join(search_notes)
        )

        logger.info(
            "Scam check: owner_id=%s message_id=%s links=%s web_search=%s",
            post.owner_id,
            post.message_id,
            len(links),
            web_enabled,
        )

        out = await self._openrouter.generate(user_prompt, system=self._system_prompt)
        if out:
            return out.strip()
        err = self._openrouter.last_error or "пустой ответ"
        return f"Не удалось получить анализ от OpenRouter: {err}"


def _links_from_stored_text(text: str) -> list[str]:
    from app.services.link_extractor import extract

    return extract(text or "")
