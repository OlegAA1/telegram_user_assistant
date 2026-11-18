"""Reply under a forwarded post / testnet card -> AI answers with the post as context."""

from __future__ import annotations

import logging

from app.config import Settings
from app.handlers.testnet_handler import collect_links
from app.services.post_dialog import PostDialogService, build_context, is_bot_text

logger = logging.getLogger(__name__)


def post_dialog_predicate(event, settings: Settings) -> bool:
    message = event.message
    if not message or not getattr(message, "reply_to_msg_id", None):
        return False
    text = (message.message or "").strip()
    if not text or text.startswith("/"):
        return False
    if getattr(message, "out", False):
        # The owner may write from the assistant account itself (e.g. Saved Messages),
        # but never react to our own answers/cards.
        return not is_bot_text(text) and getattr(message, "fwd_from", None) is None
    if event.is_private:
        return False  # private chats with allowed users are handled by the DM assistant
    return event.sender_id in settings.ask_sender_ids


async def _load_chain(message, max_depth: int) -> list:
    chain = []
    current = message
    for _ in range(max_depth):
        try:
            parent = await current.get_reply_message()
        except Exception:
            logger.exception("Post dialog: failed to load replied message")
            break
        if parent is None:
            break
        chain.append(parent)
        if not getattr(parent, "reply_to_msg_id", None):
            break
        current = parent
    chain.reverse()  # root post first
    return chain


async def handle_post_dialog(event, *, settings: Settings, service: PostDialogService) -> None:
    message = event.message
    chain = await _load_chain(message, settings.post_dialog_max_depth)
    if not chain:
        return
    # Only talk about posts the assistant is involved in: a forwarded post or our own message.
    if not any(getattr(m, "out", False) or getattr(m, "fwd_from", None) is not None for m in chain):
        return

    ctx = build_context(chain, links_of=collect_links)
    question = (message.message or "").strip()
    logger.info(
        "Post dialog: chat=%s msg=%s depth=%s card=%s",
        event.chat_id,
        message.id,
        len(chain),
        ctx.card_id,
    )
    try:
        async with event.client.action(event.chat_id, "typing"):
            answer = await service.answer(ctx, question)
    except Exception:
        logger.exception("Post dialog failed")
        answer = "⚠️ Не удалось получить ответ: внутренняя ошибка, см. логи."
    await event.reply(answer, link_preview=False)
