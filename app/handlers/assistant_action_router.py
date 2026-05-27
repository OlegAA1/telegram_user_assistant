"""Route parsed assistant intents to concrete actions."""

from __future__ import annotations

import logging
from datetime import date

from app.config import Settings
from app.handlers.assistant_command_actions import handle_command_action_intent
from app.handlers.assistant_reminder_actions import handle_reminder_action_intent
from app.prompts.assistant_system import ASSISTANT_SYSTEM_RU, SEARCH_SUMMARY_SYSTEM_RU
from app.services.crypto_price_service import (
    CryptoPriceError,
    CryptoPriceService,
    format_crypto_price_reply,
)
from app.services.llm_router import LLMRouter
from app.services.reminder_store import ReminderStore
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)


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


async def reply_crypto_price(
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


async def handle_parsed_assistant_intent(
    event,
    *,
    parsed: dict,
    user_text: str,
    settings: Settings,
    router: LLMRouter,
    reminders: ReminderStore,
    search: WebSearchService,
    crypto: CryptoPriceService,
) -> bool:
    intent = str(parsed.get("intent", "unknown")).strip().lower()

    if await handle_reminder_action_intent(
        event,
        parsed=parsed,
        settings=settings,
        reminders=reminders,
    ):
        return True

    if await handle_command_action_intent(
        event,
        parsed=parsed,
        settings=settings,
        router=router,
    ):
        return True

    if intent == "crypto_price":
        asset = (parsed.get("asset") or parsed.get("symbol") or "").strip()
        vs = (parsed.get("vs_currency") or settings.default_crypto_vs_currency).strip().lower()
        if not asset:
            await event.reply("Не понял монету. Примеры: btc, eth, sol, ton, bnb")
            return True
        await reply_crypto_price(event, crypto=crypto, asset=asset, vs_currency=vs)
        return True

    if intent in {"ask_llm", "local_ask"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_local(q)
        await event.reply(result.text or result.error or "Пустой ответ модели.")
        return True

    if intent in {"cloud_ask", "deep_analysis"}:
        q = (parsed.get("text") or "").strip() or user_text
        result = await router.ask_cloud(q)
        await event.reply(result.text or result.error)
        return True

    if intent == "web_search":
        q = (parsed.get("query") or parsed.get("text") or user_text).strip()
        results = await search.search(q)
        if not results:
            if not settings.enable_web_search:
                await event.reply("Для актуальной информации включи ENABLE_WEB_SEARCH или используй /cloud.")
                return True
            result = await router.ask_cloud(
                f"Пользователь запросил актуальную информацию: {q}\n"
                "Web search (Tavily) не вернул результатов. Кратко ответь по общим знаниям "
                "и укажи, что данные могут быть неактуальны.",
                system=ASSISTANT_SYSTEM_RU,
            )
            await event.reply(result.text or result.error)
            return True
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
        return True

    return False
