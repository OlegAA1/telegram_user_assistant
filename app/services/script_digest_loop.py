"""Background script run health digest delivery."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

from app.config import Settings, coerce_telethon_chat
from app.services.script_run_store import ScriptRunStore

logger = logging.getLogger(__name__)


async def run_script_digest_loop(
    client: TelegramClient,
    *,
    settings: Settings,
    store: ScriptRunStore,
    interval_sec: float = 60.0,
) -> None:
    if not settings.script_digest_chats:
        return

    interval_hours = max(1, settings.script_digest_interval_hours)
    interval = timedelta(hours=interval_hours)
    target_raw = settings.script_digest_target_chat or settings.script_digest_chats[0]
    target = coerce_telethon_chat(target_raw)
    logger.info(
        "Script digest enabled: chats=%s target=%s interval_hours=%s",
        settings.script_digest_chats,
        target_raw,
        interval_hours,
    )

    while True:
        try:
            if not settings.enable_script_digest:
                await asyncio.sleep(interval_sec)
                continue
            if not client.is_connected():
                await asyncio.sleep(interval_sec)
                continue

            now = datetime.now(timezone.utc)
            latest = store.latest_success_end()
            if latest is not None and now - latest < interval:
                await asyncio.sleep(interval_sec)
                continue

            period_end = now
            period_start = latest or (period_end - interval)
            report = store.build_report(start=period_start, end=period_end)
            await client.send_message(target, report)
            store.record_digest_run(
                period_start=period_start,
                period_end=period_end,
                status="success",
            )
            store.cleanup()
            logger.info("Script digest sent: target=%s period_hours=%s", target_raw, interval_hours)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(hours=max(1, settings.script_digest_interval_hours))
            store.record_digest_run(
                period_start=period_start,
                period_end=period_end,
                status="error",
                error=str(exc),
            )
            logger.exception("Script digest loop tick failed")
        await asyncio.sleep(interval_sec)
