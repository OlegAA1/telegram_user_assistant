"""Route LLM requests between local Ollama and optional OpenRouter."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from app.config import Settings
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU
from app.services.llm_service import LLMService
from app.services.openrouter_service import OpenRouterService

logger = logging.getLogger(__name__)


class Provider(StrEnum):
    LOCAL = "local"
    OPENROUTER = "openrouter"


@dataclass(frozen=True)
class RouterResult:
    text: str
    provider: Provider | None
    fallback_used: bool = False
    error: str = ""


_CURRENT_INFO_RE = re.compile(
    r"\b(latest|current|today|news|now|сегодня|сейчас|новост|актуальн|курс|цена)\b",
    re.IGNORECASE,
)
_DEEP_ANALYSIS_RE = re.compile(
    r"\b(deep analysis|analyze deeply|проанализируй|анализ|стратеги|большой текст)\b",
    re.IGNORECASE,
)
_CODING_RE = re.compile(r"\b(code|python|telethon|docker|compose|скрипт|код)\b", re.IGNORECASE)


class LLMRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        local: LLMService,
        openrouter: OpenRouterService,
    ) -> None:
        self._settings = settings
        self._local = local
        self._openrouter = openrouter

    def choose_provider(self, text: str, *, intent: str | None = None, explicit: str | None = None) -> Provider:
        if explicit == "openrouter":
            return Provider.OPENROUTER
        if explicit == "local":
            return Provider.LOCAL

        normalized_intent = (intent or "").lower()
        if normalized_intent in {"web_search", "cloud_ask", "deep_analysis"}:
            return Provider.OPENROUTER
        if normalized_intent in {
            "create_reminder",
            "todo",
            "routing",
            "local_ask",
            "crypto_price",
        }:
            return Provider.LOCAL

        if _CURRENT_INFO_RE.search(text):
            return Provider.OPENROUTER
        if _DEEP_ANALYSIS_RE.search(text) and not _CODING_RE.search(text):
            return Provider.OPENROUTER
        return Provider.LOCAL

    async def ask_local(self, text: str) -> RouterResult:
        out = await self._local.generate_plain(text)
        if out:
            return RouterResult(text=out, provider=Provider.LOCAL)
        if self._settings.enable_cloud_fallback:
            return await self.ask_cloud(
                text,
                fallback_used=True,
                fallback_reason="Local LLM returned an empty response",
            )
        return RouterResult(
            text="",
            provider=Provider.LOCAL,
            error="Локальная LLM не ответила. Cloud fallback выключен.",
        )

    async def ask_cloud(
        self,
        text: str,
        *,
        fallback_used: bool = False,
        fallback_reason: str = "",
        system: str | None = None,
    ) -> RouterResult:
        effective_system = system if system is not None else ASSISTANT_SYSTEM_RU
        out = await self._openrouter.generate(text, system=effective_system)
        if out:
            if fallback_reason:
                logger.info("OpenRouter fallback used: %s", fallback_reason)
            return RouterResult(text=out, provider=Provider.OPENROUTER, fallback_used=fallback_used)
        return RouterResult(
            text="",
            provider=Provider.OPENROUTER,
            fallback_used=fallback_used,
            error="OpenRouter недоступен или не настроен. Проверь OPENROUTER_API_KEY/OPENROUTER_MODEL.",
        )

    async def ask(self, text: str, *, intent: str | None = None, explicit: str | None = None) -> RouterResult:
        provider = self.choose_provider(text, intent=intent, explicit=explicit)
        if provider == Provider.OPENROUTER:
            return await self.ask_cloud(text)
        return await self.ask_local(text)

    def provider_status(self) -> str:
        cloud_state = "configured" if self._openrouter.is_configured else "not configured"
        web_state = "enabled" if self._settings.enable_web_search else "disabled"
        crypto_state = "enabled" if self._settings.enable_crypto_price else "disabled"
        fallback = "enabled" if self._settings.enable_cloud_fallback else "disabled"
        return (
            "Провайдеры:\n"
            f"- local: Ollama `{self._settings.llm_model}` → `{self._settings.llm_api_url}`\n"
            f"- openrouter: {cloud_state}, модель `{self._settings.openrouter_model or '<unset>'}`\n"
            f"- cloud fallback: {fallback}\n"
            f"- web search: {web_state}, provider `{self._settings.web_search_provider or 'none'}`\n"
            f"- crypto price: {crypto_state}, Binance USDT, default `{self._settings.default_crypto_vs_currency}`"
        )
