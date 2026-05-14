"""Load settings from environment (.env)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def coerce_telethon_chat(raw: str) -> str | int:
    """Username (without @) or numeric chat/channel id as used by Telethon filters."""
    s = raw.strip()
    if not s:
        raise ValueError("Empty chat identifier")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s.lstrip("@")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_json_list(name: str, default: str = "[]") -> list:
    raw = os.getenv(name, default)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON array, got: {raw!r}") from exc
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _parse_json_str_list(name: str, default: str = "[]") -> list[str]:
    items = _parse_json_list(name, default)
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, int):
            out.append(str(item))
        else:
            raise ValueError(f"{name} items must be string or integer, got {type(item)}")
    return out


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    session_name: str
    source_chats: list[str]
    target_chats: list[str]
    filter_keywords: list[str]
    forward_original: bool
    use_llm: bool
    llm_model: str
    llm_api_url: str
    dedup_db_path: Path
    prompt_path: Path


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent

    api_id_raw = os.getenv("API_ID")
    if not api_id_raw:
        raise ValueError("API_ID is required")
    api_id = int(api_id_raw)

    api_hash = os.getenv("API_HASH")
    if not api_hash:
        raise ValueError("API_HASH is required")

    phone = os.getenv("PHONE", "")
    session_name = os.getenv("SESSION_NAME", "user_assistant_session")

    source_chats = _parse_json_str_list("SOURCE_CHATS")
    target_chats = _parse_json_str_list("TARGET_CHATS")
    filter_keywords = _parse_json_str_list("FILTER_KEYWORDS", "[]")

    if not source_chats:
        raise ValueError("SOURCE_CHATS must contain at least one chat/channel")

    dedup_default = str(project_root / "data" / "processed.sqlite3")
    dedup_db_path = Path(os.getenv("DEDUP_DB_PATH", dedup_default))

    prompt_rel = os.getenv("PROMPT_FILE", "prompts/message_analyzer.txt")
    prompt_path = Path(prompt_rel)
    if not prompt_path.is_absolute():
        prompt_path = project_root / prompt_path

    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        session_name=session_name,
        source_chats=source_chats,
        target_chats=target_chats,
        filter_keywords=filter_keywords,
        forward_original=_env_bool("FORWARD_ORIGINAL", False),
        use_llm=_env_bool("USE_LLM", False),
        llm_model=os.getenv("LLM_MODEL", "qwen2.5-coder:14b"),
        llm_api_url=os.getenv(
            "LLM_API_URL",
            "http://localhost:11434/api/generate",
        ),
        dedup_db_path=dedup_db_path,
        prompt_path=prompt_path,
    )
