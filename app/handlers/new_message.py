"""Handle incoming messages from monitored source chats."""

from __future__ import annotations

import logging

from app.config import Settings, coerce_telethon_chat
from app.services.filter_service import FilterService
from app.services.forwarder import Forwarder
from app.services.llm_service import LLMService
from app.services.storage import ProcessedStore

logger = logging.getLogger(__name__)


async def handle_new_message(
    event,
    *,
    settings: Settings,
    store: ProcessedStore,
    filters: FilterService,
    forwarder: Forwarder,
    llm: LLMService,
) -> None:
    message = event.message
    if not message:
        return

    if settings.ask_sender_ids and event.is_private and event.sender_id in settings.ask_sender_ids:
        body = (message.message or "").lstrip()
        if body.startswith("/ask") and not getattr(message, "out", False):
            return

    chat_id = int(event.chat_id)
    message_id = int(message.id)

    if store.is_processed(chat_id, message_id):
        logger.debug("Skip already processed message %s/%s", chat_id, message_id)
        return

    if not await filters.passes(event):
        return

    try:
        if settings.forward_original:
            await forwarder.forward_original(event.client, message, settings.target_chats)

        if settings.use_llm:
            text = (event.raw_text or "").strip()
            if not text:
                logger.info(
                    "USE_LLM is on but message %s/%s has no text; skipping LLM output",
                    chat_id,
                    message_id,
                )
            else:
                analysis = await llm.analyze(text)
                if analysis:
                    for raw in settings.target_chats:
                        target = coerce_telethon_chat(raw)
                        await event.client.send_message(target, analysis)
                else:
                    logger.warning("LLM returned empty output for message %s/%s", chat_id, message_id)

        store.mark_processed(chat_id, message_id)
    except Exception:
        logger.exception("Error while processing message %s/%s", chat_id, message_id)
