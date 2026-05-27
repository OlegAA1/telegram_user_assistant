"""Private /remind: schedule messages at a time (same allowed senders as /ask)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings
from app.services.reminder_store import ReminderStore

logger = logging.getLogger(__name__)

_RELATIVE = re.compile(
    r"^/remind\s+in\s+(\d+)\s*(m|min|h|hour|hours|d|day|days)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_ABSOLUTE = re.compile(
    r"^/remind\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$",
    re.DOTALL,
)

USAGE = (
    "Формат напоминания:\n"
    "• /remind ГГГГ-ММ-ДД ЧЧ:ММ текст — время в часовом поясе REMINDER_TZ из .env (часы с ведущим нулём, напр. 09:05)\n"
    "• /remind in 30m текст или in 2h, in 1d\n"
    "• /remind list — список ожидающих\n"
    "• /remind history или /remind list all — история активных/отменённых/сработавших\n"
    "• /remind cancel ID — отменить по номеру из list\n\n"
    "Свободную фразу «напомни завтра в 10» можно сначала обсудить через /ask, "
    "а затем оформить командой /remind с конкретной датой/временем."
)


def remind_command_predicate(event) -> bool:
    if not event.message:
        return False
    if not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    msg = (event.message.message or "").lstrip()
    return msg.startswith("/remind")


def _parse_absolute(rest: str, tz: ZoneInfo) -> datetime | None:
    m = _ABSOLUTE.match(rest)
    if not m:
        return None
    date_s, time_s, _text = m.group(1), m.group(2), m.group(3)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            local = datetime.strptime(f"{date_s} {time_s}", fmt).replace(tzinfo=tz)
            return local.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _parse_relative(rest: str, tz: ZoneInfo) -> datetime | None:
    m = _RELATIVE.match(rest)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit in ("m", "min"):
        delta = timedelta(minutes=n)
    elif unit in ("h", "hour", "hours"):
        delta = timedelta(hours=n)
    elif unit in ("d", "day", "days"):
        delta = timedelta(days=n)
    else:
        return None
    now = datetime.now(tz)
    return (now + delta).astimezone(timezone.utc)


def _format_history(rows, *, tz: ZoneInfo, timezone_name: str) -> str:
    if not rows:
        return "История напоминаний пуста."
    labels = {
        "active": "активно",
        "cancelled": "отменено",
        "fired": "сработало",
    }
    lines = ["История напоминаний:"]
    for row in rows:
        local = row.fire_at.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        short = row.body.replace("\n", " ")[:80]
        suffix = "..." if len(row.body) > 80 else ""
        status = labels.get(row.status, row.status)
        lines.append(f"#{row.id} — {status} — {local} ({timezone_name}) — {short}{suffix}")
    return "\n".join(lines)


async def handle_remind_command(
    event,
    *,
    settings: Settings,
    reminders: ReminderStore,
) -> None:
    allowed = settings.ask_sender_ids
    if not allowed:
        return
    if not event.message or not event.is_private or event.sender_id not in allowed:
        return
    if getattr(event.message, "out", False):
        return

    raw = (event.message.message or "").strip()
    uid = int(event.sender_id)
    chat_id = int(event.chat_id)

    try:
        tz = ZoneInfo(settings.reminder_tz)
    except ZoneInfoNotFoundError:
        await event.reply(f"Неверная зона REMINDER_TZ={settings.reminder_tz!r}")
        return

    if re.match(r"^/remind\s+(?:history|all|list\s+all)\b", raw, re.IGNORECASE):
        logger.info("reminder history user=%s chat=%s", uid, chat_id)
        await event.reply(
            _format_history(
                reminders.list_history(uid),
                tz=tz,
                timezone_name=settings.reminder_tz,
            ),
        )
        return

    if re.match(r"^/remind\s+list\b", raw, re.IGNORECASE):
        pending = reminders.list_pending(uid)
        logger.info("reminder list user=%s chat=%s count=%s", uid, chat_id, len(pending))
        if not pending:
            await event.reply("Нет активных напоминаний.")
            return
        lines = ["Ожидающие напоминания:"]
        for rid, body, when in pending:
            local = when.astimezone(tz).strftime("%Y-%m-%d %H:%M")
            short = body.replace("\n", " ")[:80]
            lines.append(f"#{rid} — {local} ({settings.reminder_tz}) — {short}")
        await event.reply("\n".join(lines))
        return

    m_cancel = re.match(r"^/remind\s+cancel\s+(\d+)\s*$", raw, re.IGNORECASE)
    if m_cancel:
        rid = int(m_cancel.group(1))
        if reminders.cancel(uid, rid):
            logger.info("reminder cancel id=%s user=%s chat=%s", rid, uid, chat_id)
            await event.reply(f"Напоминание #{rid} отменено.")
        else:
            await event.reply(f"Не найдено напоминание #{rid} или оно уже сработало.")
        return

    body_match = _ABSOLUTE.match(raw) or _RELATIVE.match(raw)
    if not body_match:
        await event.reply(USAGE)
        return

    text = body_match.group(3).strip()
    if not text:
        await event.reply("Добавь текст напоминания после времени.\n\n" + USAGE)
        return

    fire_utc = _parse_absolute(raw, tz) or _parse_relative(raw, tz)
    if fire_utc is None:
        await event.reply("Не удалось разобрать время.\n\n" + USAGE)
        return

    now_utc = datetime.now(timezone.utc)
    if fire_utc <= now_utc:
        await event.reply("Время напоминания уже в прошлом. Укажи будущее время.")
        return

    rid = reminders.add(uid, chat_id, text, fire_utc)
    local_str = fire_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    logger.info(
        "reminder create id=%s user=%s chat=%s at_utc=%s text_len=%s",
        rid,
        uid,
        chat_id,
        fire_utc.isoformat(),
        len(text),
    )
    await event.reply(
        f"Ок, напоминание #{rid} на {local_str} ({settings.reminder_tz}).\n"
        f"Текст: {text[:500]}{'…' if len(text) > 500 else ''}",
    )
