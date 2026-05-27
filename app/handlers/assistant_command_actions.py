"""Non-reminder command actions for conversational assistant intents."""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.config import Settings
from app.handlers.dialogs import reply_dialogs
from app.handlers.join_command import reply_join_targets
from app.handlers.server_status_command import server_status_text
from app.prompts.assistant_system import HELP_REPLY
from app.services.channel_join_service import MAX_JOIN_PER_COMMAND, parse_join_targets
from app.services.llm_router import LLMRouter

_JOIN_CONFIRM_TTL_SECONDS = 300
_CONFIRM_WORDS = {"да", "давай", "ок", "okay", "yes", "y", "подтверждаю", "подтвердить"}
_CANCEL_WORDS = {"нет", "не", "no", "n", "отмена", "отмени", "cancel", "стоп"}


@dataclass(frozen=True)
class _PendingJoinConfirmation:
    tail: str
    created_at: float


_PENDING_JOIN_CONFIRMATIONS: dict[tuple[int, int], _PendingJoinConfirmation] = {}


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


def _confirmation_key(event) -> tuple[int, int]:
    return int(event.sender_id), int(event.chat_id)


def _trim_expired_confirmations(now: float) -> None:
    expired = [
        key
        for key, pending in _PENDING_JOIN_CONFIRMATIONS.items()
        if now - pending.created_at > _JOIN_CONFIRM_TTL_SECONDS
    ]
    for key in expired:
        _PENDING_JOIN_CONFIRMATIONS.pop(key, None)


def _normalize_confirmation_text(text: str) -> str:
    return (text or "").strip().lower().replace(".", "").replace("!", "")


async def handle_pending_command_confirmation(event, *, user_text: str) -> bool:
    now = time.time()
    _trim_expired_confirmations(now)
    key = _confirmation_key(event)
    pending = _PENDING_JOIN_CONFIRMATIONS.get(key)
    if pending is None:
        return False

    normalized = _normalize_confirmation_text(user_text)
    if normalized in _CANCEL_WORDS:
        _PENDING_JOIN_CONFIRMATIONS.pop(key, None)
        await event.reply("Ок, подписку отменил.")
        return True
    if normalized not in _CONFIRM_WORDS:
        return False

    _PENDING_JOIN_CONFIRMATIONS.pop(key, None)
    await reply_join_targets(event, tail=pending.tail)
    return True


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
        tail = _join_tail_from_intent(parsed)
        targets = parse_join_targets(tail, max_targets=MAX_JOIN_PER_COMMAND)
        if not targets:
            await reply_join_targets(event, tail=tail)
            return True
        _PENDING_JOIN_CONFIRMATIONS[_confirmation_key(event)] = _PendingJoinConfirmation(
            tail=tail,
            created_at=time.time(),
        )
        displays = ", ".join(t.display for t in targets)
        await event.reply(
            f"Подтвердить подписку на {displays}? Ответь «да» или «нет»."
        )
        return True

    return False
