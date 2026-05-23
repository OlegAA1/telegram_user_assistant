"""Archive structured script run messages."""

from __future__ import annotations

from telethon import utils

from app.config import Settings
from app.services.script_run_parser import parse_script_run
from app.services.script_run_store import ScriptRunStore


def _entity_title(entity) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    username = getattr(entity, "username", None)
    return f"@{username}" if username else str(getattr(entity, "id", "unknown"))


async def archive_script_run_message(event, *, settings: Settings, store: ScriptRunStore) -> None:
    message = event.message
    if not message:
        return

    run = parse_script_run(event.raw_text or "", timezone_name=settings.script_digest_tz)
    if run is None:
        return

    chat = await event.get_chat()
    store.save_run(
        chat_id=int(utils.get_peer_id(chat)),
        chat_title=_entity_title(chat),
        message_id=int(message.id),
        message_date=message.date,
        run=run,
    )
