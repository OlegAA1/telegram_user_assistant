"""List available Telegram dialogs for allowed private senders."""

from __future__ import annotations

import re

from telethon.tl.types import Channel, Chat, User

from app.config import Settings

_DIALOGS_PATTERN = re.compile(r"^/dialogs(?:@\S+)?(?:\s+(channels|groups|users))?\s*$", re.IGNORECASE)
_CHUNK_LIMIT = 3500


def dialogs_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith("/dialogs")


def _dialog_type(entity) -> str:
    if isinstance(entity, User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        if getattr(entity, "megagroup", False):
            return "supergroup"
        return "channel"
    return type(entity).__name__.lower()


def _matches_filter(dialog_type: str, filter_name: str | None) -> bool:
    if filter_name is None:
        return True
    if filter_name == "channels":
        return dialog_type == "channel"
    if filter_name == "groups":
        return dialog_type in {"group", "supergroup"}
    if filter_name == "users":
        return dialog_type in {"user", "bot"}
    return False


def _format_dialog(*, name: str, dialog_type: str, dialog_id: int, username: str | None) -> str:
    username_line = f"Username: @{username}" if username else "Username: -"
    return (
        f"Название: {name}\n"
        f"Тип: {dialog_type}\n"
        f"ID: {dialog_id}\n"
        f"{username_line}"
    )


def _chunks(items: list[str], limit: int = _CHUNK_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for item in items:
        block = item if not current else "\n\n" + item
        if current and len(current) + len(block) > limit:
            chunks.append(current)
            current = item
        else:
            current += block
    if current:
        chunks.append(current)
    return chunks


async def handle_dialogs_command(event, *, settings: Settings) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return

    raw = (event.message.message or "").strip()
    m = _DIALOGS_PATTERN.match(raw)
    if not m:
        await event.reply("Формат: /dialogs, /dialogs channels, /dialogs groups или /dialogs users")
        return

    filter_name = m.group(1).lower() if m.group(1) else None
    entries: list[str] = []

    async for dialog in event.client.iter_dialogs():
        entity = dialog.entity
        dialog_type = _dialog_type(entity)
        if not _matches_filter(dialog_type, filter_name):
            continue

        username = getattr(entity, "username", None)
        entries.append(
            _format_dialog(
                name=dialog.name or "(без названия)",
                dialog_type=dialog_type,
                dialog_id=int(dialog.id),
                username=username,
            ),
        )

    title = "Доступные диалоги" if filter_name is None else f"Доступные диалоги: {filter_name}"
    if not entries:
        await event.reply(f"{title}\n\nНичего не найдено.")
        return

    for idx, chunk in enumerate(_chunks(entries), start=1):
        suffix = "" if len(entries) == 1 else f"\n\nЧасть {idx}"
        await event.reply(f"{title}{suffix}\n\n{chunk}")
