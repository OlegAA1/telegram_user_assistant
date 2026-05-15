"""Shared helpers for owner-only private commands."""

from __future__ import annotations

_OWNER_SLASH_PREFIXES = (
    "/ask",
    "/search",
    "/cloud",
    "/analyze",
    "/provider",
    "/price",
    "/dialogs",
    "/join",
    "/remind",
    "/check",
)


def is_owner_slash_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(t.startswith(prefix) for prefix in _OWNER_SLASH_PREFIXES)
