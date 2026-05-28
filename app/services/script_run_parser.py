"""Parse structured script status messages from Telegram."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


_SCRIPT_RUN_RE = re.compile(
    r"^\s*(?:✅|❌)?\s*(?P<status>OK|ERROR)\s*\|\s*(?P<script>[^\n]+?)\s*\n"
    r"\s*Действие:\s*(?P<action>[^\n]+?)\s*\n"
    r"\s*(?P<profile>\d+)\s*-\s*(?:(?P<wallet>0x[0-9A-Fa-f.]+)\s*-\s*)?"
    r"(?P<created_at>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})"
    r"(?:\s*\n\s*Детали:\s*(?P<details>[^\n]+))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ScriptRun:
    status: str
    script_name: str
    action: str
    profile_number: int
    wallet: str
    details: str
    script_created_at: datetime | None


def parse_script_run(text: str, *, timezone_name: str) -> ScriptRun | None:
    m = _SCRIPT_RUN_RE.match((text or "").strip())
    if not m:
        return None

    script_created_at: datetime | None = None
    try:
        script_created_at = datetime.strptime(m.group("created_at"), "%Y-%m-%d %H:%M").replace(
            tzinfo=ZoneInfo(timezone_name),
        )
    except ValueError:
        script_created_at = None

    return ScriptRun(
        status=m.group("status").upper(),
        script_name=m.group("script").strip(),
        action=m.group("action").strip(),
        profile_number=int(m.group("profile")),
        wallet=(m.group("wallet") or "").strip(),
        details=(m.group("details") or "").strip(),
        script_created_at=script_created_at,
    )
