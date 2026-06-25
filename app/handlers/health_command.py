"""Private /health command: server + OpenRouter provider status."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.handlers.server_status_command import server_status_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.llm_router import LLMRouter

_HEALTH_PATTERN = re.compile(r"^/(?:health|llmhealth)(?:@\S+)?\s*$", re.IGNORECASE)


def health_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return bool(_HEALTH_PATTERN.match(msg.strip()))


async def health_status_text(*, settings: Settings, router: LLMRouter) -> str:
    _ = settings
    return (
        "Health:\n"
        f"{router.provider_status()}\n\n"
        f"{server_status_text()}"
    )


async def handle_health_command(event, *, settings: Settings, router: LLMRouter) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    if not _HEALTH_PATTERN.match((event.message.message or "").strip()):
        return
    await event.reply(await health_status_text(settings=settings, router=router))
