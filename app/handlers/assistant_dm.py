"""Natural-language private messages for allowed senders (intent → remind or LLM)."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser

from app.config import Settings
from app.prompts.assistant_system import (
    ASSISTANT_SYSTEM_RU,
    HELP_REPLY,
    SEARCH_SUMMARY_SYSTEM_RU,
)
from app.services.crypto_price_parser import looks_like_crypto_price_query, try_parse_crypto_price
from app.services.crypto_price_service import (
    CryptoPriceError,
    CryptoPriceService,
    format_crypto_price_reply,
)
from app.services.llm_service import LLMService
from app.services.llm_router import LLMRouter
from app.services.reminder_store import ReminderStore
from app.services.reply_context import build_reply_followup_prompt
from app.handlers.scam_check_access import MSG_DM_REDIRECT, is_scam_check_trigger
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)

UNKNOWN_REPLY = (
    "Не понял команду. Напиши ? для списка команд или, например: "
    "напомни в 23:30 открыть сайт, /price btc, /search запрос, "
    "перешли пост в scam-группу и /check."
)

_REMINDER_ACTION_KEYWORDS = (
    "напомни",
    "напомнить",
    "напоминание",
    "напоминания",
    "напоминаний",
    "будильник",
    "отмени",
    "отменить",
    "удали",
    "удалить",
)


def looks_like_reminder_action_text(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in _REMINDER_ACTION_KEYWORDS)


def _format_search_result(index: int, item: dict[str, str]) -> str:
    title = item.get("title", "Без названия")
    url = item.get("url", "")
    snippet = item.get("snippet", "")
    published_date = item.get("published_date", "")
    score = item.get("score", "")
    meta = []
    if published_date:
        meta.append(f"published_date={published_date}")
    if score:
        meta.append(f"score={score}")
    meta_line = f"\nМетаданные: {', '.join(meta)}" if meta else ""
    return f"{index}. {title}\n{url}{meta_line}\n{snippet}"


def assistant_natural_predicate(event) -> bool:
    if not event.message:
        return False
    if not event.is_private:
        return False
    if getattr(event.message, "out", False):
        return False
    raw = (event.message.message or "").strip()
    if not raw:
        return False
    if raw.startswith("/"):
        return False
    if is_scam_check_trigger(raw):
        return False
    return True


def _extract_json_object(raw: str) -> dict | None:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        idx = s.index("{")
    except ValueError:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[idx:])
    except json.JSONDecodeError as exc:
        logger.warning("Intent JSON parse failed: %s", exc)
        return None
    return obj if isinstance(obj, dict) else None


async def _reply_crypto_price(
    event,
    *,
    crypto: CryptoPriceService,
    asset: str,
    vs_currency: str,
) -> None:
    try:
        data = await crypto.get_price(asset, vs_currency)
        await event.reply(format_crypto_price_reply(data))
    except CryptoPriceError as exc:
        await event.reply(exc.message)
    except Exception:
        logger.exception("crypto_price failed")
        await event.reply(
            "Не смог получить цену через Binance. "
            "Возможно, такой пары нет или Binance временно недоступен.",
        )


async def classify_assistant_intent(llm: LLMService, user_text: str) -> dict | None:
    try:
        raw_llm = await llm.intent_detection(user_text)
    except Exception:
        logger.exception("intent_detection failed")
        return None
    return _extract_json_object(raw_llm) if raw_llm else None


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


async def handle_assistant_natural(
    event,
    *,
    settings: Settings,
    llm: LLMService,
    router: LLMRouter,
    reminders: ReminderStore,
    search: WebSearchService,
    crypto: CryptoPriceService,
) -> None:
    if not settings.ask_sender_ids:
        return
    if not event.message or not event.is_private or event.sender_id not in settings.ask_sender_ids:
        return
    if getattr(event.message, "out", False):
        return

    user_text = (event.message.message or "").strip()
    if not user_text or user_text.startswith("/"):
        return
    if user_text == "?":
        await event.reply(HELP_REPLY)
        return

    if is_scam_check_trigger(user_text):
        await event.reply(MSG_DM_REDIRECT)
        return

    # Deterministic crypto price (before LLM intent parser)
    if looks_like_crypto_price_query(user_text):
        parsed_crypto = try_parse_crypto_price(
            user_text,
            default_vs=settings.default_crypto_vs_currency,
        )
        if parsed_crypto:
            await _reply_crypto_price(
                event,
                crypto=crypto,
                asset=parsed_crypto.asset,
                vs_currency=parsed_crypto.vs_currency,
            )
            return
        await event.reply("Не понял монету. Примеры: btc, eth, sol, ton, bnb")
        return

    followup_prompt = await build_reply_followup_prompt(event, user_text)
    if followup_prompt:
        result = await router.ask_cloud(followup_prompt, system=ASSISTANT_SYSTEM_RU)
        await event.reply(result.text or result.error)
        return

    parsed = await classify_assistant_intent(llm, user_text)

    if not isinstance(parsed, dict):
        logger.info("Intent fallback to ask_llm (invalid JSON)")
        result = await router.ask_local(user_text)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return

    intent = str(parsed.get("intent", "unknown")).strip().lower()

    if await handle_reminder_action_intent(
        event,
        parsed=parsed,
        settings=settings,
        reminders=reminders,
    ):
        return

    if intent == "crypto_price":
        asset = (parsed.get("asset") or parsed.get("symbol") or "").strip()
        vs = (parsed.get("vs_currency") or settings.default_crypto_vs_currency).strip().lower()
        if not asset:
            await event.reply("Не понял монету. Примеры: btc, eth, sol, ton, bnb")
            return
        await _reply_crypto_price(event, crypto=crypto, asset=asset, vs_currency=vs)
        return

    if intent in {"ask_llm", "local_ask"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_local(q)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return

    if intent in {"cloud_ask", "deep_analysis"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_cloud(q)
        await event.reply(result.text or result.error)
        return

    if intent == "web_search":
        q = (parsed.get("query") or parsed.get("text") or user_text).strip()
        results = await search.search(q)
        if not results:
            if not settings.enable_web_search:
                await event.reply("Для актуальной информации включи ENABLE_WEB_SEARCH или используй /cloud.")
                return
            result = await router.ask_cloud(
                f"Пользователь запросил актуальную информацию: {q}\n"
                "Web search (Tavily) не вернул результатов. Кратко ответь по общим знаниям "
                "и укажи, что данные могут быть неактуальны.",
                system=ASSISTANT_SYSTEM_RU,
            )
            await event.reply(result.text or result.error)
            return
        lines = [
            _format_search_result(i, item)
            for i, item in enumerate(results[:5], start=1)
        ]
        sources_block = "Найденные источники:\n\n" + "\n\n".join(lines)
        summary_prompt = (
            f"Сегодня: {date.today().isoformat()}\n"
            f"Запрос пользователя: {q}\n\n"
            f"Результаты поиска:\n\n" + "\n\n".join(lines) + "\n\n"
            "Сделай краткую сводку на русском языке. Для актуальных запросов явно отдели "
            "подтвержденные свежими источниками факты от устаревших или неподтвержденных."
        )
        result = await router.ask_cloud(summary_prompt, system=SEARCH_SUMMARY_SYSTEM_RU)
        await event.reply(result.text or sources_block)
        return

    await event.reply(UNKNOWN_REPLY)
