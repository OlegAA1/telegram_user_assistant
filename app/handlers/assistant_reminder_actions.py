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


_RU_COLLOQUIAL_TIME_RE = re.compile(
    r"(?:(?P<date_before>\bсегодня\b|\bзавтра\b)\s+)?"
    r"(?P<time>(?:\bв\s+)?(?P<hour>\d{1,2})"
    r"(?:\s+час(?:а|ов)?)?\s+(?P<daypart>утра|дня|вечера|ночи)\b)"
    r"(?:\s+(?P<date_after>\bсегодня\b|\bзавтра\b))?",
    re.IGNORECASE,
)

_CANCEL_TEXT_RE = re.compile(r"\b(отмени|отменить|удали|удалить|убери|убрать)\b", re.IGNORECASE)
_EXPLICIT_REMINDER_ID_RE = re.compile(
    r"(?:#\s*|(?:напоминани[ея]|номер)\s+)(\d+)",
    re.IGNORECASE,
)
_IMPLICIT_CANCEL_RE = re.compile(
    r"\b(его|это|её|ее|напоминание|напоминания|последнее|ближайшее|первое)\b",
    re.IGNORECASE,
)


def _normalize_ru_colloquial_time(text: str) -> str:
    """Turn Russian time-of-day phrases into an unambiguous parser input."""
    normalized = text.strip()
    match = _RU_COLLOQUIAL_TIME_RE.search(normalized)
    if not match:
        return normalized

    time_phrase = match.group("time").lower().replace("ё", "е")
    is_explicit_clock_time = (
        re.search(r"\bв\s+\d", time_phrase) is not None or "час" in time_phrase
    )
    if not is_explicit_clock_time:
        return normalized

    hour = int(match.group("hour"))
    if hour > 24:
        return normalized

    daypart = match.group("daypart").lower().replace("ё", "е")
    if daypart in {"дня", "вечера"} and 1 <= hour <= 11:
        hour += 12
    elif daypart in {"утра", "ночи"} and hour == 12:
        hour = 0
    elif hour == 24:
        hour = 0

    date_word = match.group("date_before") or match.group("date_after")
    if date_word:
        return f"{date_word.lower()} в {hour:02d}:00"
    return f"{hour:02d}:00"


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


async def handle_reminder_text_shortcut(
    event,
    *,
    user_text: str,
    settings: Settings,
    reminders: ReminderStore,
) -> bool:
    """Handle terse reminder follow-ups before they can be answered as plain chat."""
    text = user_text.strip()
    if not _CANCEL_TEXT_RE.search(text):
        return False

    lowered = text.lower()
    pending = reminders.list_pending(int(event.sender_id))
    parsed: dict[str, object] = {"intent": "cancel_reminder"}

    id_match = _EXPLICIT_REMINDER_ID_RE.search(text)
    if id_match:
        parsed["reminder_id"] = int(id_match.group(1))
        return await handle_reminder_action_intent(
            event,
            parsed=parsed,
            settings=settings,
            reminders=reminders,
        )

    if "послед" in lowered:
        parsed["selector"] = "последнее"
    elif "ближай" in lowered or "перв" in lowered:
        parsed["selector"] = "ближайшее"
    elif _IMPLICIT_CANCEL_RE.search(text):
        if not pending:
            await event.reply("Нет активных напоминаний, отменять нечего.")
            return True
        if len(pending) == 1:
            parsed["reminder_id"] = pending[0][0]
        else:
            await event.reply(
                "У тебя несколько активных напоминаний. Напиши номер, например "
                "«отмени #3», или попроси: «покажи напоминания»."
            )
            return True
    else:
        return False

    return await handle_reminder_action_intent(
        event,
        parsed=parsed,
        settings=settings,
        reminders=reminders,
    )


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

    raw_dt_text = (parsed.get("datetime_text") or parsed.get("when") or "").strip()
    dt_text = _normalize_ru_colloquial_time(raw_dt_text)
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
