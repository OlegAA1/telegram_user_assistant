"""Shared assistant system prompts and help text (single source of truth)."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_prompt_file(name: str) -> str:
    path = _PROJECT_ROOT / "prompts" / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_capabilities_text() -> str:
    return _load_prompt_file("assistant_capabilities.txt")


def build_assistant_system_ru() -> str:
    capabilities = get_capabilities_text()
    return (
        "Ты Telegram AI assistant. Всегда отвечай пользователю на русском языке, "
        "если он явно не попросил другой язык. Будь кратким и полезным.\n\n"
        "Доступные возможности (не выдумывай функции вне списка):\n"
        f"{capabilities}\n\n"
        "Если спрашивают, что ты умеешь — отвечай строго по списку выше. "
        "Для полной памятки посоветуй команду ?."
    )


def build_help_reply() -> str:
    capabilities = get_capabilities_text()
    return (
        "Доступные команды:\n\n"
        "**?** — показать эту памятку\n"
        f"{capabilities}\n\n"
        "Напоминания (подробнее):\n"
        "**/remind** `2026-05-21 18:30 текст`\n"
        "**/remind** `in 45m текст`\n"
        "**/remind** `list`\n"
        "**/remind** `history`\n"
        "**/remind** `cancel ID`\n\n"
        "Обычный текст без команды:\n"
        "напомни мне в 23:30 открыть сайт — напоминание\n"
        "покажи напоминания / покажи историю напоминаний / отмени #12 — управление напоминаниями\n"
        "цена биткоина / сколько стоит eth — Binance\n"
        "что сегодня с Ethereum в новостях? — веб-поиск\n"
        "проверь здоровье / доступна ли Ollama — healthcheck\n"
        "как сервер? / какая модель? / покажи каналы — служебные действия\n"
        "подпишись на @channel — подписка аккаунта на канал\n"
        "напиши код для Telethon — локальная Qwen\n\n"
        "Проверка поста на scam (только в группе SCAM_CHECK_GROUP_ID):\n"
        "1) перешли пост в эту группу\n"
        "2) напиши там: проверь пост или **/check**"
    )


ASSISTANT_SYSTEM_RU = build_assistant_system_ru()
HELP_REPLY = build_help_reply()

SEARCH_SUMMARY_SYSTEM_RU = (
    "Ты помощник в Telegram. Отвечай на русском языке строго по результатам веб-поиска. "
    "Сначала оцени свежесть и надежность источников: предпочитай официальные сайты, документацию, "
    "релизные заметки и материалы с явной датой публикации. Если запрос про текущую ситуацию, "
    "считай устаревшие источники слабым сигналом и не называй их данные актуальными без подтверждения. "
    "Если источники конфликтуют или дат не хватает, прямо скажи об ограничении. "
    "Укажи важные даты и 2-4 источника. Не выдумывай данные вне найденных результатов."
)
