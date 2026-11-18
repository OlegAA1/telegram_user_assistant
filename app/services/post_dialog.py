"""Follow-up dialog under a post: replies to a forwarded post / testnet card / previous answer."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.config import Settings
from app.services.openrouter_service import OpenRouterService
from app.services.testnet_analyzer import CARD_PREFIX, DUPLICATE_PREFIX, name_hint
from app.services.testnet_store import TestnetStore
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)

ANSWER_PREFIX = "💬"
ERROR_PREFIX = "⚠️ Не удалось"
BOT_PREFIXES = (ANSWER_PREFIX, CARD_PREFIX, DUPLICATE_PREFIX, ERROR_PREFIX)
_CARD_ID_RE = re.compile(r"/testnet\s+(\d+)")
MAX_ANSWER_CHARS = 3900

SYSTEM_PROMPT = (
    "Ты помощник по крипто-активностям (тестнеты, ноды, квесты, дропы) в Telegram. "
    "Пользователь ведёт диалог реплаями под конкретным постом и задаёт уточняющие вопросы. "
    "Отвечай на русском, кратко и по делу, опираясь на пост, AI-разбор проекта, историю диалога "
    "и результаты веб-поиска. Не выдумывай факты (инвестиции, даты, ссылки): если данных нет — "
    "так и скажи и подскажи, где проверить. Пошаговые инструкции — нумерованным списком. "
    "Никогда не советуй вводить seed-фразу или приватный ключ и подписывать непонятные транзакции."
)


@dataclass
class ChainMessage:
    role: str  # "post" | "user" | "assistant"
    text: str


@dataclass
class DialogContext:
    post_text: str = ""
    post_links: list[str] = field(default_factory=list)
    history: list[ChainMessage] = field(default_factory=list)  # oldest first, without the post
    card_id: int | None = None


def is_bot_text(text: str) -> bool:
    return (text or "").lstrip().startswith(BOT_PREFIXES)


def classify(message, *, is_root: bool) -> ChainMessage:
    text = (getattr(message, "message", None) or "").strip()
    if getattr(message, "out", False) and getattr(message, "fwd_from", None) is None and is_bot_text(text):
        return ChainMessage("assistant", text)
    if is_root or getattr(message, "fwd_from", None) is not None:
        return ChainMessage("post", text)
    return ChainMessage("user", text)


def build_context(chain: list, *, links_of) -> DialogContext:
    """chain: messages from the root post to the message the user replied to (oldest first)."""
    ctx = DialogContext()
    for i, msg in enumerate(chain):
        item = classify(msg, is_root=(i == 0))
        if item.role == "post" and not ctx.post_text:
            ctx.post_text = item.text
            ctx.post_links = links_of(msg)
            continue
        if item.role == "assistant" and ctx.card_id is None:
            m = _CARD_ID_RE.search(item.text)
            if m:
                ctx.card_id = int(m.group(1))
        if item.text:
            ctx.history.append(item)
    return ctx


def build_prompt(
    ctx: DialogContext,
    question: str,
    *,
    report_json: str = "",
    search_notes: list[str] | None = None,
    max_chars: int = 30000,
) -> str:
    parts = ["Пост:\n" + (ctx.post_text[:6000] or "(без текста)")]
    if ctx.post_links:
        parts.append("Ссылки поста:\n" + "\n".join(f"- {u}" for u in ctx.post_links[:15]))
    if report_json:
        parts.append("AI-разбор проекта (JSON):\n" + report_json[:8000])
    if ctx.history:
        lines = []
        for item in ctx.history[-10:]:
            who = "Ассистент" if item.role == "assistant" else "Пользователь"
            lines.append(f"{who}: {item.text[:2500]}")
        parts.append("История диалога:\n" + "\n\n".join(lines))
    if search_notes:
        parts.append("Результаты веб-поиска по вопросу:\n" + "\n".join(search_notes)[:6000])
    parts.append("Новый вопрос пользователя:\n" + question.strip())
    prompt = "\n\n".join(parts)
    if len(prompt) > max_chars:  # keep the question, trim the oldest context
        prompt = prompt[-max_chars:]
    return prompt


class PostDialogService:
    def __init__(
        self,
        settings: Settings,
        *,
        openrouter: OpenRouterService,
        search: WebSearchService,
        testnets: TestnetStore | None,
    ) -> None:
        self._settings = settings
        self._openrouter = openrouter
        self._search = search
        self._testnets = testnets

    async def answer(self, ctx: DialogContext, question: str) -> str:
        if not self._openrouter.is_configured:
            return f"{ERROR_PREFIX} получить ответ: OpenRouter не настроен (OPENROUTER_API_KEY / OPENROUTER_MODEL)."

        report_json = ""
        if ctx.card_id is not None and self._testnets is not None:
            report_json = self._testnets.get_report_json(ctx.card_id)

        notes = await self._search_notes(ctx, question, report_json)
        prompt = build_prompt(ctx, question, report_json=report_json, search_notes=notes)
        s = self._settings
        out = await self._openrouter.generate(
            prompt,
            system=SYSTEM_PROMPT,
            model=s.post_dialog_model or s.testnet_model or None,
            max_tokens=max(s.max_cloud_output_tokens, 1500),
            max_input_chars=31000,
        )
        if not out:
            return f"{ERROR_PREFIX} получить ответ: {self._openrouter.last_error or 'пустой ответ модели'}"
        text = f"{ANSWER_PREFIX} {out.strip()}"
        return text[:MAX_ANSWER_CHARS]

    async def _search_notes(self, ctx: DialogContext, question: str, report_json: str) -> list[str]:
        s = self._settings
        if not (s.post_dialog_web_search and s.enable_web_search):
            return []
        project = ""
        if report_json:
            try:
                project = str(json.loads(report_json).get("project") or "")
            except (ValueError, AttributeError):
                project = ""
        project = project or name_hint(ctx.post_links)
        if not project:
            return []
        query = f"{project} {question}".strip()[:300]
        results = await self._search.search(query, time_range="year", max_results=5)
        return [
            f"- {r.get('title', '')} ({r.get('url', '')}): {(r.get('snippet') or '')[:400]}"
            for r in results[:5]
        ]
