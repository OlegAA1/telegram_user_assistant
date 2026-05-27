"""Natural-language private messages for allowed senders (intent → remind or LLM)."""

from __future__ import annotations

import logging

from app.config import Settings
from app.handlers.assistant_action_router import (
    handle_parsed_assistant_intent,
    reply_crypto_price,
)
from app.handlers.assistant_command_actions import handle_pending_command_confirmation
from app.handlers.assistant_intents import (
    ACTION_UNCLEAR_REPLY,
    classify_assistant_intent,
    looks_like_command_action_text,
)
from app.handlers.assistant_reminder_actions import handle_reminder_text_shortcut
from app.prompts.assistant_system import (
    ASSISTANT_SYSTEM_RU,
    HELP_REPLY,
)
from app.services.crypto_price_parser import looks_like_crypto_price_query, try_parse_crypto_price
from app.services.crypto_price_service import CryptoPriceService
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

    if await handle_pending_command_confirmation(event, user_text=user_text):
        return

    # Deterministic crypto price (before LLM intent parser)
    if looks_like_crypto_price_query(user_text):
        parsed_crypto = try_parse_crypto_price(
            user_text,
            default_vs=settings.default_crypto_vs_currency,
        )
        if parsed_crypto:
            await reply_crypto_price(
                event,
                crypto=crypto,
                asset=parsed_crypto.asset,
                vs_currency=parsed_crypto.vs_currency,
            )
            return
        await event.reply("Не понял монету. Примеры: btc, eth, sol, ton, bnb")
        return

    if await handle_reminder_text_shortcut(
        event,
        user_text=user_text,
        settings=settings,
        reminders=reminders,
    ):
        return

    followup_prompt = await build_reply_followup_prompt(event, user_text)
    if followup_prompt:
        result = await router.ask_cloud(followup_prompt, system=ASSISTANT_SYSTEM_RU)
        await event.reply(result.text or result.error)
        return

    parsed = await classify_assistant_intent(llm, user_text)

    if not isinstance(parsed, dict):
        if looks_like_command_action_text(user_text):
            logger.info("Intent action-like fallback blocked (invalid JSON)")
            await event.reply(ACTION_UNCLEAR_REPLY)
            return
        logger.info("Intent fallback to ask_llm (invalid JSON)")
        result = await router.ask_local(user_text)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return

    if await handle_parsed_assistant_intent(
        event,
        parsed=parsed,
        user_text=user_text,
        settings=settings,
        router=router,
        reminders=reminders,
        search=search,
        crypto=crypto,
    ):
        return

    if looks_like_command_action_text(user_text):
        logger.info("Intent action-like fallback blocked (unhandled intent)")
        await event.reply(ACTION_UNCLEAR_REPLY)
        return

    await event.reply(UNKNOWN_REPLY)
