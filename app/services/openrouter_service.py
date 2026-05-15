"""OpenRouter provider (OpenAI-compatible chat completions)."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)


class OpenRouterService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.openrouter_api_key and self._settings.openrouter_model)

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        if not self.is_configured:
            logger.warning("OpenRouter is not configured (missing API key or model)")
            return ""

        url = self._settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt.strip()})

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/OlegAA1/telegram_user_assistant",
            "X-Title": "telegram_user_assistant",
        }
        payload = {
            "model": self._settings.openrouter_model,
            "messages": messages,
        }
        timeout = aiohttp.ClientTimeout(total=self._settings.openrouter_timeout)

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
                        return ""
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("OpenRouter HTTP error")
            return ""

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.error("Unexpected OpenRouter response shape: %s", str(data)[:2000])
            return ""
        return content.strip() if isinstance(content, str) else ""
