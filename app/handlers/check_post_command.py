"""Manual scam check: /check, phrases, and auto-check on links in scam group."""

from __future__ import annotations

from app.config import Settings
from app.handlers.scam_check_access import (
    MSG_DM_REDIRECT,
    MSG_NO_FRESH_POST,
    MSG_NO_GROUP_CONFIGURED,
    MSG_WRONG_CHAT,
    is_allowed_sender,
    is_group_configured,
    is_manual_scam_enabled,
    is_scam_check_group_chat,
    is_scam_check_trigger,
    log_no_group_configured,
    log_scam_check_started,
    log_wrong_chat,
)
from app.services.link_extractor import extract_from_message
from app.services.pending_post_store import PendingPostStore
from app.services.scam_check_service import ScamCheckService


def scam_check_trigger_predicate(event) -> bool:
    if not event.message:
        return False
    if getattr(event.message, "out", False):
        return False
    return is_scam_check_trigger(event.message.message or "")


async def run_scam_check(
    event,
    *,
    settings: Settings,
    pending_store: PendingPostStore,
    scam_check: ScamCheckService,
    message=None,
) -> str | None:
    """Run scam check on the latest pending post in the scam group. Returns reply text."""
    owner_id = int(event.sender_id)
    group_id = int(settings.scam_check_group_id)  # type: ignore[arg-type]
    post = pending_store.get_fresh(owner_id, expected_chat_id=group_id)
    if post is None:
        return None

    if message is None:
        try:
            message = await event.get_message()
        except Exception:
            message = event.message

    links_count = len(extract_from_message(message)) if message else 0
    log_scam_check_started(
        owner_id=owner_id,
        message_id=post.message_id,
        links=links_count,
    )
    return await scam_check.check_post(post, message=message)


async def handle_scam_check_trigger(
    event,
    *,
    settings: Settings,
    pending_store: PendingPostStore,
    scam_check: ScamCheckService,
) -> None:
    if not is_manual_scam_enabled(settings):
        return
    if not is_allowed_sender(settings, event.sender_id):
        return

    raw = (event.message.message or "").strip()
    if not is_scam_check_trigger(raw):
        return

    if not is_group_configured(settings):
        log_no_group_configured()
        await event.reply(MSG_NO_GROUP_CONFIGURED)
        return

    if not is_scam_check_group_chat(event, settings):
        log_wrong_chat(event, settings)
        if event.is_private:
            await event.reply(MSG_DM_REDIRECT)
        else:
            await event.reply(MSG_WRONG_CHAT)
        return

    result = await run_scam_check(
        event,
        settings=settings,
        pending_store=pending_store,
        scam_check=scam_check,
    )
    if result is None:
        await event.reply(MSG_NO_FRESH_POST)
        return
    await event.reply(result)
