"""Auto-analysis of posts in TESTNET_CHATS + /testnets, /testnet commands."""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings, coerce_telethon_chat
from app.services.link_extractor import extract_from_message, normalize_url
from app.services.testnet_analyzer import CARD_PREFIX, DUPLICATE_PREFIX, TestnetAnalyzer, primary_domain
from app.services.testnet_store import StoredTestnet, TestnetStore

logger = logging.getLogger(__name__)

_COMMAND_RE = re.compile(r"^/(testnets|testnet)(?:@\S+)?(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


# --- helpers -------------------------------------------------------------------


def collect_links(message) -> list[str]:
    """Links from text, hidden text links, inline buttons and the web preview."""
    links = extract_from_message(message)

    def add(raw: str | None) -> None:
        url = normalize_url(raw or "")
        if url and url.lower().rstrip("/") not in {l.lower().rstrip("/") for l in links}:
            links.append(url)

    markup = getattr(message, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            add(getattr(button, "url", None))
    webpage = getattr(getattr(message, "media", None), "webpage", None)
    add(getattr(webpage, "url", None))
    return links


async def forward_source(message) -> tuple[str, str]:
    """(title, link to original post) for forwarded messages."""
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return "", ""
    title = getattr(fwd, "from_name", None) or ""
    url = ""
    try:
        forward = message.forward
        chat = await forward.get_chat() if forward is not None else None
    except Exception:
        chat = None
    if chat is not None:
        title = getattr(chat, "title", None) or title
        username = getattr(chat, "username", None)
        post_id = getattr(fwd, "channel_post", None)
        if username and post_id:
            url = f"https://t.me/{username}/{post_id}"
    return title, url


def is_own_card(message) -> bool:
    if not getattr(message, "out", False) or getattr(message, "fwd_from", None) is not None:
        return False
    text = (getattr(message, "message", None) or "").lstrip()
    return text.startswith((CARD_PREFIX, DUPLICATE_PREFIX, "⚠️ Не удалось", "💬"))


def _fmt_date(unix: int, tz: str) -> str:
    return datetime.fromtimestamp(unix, ZoneInfo(tz)).strftime("%d.%m.%Y")


def _footer(item_id: int) -> str:
    return f"\n\n#testnet · /testnet {item_id}"


def format_list(items: list[StoredTestnet], tz: str) -> str:
    if not items:
        return "Пока ни одного разобранного тестнета."
    lines = ["<b>Последние разборы:</b>"]
    for it in items:
        score = f"{it.score}/10" if it.score is not None else "?/10"
        verdict = f" — {html.escape(it.verdict)}" if it.verdict else ""
        lines.append(f"#{it.id} · {_fmt_date(it.created_at_unix, tz)} · <b>{html.escape(it.name)}</b> · {score}{verdict}")
    lines.append("\nПолный разбор: /testnet ID или /testnet название")
    return "\n".join(lines)


# --- auto analysis -----------------------------------------------------------------


async def handle_testnet_message(
    event,
    *,
    settings: Settings,
    store: TestnetStore,
    analyzer: TestnetAnalyzer,
) -> None:
    message = event.message
    if not message or is_own_card(message):
        return
    text = (message.message or "").strip()
    if text.startswith("/"):
        return
    if getattr(message, "reply_to_msg_id", None) and getattr(message, "fwd_from", None) is None:
        return  # a reply under a post is a follow-up question (post dialog), not a new post
    chat_id = int(event.chat_id)
    message_id = int(message.id)
    if store.is_message_processed(chat_id, message_id):
        return

    links = collect_links(message)
    if len(text) < 20 and not links:
        store.mark_message_processed(chat_id, message_id)
        return
    store.mark_message_processed(chat_id, message_id)

    target = coerce_telethon_chat(settings.testnet_target_chat) if settings.testnet_target_chat else chat_id
    reply_to = message_id if target == chat_id else None
    client = event.client
    since = int(time.time()) - settings.testnet_dedup_days * 86400

    domain = primary_domain(links)
    previous = store.find_recent_by_domain(domain, since_unix=since) if domain else None
    if previous is not None:
        logger.info("Testnet duplicate by domain %s -> #%s", domain, previous.id)
        await client.send_message(
            target,
            f"{DUPLICATE_PREFIX} Уже разбирали {_fmt_date(previous.created_at_unix, settings.reminder_tz)}: "
            f"<b>{html.escape(previous.name)}</b> "
            f"({previous.score if previous.score is not None else '?'}/10"
            f"{', ' + html.escape(previous.verdict) if previous.verdict else ''}).\n"
            f"Полный разбор: /testnet {previous.id}",
            reply_to=reply_to,
            parse_mode="html",
        )
        return

    source, source_url = await forward_source(message)
    status = await client.send_message(target, f"{CARD_PREFIX} Разбираю пост…", reply_to=reply_to)
    logger.info("Testnet analysis: chat=%s msg=%s links=%s domain=%s", chat_id, message_id, len(links), domain)

    try:
        result = await analyzer.analyze(text, links, source=source, source_url=source_url)
    except Exception:
        logger.exception("Testnet analysis crashed for %s/%s", chat_id, message_id)
        await status.edit("⚠️ Не удалось разобрать пост: внутренняя ошибка, см. логи.")
        return

    if result.error:
        await status.edit(f"⚠️ Не удалось разобрать пост: {result.error}")
        return

    if not result.relevant and settings.testnet_skip_irrelevant:
        logger.info("Testnet analysis: message %s/%s is not an activity, skipped", chat_id, message_id)
        await status.delete()
        return

    prefix = ""
    if result.name:
        same_name = store.find_recent_by_name(result.name, since_unix=since)
        if same_name is not None:
            prefix = (
                f"{DUPLICATE_PREFIX} Похоже, проект уже был: #{same_name.id} от "
                f"{_fmt_date(same_name.created_at_unix, settings.reminder_tz)}. Свежий разбор:\n\n"
            )

    item_id = store.save(
        name=result.name or "Без названия",
        domain=result.domain,
        score=result.score,
        verdict=result.verdict,
        card=result.card,
        report_json=result.report_json,
        source_chat_id=chat_id,
        source_message_id=message_id,
    )
    await status.edit(prefix + result.card + _footer(item_id), parse_mode="html", link_preview=False)


# --- commands in DM ------------------------------------------------------------------


def testnet_command_predicate(event) -> bool:
    if not event.message or not event.is_private or getattr(event.message, "out", False):
        return False
    return bool(_COMMAND_RE.match((event.message.message or "").strip()))


async def handle_testnet_command(event, *, settings: Settings, store: TestnetStore) -> None:
    if not settings.ask_sender_ids or event.sender_id not in settings.ask_sender_ids:
        return
    m = _COMMAND_RE.match((event.message.message or "").strip())
    if not m:
        return
    command, arg = m.group(1).lower(), (m.group(2) or "").strip()
    if command == "testnets" or not arg:
        await event.reply(format_list(store.list_recent(15), settings.reminder_tz), parse_mode="html")
        return
    item = store.get(arg)
    if item is None:
        await event.reply("Не нашёл такой разбор. Список: /testnets")
        return
    await event.reply(item.card + _footer(item.id), parse_mode="html", link_preview=False)
