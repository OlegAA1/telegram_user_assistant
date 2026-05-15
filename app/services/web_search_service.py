"""Web search abstraction.

The first implementation is intentionally a stub: it defines the interface and
keeps the app safe until Tavily/SerpAPI/Brave/Google CSE is wired in.
"""

from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger(__name__)


class WebSearchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, query: str) -> list[dict]:
        if not self._settings.enable_web_search:
            logger.info("Web search requested but ENABLE_WEB_SEARCH=false")
            return []
        logger.warning(
            "Web search provider %r is not implemented yet",
            self._settings.web_search_provider or "stub",
        )
        return []
