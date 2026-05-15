"""Cloud/OpenRouter commands for allowed private senders."""

from __future__ import annotations

import logging
import re

from app.config import Settings
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

_CLOUD_PATTERN = re.compile(r"^/cloud(?:@\S+)?\s*(.*)$", re.DOTALL)
_ANALYZE_PATTERN = re.compile(r"^/analyze(?:@\S+)?\s*(.*)$", re.DOTALL)
_PROVIDER_PATTERN = re.compile(r"^/provider(?:@\S+)?\s*$", re.DOTALL)


def cloud_command_predicate(event) -> bool:
    return _allowed_command(event, "/cloud")


def analyze_command_predicate(event) -> bool:
    return _allowed_command(event, "/analyze")


def provider_command_predicate(event) -> bool:
    return _allowed_command(event, "/provider")


def _allowed_command(event, prefix: str) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith(prefix)


async def _check_sender(event, settings: Settings) -> bool:
    return bool(settings.ask_sender_ids and event.sender_id in settings.ask_sender_ids)


async def handle_cloud_command(event, *, settings: Settings, router: LLMRouter) -> None:
    if not await _check_sender(event, settings):
        return
    raw = (event.message.message or "").strip()
    m = _CLOUD_PATTERN.match(raw)
    if not m:
        return
    query = (m.group(1) or "").strip()
    if not query:
        await event.reply("Напиши вопрос после /cloud")
        return
    result = await router.ask_cloud(query)
    await event.reply(result.text or result.error)


async def handle_analyze_command(event, *, settings: Settings, router: LLMRouter) -> None:
    if not await _check_sender(event, settings):
        return
    raw = (event.message.message or "").strip()
    m = _ANALYZE_PATTERN.match(raw)
    if not m:
        return
    text = (m.group(1) or "").strip()
    if not text:
        await event.reply("Пришли текст после /analyze")
        return
    system = (
        f"{ASSISTANT_SYSTEM_RU}\n"
        "Дополнительно: ты старший аналитик. Дай структурированный глубокий анализ на русском."
    )
    result = await router.ask_cloud(text, system=system)
    await event.reply(result.text or result.error)


async def handle_provider_command(event, *, settings: Settings, router: LLMRouter) -> None:
    if not await _check_sender(event, settings):
        return
    raw = (event.message.message or "").strip()
    if not _PROVIDER_PATTERN.match(raw):
        return
    await event.reply(router.provider_status())
