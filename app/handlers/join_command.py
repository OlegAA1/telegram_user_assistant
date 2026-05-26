"""Private /join command: subscribe account to up to 3 channels."""

from __future__ import annotations

import logging
import re

from app.config import Settings
from app.services.channel_join_service import (
    MAX_JOIN_PER_COMMAND,
    join_targets,
    parse_join_targets,
)

logger = logging.getLogger(__name__)

_JOIN_PATTERN = re.compile(r"^/join(?:@\S+)?\s*(.*)$", re.DOTALL)


def join_command_predicate(event) -> bool:
    if not event.message or not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = event.message.message or ""
    return msg.lstrip().startswith("/join")


async def handle_join_command(event, *, settings: Settings) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return

    raw = (event.message.message or "").strip()
    m = _JOIN_PATTERN.match(raw)
    if not m:
        return

    tail = (m.group(1) or "").strip()
    await reply_join_targets(event, tail=tail)


async def reply_join_targets(event, *, tail: str) -> None:
    if not tail:
        await event.reply(
            "Напиши до 3 каналов после /join, например:\n"
            "/join @channel1 @channel2\n"
            "/join https://t.me/some_channel\n"
            "/join https://t.me/+invitehash",
        )
        return

    targets = parse_join_targets(tail, max_targets=MAX_JOIN_PER_COMMAND)
    if not targets:
        await event.reply(
            "Не нашёл каналы в сообщении. Укажи @username, t.me/... или id (-100...). "
            f"За раз — не больше {MAX_JOIN_PER_COMMAND}.",
        )
        return

    extra = ""
    all_tokens = len(parse_join_targets(tail, max_targets=99))
    if all_tokens > MAX_JOIN_PER_COMMAND:
        extra = f"\n\nОбработано только первые {MAX_JOIN_PER_COMMAND} из {all_tokens}."

    logger.info(
        "/join from sender_id=%s targets=%s",
        event.sender_id,
        [t.display for t in targets],
    )

    outcomes = await join_targets(event.client, targets)

    lines = [f"Результат /join ({len(outcomes)}):"]
    for i, o in enumerate(outcomes, start=1):
        lines.append(f"{i}. {o.display} — {o.message}")

    await event.reply("\n".join(lines) + extra)
