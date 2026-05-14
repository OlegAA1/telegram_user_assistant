"""Telethon user client entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Support `python app/main.py` (script run) and `python -m app.main` (package run)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telethon import TelegramClient, events

from app.config import coerce_telethon_chat, load_settings
from app.handlers.new_message import handle_new_message
from app.handlers.owner_ask import handle_owner_ask, owner_ask_predicate
from app.logger import setup_logging
from app.services.filter_service import FilterService
from app.services.forwarder import Forwarder
from app.services.llm_service import LLMService
from app.services.storage import ProcessedStore

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = load_settings()
    setup_logging(_ROOT / "logs" / "app.log")

    store = ProcessedStore(settings.dedup_db_path)
    try:
        filters = FilterService(settings)
        forwarder = Forwarder()
        llm = LLMService(settings)

        session_path = str(_ROOT / settings.session_name)
        client = TelegramClient(session_path, settings.api_id, settings.api_hash)

        source_entities = [coerce_telethon_chat(x) for x in settings.source_chats]

        if settings.owner_id is not None:
            owner_id = settings.owner_id

            @client.on(
                events.NewMessage(
                    incoming=True,
                    func=lambda e, oid=owner_id: owner_ask_predicate(e, oid),
                ),
            )
            async def _on_owner_ask(event: events.NewMessage.Event) -> None:
                await handle_owner_ask(event, settings=settings, llm=llm)

            logger.info("Owner /ask enabled for OWNER_ID=%s", owner_id)

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
        await client.run_until_disconnected()
    finally:
        store.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
