"""Background delivery of due reminders."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telethon import TelegramClient

from app.services.reminder_store import ReminderStore

logger = logging.getLogger(__name__)


async def run_reminder_loop(client: TelegramClient, store: ReminderStore, interval_sec: float = 15.0) -> None:
    while True:
        try:
            if not client.is_connected():
                await asyncio.sleep(interval_sec)
                continue
            due = store.fetch_due(datetime.now(timezone.utc))
            for r in due:
                text = f"⏰ Напоминание #{r.id}\n{r.body}"
                try:
                    await client.send_message(r.chat_id, text)
                    store.delete_reminder(r.id)
                except Exception:
                    logger.exception(
                        "Failed to send reminder id=%s chat_id=%s (will retry)",
                        r.id,
                        r.chat_id,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder loop tick failed")
        await asyncio.sleep(interval_sec)
