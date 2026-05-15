"""Web search service with Tavily provider."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)


class WebSearchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, query: str) -> list[dict[str, str]]:
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

        return await self._search_tavily(query)

    async def _search_tavily(self, query: str) -> list[dict[str, str]]:
        url = "https://api.tavily.com/search"
        max_results = self._settings.web_search_max_results or 5
        timeout_seconds = self._settings.web_search_timeout or 30

        payload: dict[str, Any] = {
            "api_key": self._settings.web_search_api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": int(max_results),
        }

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

            if not link:
                continue

            results.append(
                {
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                }
            )

        return results
