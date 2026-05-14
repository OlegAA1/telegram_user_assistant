"""Filter messages by source chats and keywords."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telethon import utils

from app.config import Settings, coerce_telethon_chat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterService:
    settings: Settings

    def __post_init__(self) -> None:
        self._keywords = [k.strip() for k in self.settings.filter_keywords if k.strip()]
        if not self._keywords:
            logger.warning(
                "FILTER_KEYWORDS is empty: no messages will match the keyword filter",
            )

    def _sources_normalized(self) -> list[int | str]:
        out: list[int | str] = []
        for x in self.settings.source_chats:
            v = coerce_telethon_chat(x)
            out.append(v.lower() if isinstance(v, str) else v)
        return out

    def _matches_keyword(self, text: str) -> bool:
        if not self._keywords:
            return False
        haystack = text.lower()
        return any(k.lower() in haystack for k in self._keywords)

    async def passes(self, event) -> bool:
        text = event.raw_text or ""
        if not self._matches_keyword(text):
            return False

        chat = await event.get_chat()
        peer_id = utils.get_peer_id(chat)

        for src in self._sources_normalized():
            if isinstance(src, int):
                if peer_id == src or event.chat_id == src:
                    return True
            else:
                username = getattr(chat, "username", None)
                if username and username.lower() == src:
                    return True

        return False
