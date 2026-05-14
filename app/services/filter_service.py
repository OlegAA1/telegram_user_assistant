"""Filter messages by source chats and keywords."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telethon import utils

from app.config import Settings, coerce_telethon_chat

logger = logging.getLogger(__name__)


def _normalize_token(raw: str) -> int | str:
    v = coerce_telethon_chat(raw)
    return v.lower() if isinstance(v, str) else v


@dataclass
class FilterService:
    settings: Settings

    def __post_init__(self) -> None:
        self._global_keywords = [k.strip() for k in self.settings.filter_keywords if k.strip()]
        self._rule_entries: list[tuple[int | str, list[str]]] = []
        for rule in self.settings.source_keyword_rules:
            token = _normalize_token(rule.source)
            kws = [k.strip() for k in rule.keywords if k.strip()]
            self._rule_entries.append((token, kws))

        if not self.settings.source_keyword_rules and not self._global_keywords:
            logger.warning(
                "FILTER_KEYWORDS is empty and SOURCE_KEYWORD_RULES is unset: "
                "no messages will match the keyword filter",
            )
        if self.settings.explicit_source_chats and not self._global_keywords and self.settings.source_keyword_rules:
            logger.warning(
                "SOURCE_CHATS has entries but FILTER_KEYWORDS is empty: "
                "chats listed only in SOURCE_CHATS (without a SOURCE_KEYWORD_RULES rule) "
                "will never match",
            )

    @staticmethod
    def _peer_matches_token(
        token: int | str,
        chat,
        peer_id: int,
        event_chat_id: int,
    ) -> bool:
        if isinstance(token, int):
            return peer_id == token or event_chat_id == token
        username = getattr(chat, "username", None)
        return bool(username and username.lower() == token)

    def _peer_matches_any_explicit(self, chat, peer_id: int, event_chat_id: int) -> bool:
        for raw in self.settings.explicit_source_chats:
            token = _normalize_token(raw)
            if self._peer_matches_token(token, chat, peer_id, event_chat_id):
                return True
        return False

    @staticmethod
    def _text_matches_any(text: str, keywords: list[str]) -> bool:
        if not keywords:
            return False
        haystack = text.lower()
        return any(k.lower() in haystack for k in keywords)

    async def passes(self, event) -> bool:
        text = event.raw_text or ""
        chat = await event.get_chat()
        peer_id = utils.get_peer_id(chat)
        event_chat_id = int(event.chat_id)

        for token, kws in self._rule_entries:
            if self._peer_matches_token(token, chat, peer_id, event_chat_id):
                return self._text_matches_any(text, kws)

        if self._peer_matches_any_explicit(chat, peer_id, event_chat_id):
            return self._text_matches_any(text, self._global_keywords)

        return False
