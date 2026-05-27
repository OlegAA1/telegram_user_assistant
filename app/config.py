"""Load settings from environment (.env)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SourceKeywordRule:
    """Keywords that apply only to messages from the given source chat/channel."""

    source: str
    keywords: tuple[str, ...]
    targets: tuple[str, ...] = ()


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


def _parse_source_keyword_rules_value(value: object, *, source_name: str) -> tuple[SourceKeywordRule, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{source_name} must be a JSON array of objects")
    rules: list[SourceKeywordRule] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{source_name}[{idx}] must be an object")
        src = item.get("source")
        kws = item.get("keywords")
        targets_raw = item.get("targets", item.get("target_chats", []))
        if src is None or kws is None:
            raise ValueError(
                f"{source_name}[{idx}] must have 'source' and 'keywords' fields",
            )
        src_str = str(src).strip()
        if not src_str:
            raise ValueError(f"{source_name}[{idx}].source is empty")
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
                        f"{source_name}[{idx}].keywords items must be strings",
                    )
        else:
            raise ValueError(f"{source_name}[{idx}].keywords must be a list or string")

        if isinstance(targets_raw, str):
            targets_list = [targets_raw]
        elif isinstance(targets_raw, list):
            targets_list = []
            for target in targets_raw:
                if isinstance(target, str):
                    targets_list.append(target)
                elif isinstance(target, int):
                    targets_list.append(str(target))
                else:
                    raise ValueError(
                        f"{source_name}[{idx}].targets items must be strings",
                    )
        else:
            raise ValueError(f"{source_name}[{idx}].targets must be a list or string")
        rules.append(
            SourceKeywordRule(
                source=src_str,
                keywords=tuple(x.strip() for x in kw_list if x.strip()),
                targets=tuple(x.strip() for x in targets_list if x.strip()),
            ),
        )
    return tuple(rules)


def _parse_source_keyword_rules(project_root: Path) -> tuple[SourceKeywordRule, ...]:
    """Optional per-source keyword lists from SOURCE_KEYWORD_RULES or a JSON file."""
    rules_file_raw = os.getenv("SOURCE_KEYWORD_RULES_FILE", "").strip()
    if rules_file_raw:
        rules_path = Path(rules_file_raw)
        if not rules_path.is_absolute():
            rules_path = project_root / rules_path
        if not rules_path.is_file():
            raise ValueError(f"SOURCE_KEYWORD_RULES_FILE does not exist: {rules_path}")
        try:
            value = json.loads(rules_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SOURCE_KEYWORD_RULES_FILE must contain valid JSON array: {rules_path}",
            ) from exc
        return _parse_source_keyword_rules_value(
            value,
            source_name=f"SOURCE_KEYWORD_RULES_FILE({rules_path})",
        )

    raw = os.getenv("SOURCE_KEYWORD_RULES", "").strip()
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SOURCE_KEYWORD_RULES must be valid JSON, got: {raw!r}") from exc
    return _parse_source_keyword_rules_value(value, source_name="SOURCE_KEYWORD_RULES")


def _merge_unique_sources(explicit: list[str], rules: tuple[SourceKeywordRule, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for s in explicit + [r.source for r in rules]:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    return merged


def _parse_ask_sender_ids() -> frozenset[int]:
    """Telegram user ids allowed to use /ask in private (incoming)."""
    out: set[int] = set()
    raw = os.getenv("ASK_SENDER_IDS", "").strip()
    if raw:
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ASK_SENDER_IDS must be valid JSON array, got: {raw!r}") from exc
        if not isinstance(val, list):
            raise ValueError("ASK_SENDER_IDS must be a JSON array")
        for idx, item in enumerate(val):
            if isinstance(item, bool):
                raise ValueError(f"ASK_SENDER_IDS[{idx}] must be an integer user id, not boolean")
            if isinstance(item, int):
                out.add(item)
            elif isinstance(item, str):
                s = item.strip()
                if not re.fullmatch(r"-?\d+", s):
                    raise ValueError(f"ASK_SENDER_IDS[{idx}] must be an integer user id")
                out.add(int(s))
            else:
                raise ValueError(f"ASK_SENDER_IDS[{idx}] must be an integer user id")
    legacy = os.getenv("OWNER_ID", "").strip()
    if legacy:
        if not re.fullmatch(r"-?\d+", legacy):
            raise ValueError("OWNER_ID must be an integer Telegram user id")
        out.add(int(legacy))
    return frozenset(out)


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
    llm_think: bool
    llm_num_ctx: int
    llm_timeout: float
    llm_intent_timeout: float
    llm_analyze_timeout: float
    enable_cloud_fallback: bool
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    openrouter_timeout: float
    max_cloud_requests_per_day: int
    max_cloud_input_chars: int
    max_cloud_output_tokens: int
    log_cloud_usage: bool
    cloud_usage_db_path: Path
    enable_web_search: bool
    web_search_provider: str
    web_search_api_key: str
    web_search_depth: str
    web_search_topic: str
    web_search_time_range: str
    web_search_auto_parameters: bool
    web_search_chunks_per_source: int
    web_search_max_results: int
    web_search_timeout: int
    enable_crypto_price: bool
    binance_base_url: str
    binance_timeout: int
    default_crypto_vs_currency: str
    enable_manual_scam_check: bool
    scam_check_group_id: int | None
    scam_check_auto_on_link: bool
    enable_link_scam_check: bool
    scam_check_max_links: int
    scam_check_max_searches_per_link: int
    scam_check_pending_ttl_minutes: int
    scam_check_use_openrouter: bool
    scam_check_db_path: Path
    dedup_db_path: Path
    prompt_path: Path
    intent_parser_path: Path
    # Incoming private /ask is allowed only from these Telegram user ids (empty = disabled).
    ask_sender_ids: frozenset[int]
    reminder_db_path: Path
    reminder_tz: str
    enable_daily_summary: bool
    summary_chats: list[str]
    summary_target_chat: str
    summary_time: str
    summary_tz: str
    summary_db_path: Path
    summary_retention_days: int
    summary_max_db_mb: int
    summary_store_media: bool
    summary_vacuum_after_cleanup: bool
    summary_max_message_chars: int
    summary_use_cloud_final: bool
    summary_cloud_model: str
    summary_max_cloud_input_chars: int
    summary_max_output_tokens: int
    enable_script_digest: bool
    script_digest_chats: list[str]
    script_digest_target_chat: str
    script_digest_interval_hours: int
    script_digest_tz: str
    script_digest_db_path: Path
    script_digest_retention_days: int
    script_digest_top_limit: int


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
    rules = _parse_source_keyword_rules(project_root)
    source_chats = _merge_unique_sources(explicit_sources, rules)
    target_chats = _parse_json_str_list("TARGET_CHATS")
    filter_keywords = _parse_json_str_list("FILTER_KEYWORDS", "[]")
    summary_chats = _parse_json_str_list("SUMMARY_CHATS", "[]")
    script_digest_chats = _parse_json_str_list("SCRIPT_DIGEST_CHATS", "[]")
    ask_sender_ids = _parse_ask_sender_ids()

    if not source_chats and not summary_chats and not script_digest_chats and not ask_sender_ids:
        raise ValueError(
            "Set ASK_SENDER_IDS for private assistant mode, or set SOURCE_CHATS, "
            "SOURCE_KEYWORD_RULES, SUMMARY_CHATS, or SCRIPT_DIGEST_CHATS with at least one chat",
        )

    dedup_default = str(project_root / "data" / "processed.sqlite3")
    dedup_db_path = Path(os.getenv("DEDUP_DB_PATH", dedup_default))

    prompt_rel = os.getenv("PROMPT_FILE", "prompts/message_analyzer.txt")
    prompt_path = Path(prompt_rel)
    if not prompt_path.is_absolute():
        prompt_path = project_root / prompt_path

    intent_rel = os.getenv("INTENT_PARSER_PROMPT", "prompts/intent_parser.txt")
    intent_parser_path = Path(intent_rel)
    if not intent_parser_path.is_absolute():
        intent_parser_path = project_root / intent_parser_path

    reminder_default = str(project_root / "data" / "reminders.sqlite3")
    reminder_db_path = Path(os.getenv("REMINDER_DB_PATH", reminder_default))
    reminder_tz = os.getenv("REMINDER_TZ", "Europe/Moscow").strip() or "Europe/Moscow"
    try:
        ZoneInfo(reminder_tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Invalid REMINDER_TZ={reminder_tz!r} (use IANA name, e.g. Europe/Moscow)",
        ) from exc

    summary_tz = os.getenv("SUMMARY_TZ", reminder_tz).strip() or reminder_tz
    try:
        ZoneInfo(summary_tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Invalid SUMMARY_TZ={summary_tz!r} (use IANA name, e.g. Europe/Moscow)",
        ) from exc

    summary_default = str(project_root / "data" / "chat_summaries.sqlite3")
    summary_db_path = Path(os.getenv("SUMMARY_DB_PATH", summary_default))

    script_digest_tz = os.getenv("SCRIPT_DIGEST_TZ", summary_tz).strip() or summary_tz
    try:
        ZoneInfo(script_digest_tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Invalid SCRIPT_DIGEST_TZ={script_digest_tz!r} (use IANA name, e.g. Europe/Moscow)",
        ) from exc

    script_digest_default = str(project_root / "data" / "script_runs.sqlite3")
    script_digest_db_path = Path(os.getenv("SCRIPT_DIGEST_DB_PATH", script_digest_default))

    cloud_usage_default = str(project_root / "data" / "cloud_usage.sqlite3")
    cloud_usage_db_path = Path(os.getenv("CLOUD_USAGE_DB_PATH", cloud_usage_default))

    scam_check_default = str(project_root / "data" / "pending_posts.sqlite3")
    scam_check_db_path = Path(os.getenv("SCAM_CHECK_DB_PATH", scam_check_default))

    scam_group_raw = os.getenv("SCAM_CHECK_GROUP_ID", "").strip()
    scam_check_group_id: int | None = None
    if scam_group_raw:
        if not re.fullmatch(r"-?\d+", scam_group_raw):
            raise ValueError("SCAM_CHECK_GROUP_ID must be an integer Telegram chat id (e.g. -100...)")
        scam_check_group_id = int(scam_group_raw)

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
        llm_model=os.getenv("LLM_MODEL", "qwen3.5-ru-assistant"),
        llm_api_url=os.getenv(
            "LLM_API_URL",
            "http://localhost:11434/api/generate",
        ),
        llm_think=_env_bool("LLM_THINK", False),
        llm_num_ctx=int(os.getenv("LLM_NUM_CTX", "32768")),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        llm_intent_timeout=float(os.getenv("LLM_INTENT_TIMEOUT", "20")),
        llm_analyze_timeout=float(os.getenv("LLM_ANALYZE_TIMEOUT", "300")),
        enable_cloud_fallback=_env_bool("ENABLE_CLOUD_FALLBACK", False),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", ""),
        openrouter_timeout=float(os.getenv("OPENROUTER_TIMEOUT", "60")),
        max_cloud_requests_per_day=int(os.getenv("MAX_CLOUD_REQUESTS_PER_DAY", "30")),
        max_cloud_input_chars=int(os.getenv("MAX_CLOUD_INPUT_CHARS", "12000")),
        max_cloud_output_tokens=int(os.getenv("MAX_CLOUD_OUTPUT_TOKENS", "1000")),
        log_cloud_usage=_env_bool("LOG_CLOUD_USAGE", True),
        cloud_usage_db_path=cloud_usage_db_path,
        enable_web_search=_env_bool("ENABLE_WEB_SEARCH", False),
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", ""),
        web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", ""),
        web_search_depth=os.getenv("WEB_SEARCH_DEPTH", "advanced").strip().lower() or "advanced",
        web_search_topic=os.getenv("WEB_SEARCH_TOPIC", "general").strip().lower() or "general",
        web_search_time_range=os.getenv("WEB_SEARCH_TIME_RANGE", "month").strip().lower(),
        web_search_auto_parameters=_env_bool("WEB_SEARCH_AUTO_PARAMETERS", True),
        web_search_chunks_per_source=int(os.getenv("WEB_SEARCH_CHUNKS_PER_SOURCE", "3")),
        web_search_max_results=int(os.getenv("WEB_SEARCH_MAX_RESULTS", "8")),
        web_search_timeout=int(os.getenv("WEB_SEARCH_TIMEOUT", "30")),
        enable_crypto_price=_env_bool("ENABLE_CRYPTO_PRICE", True),
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        binance_timeout=int(os.getenv("BINANCE_TIMEOUT", "30")),
        default_crypto_vs_currency=(
            os.getenv("DEFAULT_CRYPTO_VS_CURRENCY", "usdt").strip().lower() or "usdt"
        ),
        enable_manual_scam_check=_env_bool("ENABLE_MANUAL_SCAM_CHECK", True),
        scam_check_group_id=scam_check_group_id,
        scam_check_auto_on_link=_env_bool("SCAM_CHECK_AUTO_ON_LINK", True),
        enable_link_scam_check=_env_bool("ENABLE_LINK_SCAM_CHECK", False),
        scam_check_max_links=int(os.getenv("SCAM_CHECK_MAX_LINKS", "5")),
        scam_check_max_searches_per_link=int(os.getenv("SCAM_CHECK_MAX_SEARCHES_PER_LINK", "2")),
        scam_check_pending_ttl_minutes=int(os.getenv("SCAM_CHECK_PENDING_TTL_MINUTES", "60")),
        scam_check_use_openrouter=_env_bool("SCAM_CHECK_USE_OPENROUTER", True),
        scam_check_db_path=scam_check_db_path,
        dedup_db_path=dedup_db_path,
        prompt_path=prompt_path,
        intent_parser_path=intent_parser_path,
        ask_sender_ids=ask_sender_ids,
        reminder_db_path=reminder_db_path,
        reminder_tz=reminder_tz,
        enable_daily_summary=_env_bool("ENABLE_DAILY_SUMMARY", False),
        summary_chats=summary_chats,
        summary_target_chat=os.getenv("SUMMARY_TARGET_CHAT", "me").strip() or "me",
        summary_time=os.getenv("SUMMARY_TIME", "21:00").strip() or "21:00",
        summary_tz=summary_tz,
        summary_db_path=summary_db_path,
        summary_retention_days=int(os.getenv("SUMMARY_RETENTION_DAYS", "7")),
        summary_max_db_mb=int(os.getenv("SUMMARY_MAX_DB_MB", "500")),
        summary_store_media=_env_bool("SUMMARY_STORE_MEDIA", False),
        summary_vacuum_after_cleanup=_env_bool("SUMMARY_VACUUM_AFTER_CLEANUP", True),
        summary_max_message_chars=int(os.getenv("SUMMARY_MAX_MESSAGE_CHARS", "4000")),
        summary_use_cloud_final=_env_bool("SUMMARY_USE_CLOUD_FINAL", True),
        summary_cloud_model=os.getenv("SUMMARY_CLOUD_MODEL", "openai/gpt-4.1-mini").strip(),
        summary_max_cloud_input_chars=int(os.getenv("SUMMARY_MAX_CLOUD_INPUT_CHARS", "30000")),
        summary_max_output_tokens=int(os.getenv("SUMMARY_MAX_OUTPUT_TOKENS", "1800")),
        enable_script_digest=_env_bool("ENABLE_SCRIPT_DIGEST", False),
        script_digest_chats=script_digest_chats,
        script_digest_target_chat=os.getenv("SCRIPT_DIGEST_TARGET_CHAT", "").strip(),
        script_digest_interval_hours=int(os.getenv("SCRIPT_DIGEST_INTERVAL_HOURS", "12")),
        script_digest_tz=script_digest_tz,
        script_digest_db_path=script_digest_db_path,
        script_digest_retention_days=int(os.getenv("SCRIPT_DIGEST_RETENTION_DAYS", "30")),
        script_digest_top_limit=int(os.getenv("SCRIPT_DIGEST_TOP_LIMIT", "10")),
    )
