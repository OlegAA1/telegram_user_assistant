"""Extract and normalize links from text and Telegram message entities."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from telethon.tl.types import MessageEntityMention, MessageEntityTextUrl, MessageEntityUrl
from telethon.utils import get_inner_text

_URL_IN_TEXT_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)
_TME_RE = re.compile(r"(?:https?://)?t\.me/[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(
    r"(?<![@\w])([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s]*)?",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"@([a-zA-Z][\w]{3,})")


def normalize_url(raw: str) -> str | None:
    s = (raw or "").strip().rstrip(".,;:!?)»\"'")
    if not s:
        return None
    lower = s.lower()
    if lower.startswith("@") and len(s) > 1:
        return f"https://t.me/{s[1:]}"
    if lower.startswith("t.me/"):
        return f"https://{s}" if not lower.startswith("http") else s
    if lower.startswith("http://") or lower.startswith("https://"):
        return s
    if "." in s and " " not in s and not s.startswith("."):
        return f"https://{s}"
    return None


def extract(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = normalize_url(raw)
        if not url:
            return
        key = url.lower().rstrip("/")
        if key in seen:
            return
        seen.add(key)
        found.append(url)

    for m in _URL_IN_TEXT_RE.finditer(text):
        add(m.group(0))
    for m in _TME_RE.finditer(text):
        add(m.group(0))
    for m in _MENTION_RE.finditer(text):
        add(m.group(0))
    for m in _BARE_DOMAIN_RE.finditer(text):
        add(m.group(0))
    return found


def message_text(message) -> str:
    return (getattr(message, "message", None) or getattr(message, "text", None) or "").strip()


def extract_from_message(message) -> list[str]:
    text = message_text(message)
    links = extract(text)
    entities = getattr(message, "entities", None) or []
    if text and entities:
        for ent in entities:
            if isinstance(ent, MessageEntityTextUrl) and ent.url:
                url = normalize_url(ent.url)
                if url and url not in links:
                    links.append(url)
            elif isinstance(ent, MessageEntityUrl):
                try:
                    part = get_inner_text(text, [ent])[0]
                except (IndexError, TypeError):
                    part = ""
                url = normalize_url(part)
                if url and url not in links:
                    links.append(url)
            elif isinstance(ent, MessageEntityMention):
                try:
                    part = get_inner_text(text, [ent])[0]
                except (IndexError, TypeError):
                    part = ""
                url = normalize_url(part)
                if url and url not in links:
                    links.append(url)

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for link in links:
        key = link.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


def domain_from_url(url: str) -> str:
    normalized = normalize_url(url) or url
    try:
        host = urlparse(normalized).netloc.lower()
    except Exception:
        return url.lower()
    return host.lstrip("www.") or url.lower()
