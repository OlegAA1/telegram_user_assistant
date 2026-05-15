"""Telethon user client entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path

# Support `python app/main.py` (script run) and `python -m app.main` (package run)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telethon import TelegramClient, events

from app.config import coerce_telethon_chat, load_settings
from app.handlers.assistant_dm import assistant_natural_predicate, handle_assistant_natural
from app.handlers.cloud_commands import (
    analyze_command_predicate,
    cloud_command_predicate,
    handle_analyze_command,
    handle_cloud_command,
    handle_provider_command,
    provider_command_predicate,
)
from app.handlers.new_message import handle_new_message
from app.handlers.owner_ask import ask_command_predicate, handle_owner_ask
from app.handlers.reminder_command import handle_remind_command, remind_command_predicate
from app.handlers.search_command import handle_search_command, search_command_predicate
from app.logger import setup_logging
from app.services.filter_service import FilterService
from app.services.forwarder import Forwarder
from app.services.llm_service import LLMService
from app.services.llm_router import LLMRouter
from app.services.openrouter_service import OpenRouterService
from app.services.reminder_loop import run_reminder_loop
from app.services.reminder_store import ReminderStore
from app.services.storage import ProcessedStore
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = load_settings()
    setup_logging(_ROOT / "logs" / "app.log")

    store = ProcessedStore(settings.dedup_db_path)
    reminder_store = ReminderStore(settings.reminder_db_path)
    reminder_task: asyncio.Task[None] | None = None
    try:
        filters = FilterService(settings)
        forwarder = Forwarder()
        llm = LLMService(settings)
        openrouter = OpenRouterService(settings)
        router = LLMRouter(settings=settings, local=llm, openrouter=openrouter)
        web_search = WebSearchService(settings)

        session_path = str(_ROOT / settings.session_name)
        client = TelegramClient(session_path, settings.api_id, settings.api_hash)

        source_entities = [coerce_telethon_chat(x) for x in settings.source_chats]

        if settings.ask_sender_ids:
            allowed = list(settings.ask_sender_ids)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: ask_command_predicate(e),
                ),
            )
            async def _on_owner_ask(event: events.NewMessage.Event) -> None:
                await handle_owner_ask(event, settings=settings, router=router)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: cloud_command_predicate(e),
                ),
            )
            async def _on_cloud(event: events.NewMessage.Event) -> None:
                await handle_cloud_command(event, settings=settings, router=router)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: analyze_command_predicate(e),
                ),
            )
            async def _on_analyze(event: events.NewMessage.Event) -> None:
                await handle_analyze_command(event, settings=settings, router=router)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: provider_command_predicate(e),
                ),
            )
            async def _on_provider(event: events.NewMessage.Event) -> None:
                await handle_provider_command(event, settings=settings, router=router)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: search_command_predicate(e),
                ),
            )
            async def _on_search(event: events.NewMessage.Event) -> None:
                await handle_search_command(
                    event,
                    settings=settings,
                    search=web_search,
                    router=router,
                )

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: remind_command_predicate(e),
                ),
            )
            async def _on_remind(event: events.NewMessage.Event) -> None:
                await handle_remind_command(event, settings=settings, reminders=reminder_store)

            @client.on(
                events.NewMessage(
                    from_users=allowed,
                    func=lambda e: assistant_natural_predicate(e),
                ),
            )
            async def _on_assistant_natural(event: events.NewMessage.Event) -> None:
                await handle_assistant_natural(
                    event,
                    settings=settings,
                    llm=llm,
                    router=router,
                    reminders=reminder_store,
                    search=web_search,
                )

            logger.info(
                "/ask, /remind и личный ассистент (без /) для user ids: %s (REMINDER_TZ=%s)",
                sorted(allowed),
                settings.reminder_tz,
            )
        else:
            logger.warning(
                "ASK_SENDER_IDS (or legacy OWNER_ID) is empty: private /ask, /remind и личный ассистент отключены",
            )

        @client.on(events.NewMessage(chats=source_entities))
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            await handle_new_message(
                event,
                settings=settings,
                store=store,
                filters=filters,
                forwarder=forwarder,
                llm=llm,
            )

        await client.start(phone=settings.phone or None)
        me = await client.get_me()
        logger.info("Logged in as id=%s username=%s", me.id, getattr(me, "username", None))
        logger.info(
            "Assistant running: sources=%s targets=%s forward_original=%s use_llm=%s",
            settings.source_chats,
            settings.target_chats,
            settings.forward_original,
            settings.use_llm,
        )

        reminder_task = asyncio.create_task(
            run_reminder_loop(client, reminder_store),
            name="reminder_loop",
        )
        await client.run_until_disconnected()
    finally:
        if reminder_task is not None:
            reminder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminder_task
        reminder_store.close()
        store.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
