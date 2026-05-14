"""Load settings from environment (.env)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SourceKeywordRule:
    """Keywords that apply only to messages from the given source chat/channel."""

    source: str
    keywords: tuple[str, ...]


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


def _parse_source_keyword_rules() -> tuple[SourceKeywordRule, ...]:
    """Optional per-source keyword lists: [{"source":"ch","keywords":["a","b"]}, ...]."""
    raw = os.getenv("SOURCE_KEYWORD_RULES", "").strip()
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SOURCE_KEYWORD_RULES must be valid JSON, got: {raw!r}") from exc
    if not isinstance(value, list):
        raise ValueError("SOURCE_KEYWORD_RULES must be a JSON array of objects")
    rules: list[SourceKeywordRule] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"SOURCE_KEYWORD_RULES[{idx}] must be an object")
        src = item.get("source")
        kws = item.get("keywords")
        if src is None or kws is None:
            raise ValueError(
                f"SOURCE_KEYWORD_RULES[{idx}] must have 'source' and 'keywords' fields",
            )
        src_str = str(src).strip()
        if not src_str:
            raise ValueError(f"SOURCE_KEYWORD_RULES[{idx}].source is empty")
        if isinstance(kws, str):
            kw_list = [kws]
        elif isinstance(kws, list):
            kw_list = []
            for k in kws:
                if isinstance(k, str):
                    kw_list.append(k)
                elif isinstance(k, int):
                    kw_list.append(str(k))
                else:
                    raise ValueError(
                        f"SOURCE_KEYWORD_RULES[{idx}].keywords items must be strings",
                    )
        else:
            raise ValueError(f"SOURCE_KEYWORD_RULES[{idx}].keywords must be a list or string")
        rules.append(
            SourceKeywordRule(source=src_str, keywords=tuple(x.strip() for x in kw_list if x.strip())),
        )
    return tuple(rules)


def _merge_unique_sources(explicit: list[str], rules: tuple[SourceKeywordRule, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for s in explicit + [r.source for r in rules]:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    return merged


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    session_name: str
    # Union of SOURCE_CHATS and sources from SOURCE_KEYWORD_RULES (for Telethon subscription).
    source_chats: list[str]
    # Raw SOURCE_CHATS from .env; FILTER_KEYWORDS apply when no per-source rule matches.
    explicit_source_chats: tuple[str, ...]
    target_chats: list[str]
    filter_keywords: list[str]
    source_keyword_rules: tuple[SourceKeywordRule, ...]
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

    explicit_sources = _parse_json_str_list("SOURCE_CHATS", "[]")
    rules = _parse_source_keyword_rules()
    source_chats = _merge_unique_sources(explicit_sources, rules)
    target_chats = _parse_json_str_list("TARGET_CHATS")
    filter_keywords = _parse_json_str_list("FILTER_KEYWORDS", "[]")

    if not source_chats:
        raise ValueError(
            "Set SOURCE_CHATS and/or SOURCE_KEYWORD_RULES with at least one source chat",
        )

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
        explicit_source_chats=tuple(explicit_sources),
        target_chats=target_chats,
        filter_keywords=filter_keywords,
        source_keyword_rules=rules,
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
