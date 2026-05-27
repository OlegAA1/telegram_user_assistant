"""Non-reminder command actions for conversational assistant intents."""

from __future__ import annotations

from app.config import Settings
from app.handlers.dialogs import reply_dialogs
from app.handlers.join_command import reply_join_targets
from app.handlers.server_status_command import server_status_text
from app.prompts.assistant_system import HELP_REPLY
from app.services.llm_router import LLMRouter


def _normalize_dialog_filter(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"channels", "channel", "каналы", "канал", "каналов"}:
        return "channels"
    if raw in {"groups", "group", "группы", "группа", "чат", "чаты"}:
        return "groups"
    if raw in {"users", "user", "people", "пользователи", "люди", "лички"}:
        return "users"
    return None


def _join_tail_from_intent(parsed: dict) -> str:
    targets = parsed.get("targets")
    if isinstance(targets, list):
        return " ".join(str(x).strip() for x in targets if str(x).strip())
    if isinstance(targets, str):
        return targets.strip()
    return str(parsed.get("text") or parsed.get("query") or "").strip()


async def handle_command_action_intent(
    event,
    *,
    parsed: dict,
    settings: Settings,
    router: LLMRouter,
) -> bool:
    intent = str(parsed.get("intent", "unknown")).strip().lower()

    if intent == "show_help":
        await event.reply(HELP_REPLY)
        return True

    if intent == "server_status":
        await event.reply(server_status_text())
        return True

    if intent == "provider_status":
        await event.reply(router.provider_status())
        return True

    if intent == "list_dialogs":
        await reply_dialogs(event, filter_name=_normalize_dialog_filter(parsed.get("filter")))
        return True

    if intent == "join_channels":
        await reply_join_targets(event, tail=_join_tail_from_intent(parsed))
        return True

    return False
