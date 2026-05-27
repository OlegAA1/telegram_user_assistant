"""Reminder actions for conversational assistant intents."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser

from app.config import Settings
from app.services.reminder_store import ReminderStore

logger = logging.getLogger(__name__)


def _human_reminder_time(fire_utc: datetime, tz: ZoneInfo) -> str:
    local = fire_utc.astimezone(tz)
    local_str = local.strftime("%Y-%m-%d %H:%M")
    today = datetime.now(tz).date()
    fire_date = local.date()
    hm = local.strftime("%H:%M")
    if fire_date == today:
        return f"сегодня в {hm}"
    if fire_date == today + timedelta(days=1):
        return f"завтра в {hm}"
    return local_str


def _format_pending_reminders(
    pending: list[tuple[int, str, datetime]],
    *,
    tz: ZoneInfo,
) -> str:
    if not pending:
        return "Нет активных напоминаний."
    lines = ["Активные напоминания:"]
    for rid, body, fire_utc in pending:
        short = body.replace("\n", " ")[:120]
        suffix = "..." if len(body) > 120 else ""
        lines.append(f"#{rid} — {_human_reminder_time(fire_utc, tz)} — {short}{suffix}")
    return "\n".join(lines)


def _parse_int_field(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lstrip("#")
    if re.fullmatch(r"\d+", s):
        return int(s)
    return None


def _resolve_reminder_to_cancel(
    parsed: dict,
    pending: list[tuple[int, str, datetime]],
) -> tuple[int, str] | None:
    reminder_id = _parse_int_field(parsed.get("reminder_id") or parsed.get("id"))
    if reminder_id is not None:
        for rid, body, _when in pending:
            if rid == reminder_id:
                return rid, body
        return reminder_id, ""

    ordinal = _parse_int_field(parsed.get("ordinal"))
    selector = str(parsed.get("selector") or "").strip().lower()
    if ordinal is None:
        if selector in {"первое", "первый", "ближайшее", "ближайший", "first", "next"}:
            ordinal = 1
        elif selector in {"последнее", "последний", "last"}:
            ordinal = len(pending)
    if ordinal is None or ordinal < 1 or ordinal > len(pending):
        return None
    rid, body, _when = pending[ordinal - 1]
    return rid, body


async def handle_reminder_action_intent(
    event,
    *,
    parsed: dict,
    settings: Settings,
    reminders: ReminderStore,
) -> bool:
    intent = str(parsed.get("intent", "unknown")).strip().lower()
    if intent not in {"create_reminder", "list_reminders", "cancel_reminder"}:
        return False

    uid = int(event.sender_id)
    chat_id = int(event.chat_id)
    tz = ZoneInfo(settings.reminder_tz)

    if intent == "list_reminders":
        await event.reply(_format_pending_reminders(reminders.list_pending(uid), tz=tz))
        return True

    if intent == "cancel_reminder":
        pending = reminders.list_pending(uid)
        if not pending:
            await event.reply("Нет активных напоминаний, отменять нечего.")
            return True
        target = _resolve_reminder_to_cancel(parsed, pending)
        if target is None:
            await event.reply(
                "Какое напоминание отменить? Напиши номер из списка, например "
                "«отмени #12», или попроси: «покажи напоминания»."
            )
            return True
        rid, body = target
        if reminders.cancel(uid, rid):
            short = body.replace("\n", " ")[:120] if body else ""
            suffix = f": {short}{'...' if len(body) > 120 else ''}" if short else ""
            await event.reply(f"Ок, отменил напоминание #{rid}{suffix}")
        else:
            await event.reply(f"Не нашёл активное напоминание #{rid}.")
        return True

    dt_text = (parsed.get("datetime_text") or parsed.get("when") or "").strip()
    body = (parsed.get("reminder_body") or parsed.get("body") or "").strip()
    if not dt_text or not body:
        logger.warning("create_reminder missing fields: %s", parsed)
        return False

    dp_settings = {
        "TIMEZONE": settings.reminder_tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": datetime.now(tz),
    }
    when = dateparser.parse(dt_text, languages=["ru", "en"], settings=dp_settings)
    if when is None:
        await event.reply(
            f"Не удалось разобрать время «{dt_text}». "
            "Попробуй явнее, например: «сегодня в 23:30»."
        )
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    fire_utc = when.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if fire_utc <= now_utc:
        await event.reply("Получилось время в прошлом. Уточни дату или время.")
        return True

    rid = reminders.add(uid, chat_id, body, fire_utc)
    local_str = fire_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    logger.info("assistant create_reminder id=%s user=%s at=%s", rid, uid, local_str)
    await event.reply(f"Ок, напомню {_human_reminder_time(fire_utc, tz)}: {body}")
    return True
