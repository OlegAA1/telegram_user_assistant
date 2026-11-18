"""Web search service with Tavily provider."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)

_CURRENT_INFO_RE = re.compile(
    r"\b("
    r"актуальн|сейчас|сегодня|последн|новост|новые|свеж|"
    r"latest|current|today|now|recent|news|new"
    r")\b",
    re.IGNORECASE,
)


class WebSearchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(
        self,
        query: str,
        *,
        time_range: str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, str]]:
        """time_range / max_results override .env defaults for this call only."""
        query = (query or "").strip()
        if not query:
            return []

        if not self._settings.enable_web_search:
            logger.info("Web search requested but ENABLE_WEB_SEARCH=false")
            return []

        provider = (self._settings.web_search_provider or "").lower().strip()
        if provider != "tavily":
            logger.warning("Unsupported web search provider: %r", provider)
            return []

        if not self._settings.web_search_api_key:
            logger.warning("WEB_SEARCH_API_KEY is empty")
            return []

        return await self._search_tavily(query, time_range=time_range, max_results=max_results)

    @property
    def can_extract(self) -> bool:
        provider = (self._settings.web_search_provider or "").lower().strip()
        return provider == "tavily" and bool(self._settings.web_search_api_key)

    async def extract(self, urls: list[str]) -> dict[str, str]:
        """Return {url: page text} via Tavily Extract (pages are fetched on Tavily side)."""
        urls = [u for u in urls if u]
        if not urls or not self.can_extract:
            return {}

        payload: dict[str, Any] = {
            "api_key": self._settings.web_search_api_key,
            "urls": urls[:20],
            "extract_depth": "basic",
            "format": "text",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.web_search_api_key}",
        }
        timeout = aiohttp.ClientTimeout(total=int(self._settings.web_search_timeout or 30) + 15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://api.tavily.com/extract",
                    json=payload,
                    headers=headers,
                ) as response:
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        logger.exception(
                            "Tavily extract returned non-JSON response (status=%s)",
                            response.status,
                        )
                        return {}
                    if response.status >= 400:
                        logger.warning("Tavily extract failed: status=%s data=%s", response.status, data)
                        return {}
        except Exception:
            logger.exception("Tavily extract request failed")
            return {}

        out: dict[str, str] = {}
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            content = str(item.get("raw_content") or "").strip()
            if url and content:
                out[url] = content
        failed = data.get("failed_results") or []
        if failed:
            logger.info("Tavily extract failed for %s url(s)", len(failed))
        return out

    async def _search_tavily(
        self,
        query: str,
        *,
        time_range: str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, str]]:
        url = "https://api.tavily.com/search"
        max_results = max_results or self._settings.web_search_max_results or 5
        timeout_seconds = self._settings.web_search_timeout or 30
        search_depth = self._settings.web_search_depth or "advanced"
        topic = self._settings.web_search_topic or "general"
        if time_range is None:
            time_range = self._settings.web_search_time_range
        if _CURRENT_INFO_RE.search(query) and not time_range:
            time_range = "month"

        payload: dict[str, Any] = {
            "api_key": self._settings.web_search_api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": int(max_results),
            "auto_parameters": self._settings.web_search_auto_parameters,
        }
        if topic in {"general", "news", "finance"}:
            payload["topic"] = topic
        if time_range in {"day", "week", "month", "year", "d", "w", "m", "y"}:
            payload["time_range"] = time_range
        if search_depth == "advanced":
            payload["chunks_per_source"] = max(
                1,
                min(int(self._settings.web_search_chunks_per_source), 3),
            )

        timeout = aiohttp.ClientTimeout(total=int(timeout_seconds))

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        logger.exception(
                            "Tavily search returned non-JSON response (status=%s)",
                            response.status,
                        )
                        return []

                    if response.status >= 400:
                        logger.warning(
                            "Tavily search failed: status=%s data=%s",
                            response.status,
                            data,
                        )
                        return []

        except Exception:
            logger.exception("Tavily search request failed")
            return []

        raw_results = data.get("results") or []
        results: list[dict[str, str]] = []

        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Untitled")
            link = str(item.get("url") or "")
            snippet = str(item.get("content") or item.get("snippet") or "")
            published_date = str(item.get("published_date") or item.get("publishedDate") or "")
            score = item.get("score")

            if not link:
                continue

            result = {
                "title": title,
                "url": link,
                "snippet": snippet,
            }
            if published_date:
                result["published_date"] = published_date
            if score is not None:
                result["score"] = str(score)
            results.append(result)

        return results
