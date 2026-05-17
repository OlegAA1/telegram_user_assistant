"""Background daily summary delivery."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telethon import TelegramClient, utils

from app.config import Settings, coerce_telethon_chat
from app.services.chat_summarizer import ChatSummarizer
from app.services.daily_summary_store import DailySummaryStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryChat:
    chat_id: int
    title: str
    username: str


def _parse_summary_time(raw: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw.strip())
    if not m:
        raise ValueError("SUMMARY_TIME must have HH:MM format")
    hour = int(m.group(1))
    minute = int(m.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("SUMMARY_TIME must have valid HH:MM values")
    return hour, minute


def _entity_title(entity) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(entity, "username", None)
    return f"@{username}" if username else str(getattr(entity, "id", "unknown"))


async def resolve_summary_chats(client: TelegramClient, settings: Settings) -> list[SummaryChat]:
    out: list[SummaryChat] = []
    for raw in settings.summary_chats:
        entity = await client.get_entity(coerce_telethon_chat(raw))
        out.append(
            SummaryChat(
                chat_id=int(utils.get_peer_id(entity)),
                title=_entity_title(entity),
                username=str(getattr(entity, "username", "") or ""),
            ),
        )
    return out


async def run_daily_summary_loop(
    client: TelegramClient,
    *,
    settings: Settings,
    store: DailySummaryStore,
    summarizer: ChatSummarizer,
    interval_sec: float = 60.0,
) -> None:
    hour, minute = _parse_summary_time(settings.summary_time)
    tz = ZoneInfo(settings.summary_tz)
    target = coerce_telethon_chat(settings.summary_target_chat)
    chats: list[SummaryChat] = []

    while True:
        try:
            if not settings.enable_daily_summary or not settings.summary_chats:
                await asyncio.sleep(interval_sec)
                continue
            if not client.is_connected():
                await asyncio.sleep(interval_sec)
                continue
            if not chats:
                chats = await resolve_summary_chats(client, settings)
                logger.info(
                    "Daily summaries enabled: chats=%s target=%s time=%s tz=%s",
                    [c.title for c in chats],
                    settings.summary_target_chat,
                    settings.summary_time,
                    settings.summary_tz,
                )

            now_local = datetime.now(tz)
            scheduled_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now_local < scheduled_local and not _is_overdue(store, tz, scheduled_local):
                await asyncio.sleep(interval_sec)
                continue
            if _already_ran_today(store, tz, now_local):
                await asyncio.sleep(interval_sec)
                continue

            period_end = datetime.now(timezone.utc)
            for chat in chats:
                await _summarize_chat(
                    client,
                    target=target,
                    chat=chat,
                    store=store,
                    summarizer=summarizer,
                    period_end=period_end,
                )
            store.cleanup()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily summary loop tick failed")
        await asyncio.sleep(interval_sec)


def _already_ran_today(store: DailySummaryStore, tz: ZoneInfo, now_local: datetime) -> bool:
    latest = store.latest_any_success_end()
    if latest is None:
        return False
    return latest.astimezone(tz).date() == now_local.date()


def _is_overdue(store: DailySummaryStore, tz: ZoneInfo, scheduled_local: datetime) -> bool:
    latest = store.latest_any_success_end()
    if latest is None:
        return False
    return latest.astimezone(tz) < scheduled_local - timedelta(hours=25)


async def _summarize_chat(
    client: TelegramClient,
    *,
    target,
    chat: SummaryChat,
    store: DailySummaryStore,
    summarizer: ChatSummarizer,
    period_end: datetime,
) -> None:
    latest = store.latest_success_end(chat.chat_id)
    period_start = latest or (period_end - timedelta(hours=24))
    try:
        messages = store.fetch_messages(chat.chat_id, period_start, period_end)
        memory = store.get_memory(chat.chat_id)
        result = await summarizer.summarize(
            chat_title=chat.title,
            chat_username=chat.username,
            period_start=period_start,
            period_end=period_end,
            messages=messages,
            previous_memory=memory,
        )
        await client.send_message(target, result.text)
        store.save_summary(
            chat_id=chat.chat_id,
            chat_title=chat.title,
            chat_username=chat.username,
            period_start=period_start,
            period_end=period_end,
            message_count=len(messages),
            summary_text=result.text,
            memory_text=result.memory_text,
            used_cloud=result.used_cloud,
        )
        store.record_run(
            chat_id=chat.chat_id,
            period_start=period_start,
            period_end=period_end,
            status="success",
        )
        logger.info(
            "Daily summary sent: chat_id=%s title=%s messages=%s cloud=%s",
            chat.chat_id,
            chat.title,
            len(messages),
            result.used_cloud,
        )
    except Exception as exc:
        store.record_run(
            chat_id=chat.chat_id,
            period_start=period_start,
            period_end=period_end,
            status="error",
            error=str(exc),
        )
        logger.exception("Failed to summarize chat_id=%s title=%s", chat.chat_id, chat.title)
