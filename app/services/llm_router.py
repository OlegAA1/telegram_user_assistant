"""OpenRouter-backed LLM request helper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.config import Settings
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU
from app.services.openrouter_service import OpenRouterService

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    OPENROUTER = "openrouter"


@dataclass(frozen=True)
class RouterResult:
    text: str
    provider: Provider | None
    fallback_used: bool = False
    error: str = ""


class LLMRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        openrouter: OpenRouterService,
    ) -> None:
        self._settings = settings
        self._openrouter = openrouter
        self._prompt_template: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is not None:
            return self._prompt_template
        path: Path = self._settings.prompt_path
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        self._prompt_template = path.read_text(encoding="utf-8")
        return self._prompt_template

    def choose_provider(self, text: str, *, intent: str | None = None, explicit: str | None = None) -> Provider:
        _ = (text, intent, explicit)
        return Provider.OPENROUTER

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
        self.choose_provider(text, intent=intent, explicit=explicit)
        return await self.ask_cloud(text)

    async def analyze(self, text: str) -> str:
        prompt = f"{self._load_prompt()}\n\n---\n\n{text}"
        return await self._openrouter.generate(prompt)

    async def generate_prompt(self, prompt: str) -> str:
        return await self._openrouter.generate(prompt)

    async def intent_detection(self, user_text: str) -> str:
        path: Path = self._settings.intent_parser_path
        if not path.is_file():
            logger.error("Intent parser prompt missing: %s", path)
            return ""
        guide = path.read_text(encoding="utf-8")
        prompt = (
            f"{guide}\n\n---\n\nСообщение пользователя:\n{user_text.strip()}\n\n"
            "Ответь ТОЛЬКО одним JSON-объектом, без другого текста."
        )
        return await self._openrouter.generate(prompt)

    def provider_status(self) -> str:
        cloud_state = "configured" if self._openrouter.is_configured else "not configured"
        web_state = "enabled" if self._settings.enable_web_search else "disabled"
        crypto_state = "enabled" if self._settings.enable_crypto_price else "disabled"
        return (
            "Провайдеры:\n"
            f"- openrouter: {cloud_state}, модель `{self._settings.openrouter_model or '<unset>'}`, "
            f"{self._openrouter.usage_status()}\n"
            f"- web search: {web_state}, provider `{self._settings.web_search_provider or 'none'}`\n"
            f"- crypto price: {crypto_state}, Binance USDT, default `{self._settings.default_crypto_vs_currency}`"
        )
