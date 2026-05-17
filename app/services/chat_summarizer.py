"""Daily chat summarization pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.daily_summary_store import SummaryMessage
from app.services.llm_service import LLMService
from app.services.openrouter_service import OpenRouterService


@dataclass(frozen=True)
class SummaryResult:
    text: str
    memory_text: str
    used_cloud: bool


class ChatSummarizer:
    def __init__(self, *, settings: Settings, local: LLMService, openrouter: OpenRouterService) -> None:
        self._settings = settings
        self._local = local
        self._openrouter = openrouter

    async def summarize(
        self,
        *,
        chat_title: str,
        chat_username: str,
        period_start: datetime,
        period_end: datetime,
        messages: list[SummaryMessage],
        previous_memory: str,
    ) -> SummaryResult:
        if not messages:
            text = self._format_empty_summary(chat_title, period_start, period_end)
            return SummaryResult(text=text, memory_text=previous_memory, used_cloud=False)

        chunks = self._chunk_messages(messages)
        chunk_summaries: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            prompt = self._chunk_prompt(
                chat_title=chat_title,
                period_start=period_start,
                period_end=period_end,
                chunk_index=idx,
                chunk_count=len(chunks),
                text=chunk,
            )
            out = await self._local.generate_prompt(prompt)
            chunk_summaries.append(out or "Локальная модель не вернула summary для этого фрагмента.")

        draft_prompt = self._final_prompt(
            chat_title=chat_title,
            chat_username=chat_username,
            period_start=period_start,
            period_end=period_end,
            message_count=len(messages),
            previous_memory=previous_memory,
            chunk_summaries=chunk_summaries,
        )
        used_cloud = False
        final = ""
        if self._settings.summary_use_cloud_final:
            final = await self._openrouter.generate(
                draft_prompt,
                system=(
                    "Ты аналитик чатов. Пиши по-русски, кратко, конкретно, без выдумок. "
                    "Если существенных событий нет, так и напиши."
                ),
                model=self._settings.summary_cloud_model,
                max_tokens=self._settings.summary_max_output_tokens,
                max_input_chars=self._settings.summary_max_cloud_input_chars,
            )
            used_cloud = bool(final)

        if not final:
            final = await self._local.generate_prompt(draft_prompt)
        if not final:
            final = self._fallback_summary(chat_title, period_start, period_end, len(messages), chunk_summaries)

        memory_text = await self._update_memory(
            chat_title=chat_title,
            previous_memory=previous_memory,
            daily_summary=final,
        )
        return SummaryResult(text=final.strip(), memory_text=memory_text, used_cloud=used_cloud)

    def _chunk_messages(self, messages: list[SummaryMessage]) -> list[str]:
        max_chars = 12000
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for msg in messages:
            line = self._format_message(msg)
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                chunks.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len
        if current:
            chunks.append("\n".join(current))
        return chunks

    def _format_message(self, msg: SummaryMessage) -> str:
        tz = ZoneInfo(self._settings.summary_tz)
        ts = msg.message_date.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        sender = msg.sender_name or (str(msg.sender_id) if msg.sender_id else "unknown")
        media = " [media]" if msg.has_media else ""
        text = msg.text.strip() or "[без текста]"
        return f"[{ts}] {sender}{media}: {text}"

    def _chunk_prompt(
        self,
        *,
        chat_title: str,
        period_start: datetime,
        period_end: datetime,
        chunk_index: int,
        chunk_count: int,
        text: str,
    ) -> str:
        period = self._period_line(period_start, period_end)
        return (
            "Ты делаешь промежуточную выжимку фрагмента Telegram-чата.\n"
            "Верни только структурированный русский текст, без вступлений.\n"
            "Вытащи: главное, решения, задачи, вопросы без ответа, ссылки/ресурсы, важные имена и даты.\n"
            "Не выдумывай. Если в блоке нет важных событий, напиши: Существенных событий не было.\n\n"
            f"Чат: {chat_title}\n"
            f"Период: {period}\n"
            f"Фрагмент: {chunk_index}/{chunk_count}\n\n"
            f"Сообщения:\n{text}\n"
        )

    def _final_prompt(
        self,
        *,
        chat_title: str,
        chat_username: str,
        period_start: datetime,
        period_end: datetime,
        message_count: int,
        previous_memory: str,
        chunk_summaries: list[str],
    ) -> str:
        username = f"@{chat_username}" if chat_username else "-"
        chunks_text = "\n\n---\n\n".join(chunk_summaries)
        return (
            "Собери финальную ежедневную выжимку Telegram-чата на русском.\n"
            "Формат строго такой:\n\n"
            f"Выжимка: {chat_title}\n"
            f"Период: {self._period_line(period_start, period_end)}\n"
            f"Сообщений: {message_count}\n\n"
            "Главное:\n"
            "- ...\n\n"
            "Решения:\n"
            "- ...\n\n"
            "Задачи:\n"
            "- ...\n\n"
            "Вопросы без ответа:\n"
            "- ...\n\n"
            "Ссылки:\n"
            "- ...\n\n"
            "Если по разделу ничего нет, напиши '- нет'. "
            "Если за период нет существенных событий, в разделе Главное напиши '- Существенных событий не было.'\n"
            "Не добавляй фактов, которых нет в промежуточных выжимках.\n\n"
            f"Чат: {chat_title}\n"
            f"Username: {username}\n"
            f"Предыдущая память чата:\n{previous_memory or 'пока нет'}\n\n"
            f"Промежуточные выжимки:\n{chunks_text}\n"
        )

    async def _update_memory(self, *, chat_title: str, previous_memory: str, daily_summary: str) -> str:
        prompt = (
            "Обнови долговременную память Telegram-чата на русском.\n"
            "Оставь только устойчиво важное: участники/роли, текущие проекты, открытые вопросы, "
            "договоренности, предпочтения. Максимум 1500 символов. Не включай одноразовый шум.\n\n"
            f"Чат: {chat_title}\n\n"
            f"Предыдущая память:\n{previous_memory or 'пока нет'}\n\n"
            f"Новая дневная выжимка:\n{daily_summary}\n"
        )
        updated = await self._local.generate_prompt(prompt)
        return (updated or previous_memory or "").strip()[:2000]

    def _fallback_summary(
        self,
        chat_title: str,
        period_start: datetime,
        period_end: datetime,
        message_count: int,
        chunk_summaries: list[str],
    ) -> str:
        body = "\n\n".join(chunk_summaries).strip() or "Существенных событий не было."
        return (
            f"Выжимка: {chat_title}\n"
            f"Период: {self._period_line(period_start, period_end)}\n"
            f"Сообщений: {message_count}\n\n"
            f"Главное:\n{body}"
        )

    def _format_empty_summary(self, chat_title: str, period_start: datetime, period_end: datetime) -> str:
        return (
            f"Выжимка: {chat_title}\n"
            f"Период: {self._period_line(period_start, period_end)}\n"
            "Сообщений: 0\n\n"
            "Главное:\n"
            "- Существенных событий не было.\n\n"
            "Решения:\n"
            "- нет\n\n"
            "Задачи:\n"
            "- нет\n\n"
            "Вопросы без ответа:\n"
            "- нет\n\n"
            "Ссылки:\n"
            "- нет"
        )

    def _period_line(self, start: datetime, end: datetime) -> str:
        tz = ZoneInfo(self._settings.summary_tz)
        start_s = start.astimezone(tz).strftime("%d.%m %H:%M")
        end_s = end.astimezone(tz).strftime("%d.%m %H:%M")
        return f"{start_s} - {end_s} {self._settings.summary_tz}"
