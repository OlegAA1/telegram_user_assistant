"""Join Telegram channels/groups via Telethon (user account)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Literal

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

logger = logging.getLogger(__name__)

MAX_JOIN_PER_COMMAND = 3

_JOIN_TOKEN_RE = re.compile(
    r"(@?[a-zA-Z][\w]{3,})|"
    r"(https?://t\.me/[^\s]+)|"
    r"(-100\d+)",
    re.IGNORECASE,
)
_TME_RE = re.compile(r"https?://t\.me/(?:\+|joinchat/)?(.+)", re.IGNORECASE)


@dataclass(frozen=True)
class JoinTarget:
    kind: Literal["username", "invite", "id"]
    value: str
    display: str


@dataclass(frozen=True)
class JoinOutcome:
    display: str
    ok: bool
    message: str


def parse_join_targets(text: str, *, max_targets: int = MAX_JOIN_PER_COMMAND) -> list[JoinTarget]:
    """Extract up to max_targets unique join targets from command tail."""
    seen: set[str] = set()
    out: list[JoinTarget] = []

    for m in _JOIN_TOKEN_RE.finditer(text or ""):
        if len(out) >= max_targets:
            break
        raw_user, raw_url, raw_id = m.groups()
        target: JoinTarget | None = None
        if raw_url:
            target = _target_from_tme_url(raw_url.strip())
        elif raw_id:
            target = JoinTarget(kind="id", value=raw_id, display=raw_id)
        elif raw_user:
            name = raw_user.lstrip("@")
            target = JoinTarget(kind="username", value=name, display=f"@{name}")

        if target is None:
            continue
        key = f"{target.kind}:{target.value.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(target)
    return out


def _target_from_tme_url(url: str) -> JoinTarget | None:
    lower = url.lower()
    if "/+" in lower or "/joinchat/" in lower:
        m = _TME_RE.match(url)
        if not m:
            return None
        invite_hash = m.group(1).split("?")[0].strip("/")
        if not invite_hash:
            return None
        return JoinTarget(kind="invite", value=invite_hash, display=url)
    m = re.match(r"https?://t\.me/([a-zA-Z][\w]{3,})", url, re.IGNORECASE)
    if not m:
        return None
    username = m.group(1)
    return JoinTarget(kind="username", value=username, display=f"@{username}")


def _entity_title(entity) -> str:
    title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
    return str(title) if title else "канал"


async def join_target(client: TelegramClient, target: JoinTarget) -> JoinOutcome:
    try:
        if target.kind == "invite":
            result = await client(ImportChatInviteRequest(target.value))
            chats = getattr(result, "chats", None) or []
            title = _entity_title(chats[0]) if chats else target.display
            logger.info("Joined via invite: display=%s", target.display)
            return JoinOutcome(
                display=target.display,
                ok=True,
                message=f"Подписался: {title}",
            )

        entity = await client.get_entity(
            int(target.value) if target.kind == "id" else target.value,
        )
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            title = _entity_title(entity)
            return JoinOutcome(
                display=target.display,
                ok=True,
                message=f"Уже подписан: {title}",
            )

        title = _entity_title(entity)
        logger.info("Joined channel: display=%s title=%s", target.display, title)
        return JoinOutcome(
            display=target.display,
            ok=True,
            message=f"Подписался: {title}",
        )

    except UserAlreadyParticipantError:
        return JoinOutcome(
            display=target.display,
            ok=True,
            message="Уже подписан на этот канал",
        )
    except FloodWaitError as exc:
        logger.warning("FloodWait on join display=%s seconds=%s", target.display, exc.seconds)
        return JoinOutcome(
            display=target.display,
            ok=False,
            message=f"Лимит Telegram, подожди {exc.seconds} сек. и повтори",
        )
    except (InviteHashExpiredError, InviteHashInvalidError):
        return JoinOutcome(
            display=target.display,
            ok=False,
            message="Ссылка-приглашение недействительна или истекла",
        )
    except Exception:
        logger.exception("Join failed for display=%s", target.display)
        return JoinOutcome(
            display=target.display,
            ok=False,
            message="Не удалось подписаться (канал закрыт, нет доступа или неверная ссылка)",
        )


async def join_targets(
    client: TelegramClient,
    targets: list[JoinTarget],
    *,
    pause_seconds: float = 1.5,
) -> list[JoinOutcome]:
    outcomes: list[JoinOutcome] = []
    for i, target in enumerate(targets):
        outcomes.append(await join_target(client, target))
        if i < len(targets) - 1 and pause_seconds > 0:
            await asyncio.sleep(pause_seconds)
    return outcomes
