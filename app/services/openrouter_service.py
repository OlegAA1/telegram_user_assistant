"""OpenRouter provider (OpenAI-compatible chat completions)."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from app.config import Settings
from app.services.cloud_usage_store import CloudUsageStore

logger = logging.getLogger(__name__)


class OpenRouterService:
    def __init__(self, settings: Settings, usage_store: CloudUsageStore | None = None) -> None:
        self._settings = settings
        self._usage_store = usage_store
        self.last_error = ""

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.openrouter_api_key and self._settings.openrouter_model)

    def _fail(self, message: str, *, log_level: int = logging.WARNING) -> str:
        self.last_error = message
        logger.log(log_level, "OpenRouter unavailable: %s", message)
        return ""

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        max_input_chars: int | None = None,
    ) -> str:
        self.last_error = ""
        prompt = prompt.strip()
        if not self._settings.openrouter_api_key:
            return self._fail("OPENROUTER_API_KEY is empty")
        effective_model = model or self._settings.openrouter_model
        if not effective_model:
            return self._fail("OPENROUTER_MODEL is empty")
        if self._usage_store is not None and not self._usage_store.can_use(
            self._settings.max_cloud_requests_per_day,
        ):
            return self._fail(
                "Дневной лимит cloud-запросов исчерпан. "
                "Попробуй локальную модель или увеличь MAX_CLOUD_REQUESTS_PER_DAY.",
            )
        effective_max_input_chars = max_input_chars or self._settings.max_cloud_input_chars
        if len(prompt) > effective_max_input_chars:
            return self._fail(
                "Запрос слишком длинный для cloud-модели. "
                "Сократи текст или увеличь MAX_CLOUD_INPUT_CHARS.",
            )

        url = self._settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/OlegAA1/telegram_user_assistant",
            "X-Title": "telegram_user_assistant",
        }
        payload = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens or self._settings.max_cloud_output_tokens,
        }
        timeout = aiohttp.ClientTimeout(total=self._settings.openrouter_timeout)

        if self._settings.log_cloud_usage:
            logger.info(
                "OpenRouter request: model=%s input_chars=%s max_tokens=%s timeout=%s",
                effective_model,
                len(prompt),
                payload["max_tokens"],
                self._settings.openrouter_timeout,
            )

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "OpenRouter request failed: status=%s body=%s",
                            resp.status,
                            body[:2000],
                        )
                        self.last_error = f"OpenRouter request failed with HTTP {resp.status}"
                        return ""
                    data = await resp.json(content_type=None)
        except asyncio.TimeoutError:
            self.last_error = "OpenRouter request timed out"
            logger.exception(
                "OpenRouter timeout: model=%s timeout=%s input_chars=%s",
                effective_model,
                self._settings.openrouter_timeout,
                len(prompt),
            )
            return ""
        except aiohttp.ClientError:
            self.last_error = "OpenRouter HTTP error"
            logger.exception(
                "OpenRouter HTTP error: model=%s input_chars=%s",
                effective_model,
                len(prompt),
            )
            return ""

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.error("Unexpected OpenRouter response shape: %s", str(data)[:2000])
            self.last_error = "OpenRouter returned an unexpected response"
            return ""
        if not isinstance(content, str) or not content.strip():
            self.last_error = "OpenRouter returned an empty response"
            logger.warning("OpenRouter returned empty response: model=%s", effective_model)
            return ""
        if self._usage_store is not None:
            self._usage_store.record_request()
        return content.strip()
