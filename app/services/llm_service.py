"""Local LLM via Ollama HTTP API (non-streaming)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp

from app.config import Settings
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._prompt_template: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is not None:
            return self._prompt_template
        path: Path = self._settings.prompt_path
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        self._prompt_template = path.read_text(encoding="utf-8")
        return self._prompt_template

    async def _generate(self, prompt: str) -> str:
        payload = {
            "model": self._settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "think": self._settings.llm_think,
        }
        if self._settings.llm_num_ctx > 0:
            payload["options"] = {"num_ctx": self._settings.llm_num_ctx}
        timeout = aiohttp.ClientTimeout(total=600)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self._settings.llm_api_url,
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        err_body = await resp.text()
                        logger.error(
                            "LLM request failed: status=%s body=%s",
                            resp.status,
                            err_body[:2000],
                        )
                        return ""
                    try:
                        data = await resp.json(content_type=None)
                    except aiohttp.ContentTypeError:
                        raw = await resp.text()
                        logger.error("LLM response is not JSON: %s", raw[:2000])
                        return ""
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("LLM HTTP error")
            return ""

        if isinstance(data, dict):
            out = data.get("response")
            if isinstance(out, str):
                return out.strip()
        logger.error("Unexpected LLM JSON shape: %s", str(data)[:2000])
        return ""

    async def analyze(self, text: str) -> str:
        prompt = f"{self._load_prompt()}\n\n---\n\n{text}"
        return await self._generate(prompt)

    async def generate_prompt(self, prompt: str) -> str:
        """Send a fully assembled prompt to the local model."""
        return await self._generate(prompt)

    async def generate_plain(self, user_text: str) -> str:
        """Send text to Ollama as the full prompt (e.g. owner /ask in DM)."""
        prompt = (
            f"{ASSISTANT_SYSTEM_RU}\n\n"
            f"Вопрос пользователя:\n{user_text.strip()}\n\n"
            "Ответ:"
        )
        return await self._generate(prompt)

    async def intent_detection(self, user_text: str) -> str:
        """LLM returns JSON intent only (see prompts/intent_parser.txt)."""
        path: Path = self._settings.intent_parser_path
        if not path.is_file():
            logger.error("Intent parser prompt missing: %s", path)
            return ""
        guide = path.read_text(encoding="utf-8")
        prompt = (
            f"{guide}\n\n---\n\nСообщение пользователя:\n{user_text.strip()}\n\n"
            "Ответь ТОЛЬКО одним JSON-объектом, без другого текста."
        )
        return await self._generate(prompt)
