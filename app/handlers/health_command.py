"""Private /health command: server + provider + Ollama reachability."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from app.handlers.server_status_command import server_status_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

_HEALTH_PATTERN = re.compile(r"^/(?:health|llmhealth)(?:@\S+)?\s*$", re.IGNORECASE)


def health_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return bool(_HEALTH_PATTERN.match(msg.strip()))


def ollama_tags_url(llm_api_url: str) -> str:
    parsed = urlsplit(llm_api_url)
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, "/api/tags", "", ""))
    return "http://localhost:11434/api/tags"


def _model_names(data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


async def ollama_health_line(settings: Settings) -> str:
    tags_url = ollama_tags_url(settings.llm_api_url)
    timeout_seconds = max(1.0, min(float(settings.llm_intent_timeout), 10.0))
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(tags_url) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Ollama health failed: status=%s body=%s", resp.status, body[:500])
                    return f"- Ollama: HTTP {resp.status} на `{tags_url}`"
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("Ollama health request failed: %s", exc)
        return f"- Ollama: недоступна на `{tags_url}` ({type(exc).__name__})"

    names = _model_names(data)
    configured = settings.llm_model
    has_model = configured in names
    model_state = "найдена" if has_model else "не найдена в /api/tags"
    count = len(names)
    return f"- Ollama: ok `{tags_url}`, моделей: {count}, `{configured}` — {model_state}"


async def health_status_text(*, settings: Settings, router: LLMRouter) -> str:
    ollama_line = await ollama_health_line(settings)
    return (
        "Health:\n"
        f"{ollama_line}\n"
        f"- LLM timeouts: intent={settings.llm_intent_timeout}s, "
        f"chat={settings.llm_timeout}s, analyze={settings.llm_analyze_timeout}s\n\n"
        f"{router.provider_status()}\n\n"
        f"{server_status_text()}"
    )


async def handle_health_command(event, *, settings: Settings, router: LLMRouter) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    if not _HEALTH_PATTERN.match((event.message.message or "").strip()):
        return
    await event.reply(await health_status_text(settings=settings, router=router))
