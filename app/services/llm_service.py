"""Local LLM via Ollama HTTP API (non-streaming)."""

from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from app.config import Settings

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

    async def analyze(self, text: str) -> str:
        prompt = self._load_prompt()
        payload = {
            "model": self._settings.llm_model,
            "prompt": f"{prompt}\n\n---\n\n{text}",
            "stream": False,
        }
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
        except aiohttp.ClientError:
            logger.exception("LLM HTTP error")
            return ""

        # Ollama returns {"response": "..."} for stream:false
        if isinstance(data, dict):
            out = data.get("response")
            if isinstance(out, str):
                return out.strip()
        logger.error("Unexpected LLM JSON shape: %s", str(data)[:2000])
        return ""
