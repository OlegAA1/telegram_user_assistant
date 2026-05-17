"""SQLite storage for daily chat summaries and short-lived raw messages."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryMessage:
    chat_id: int
    chat_title: str
    chat_username: str
    message_id: int
    message_date: datetime
    sender_id: int | None
    sender_name: str
    text: str
    has_media: bool


class DailySummaryStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = settings.summary_db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS summary_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                chat_title TEXT NOT NULL,
                chat_username TEXT NOT NULL DEFAULT '',
                sender_id INTEGER,
                sender_name TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                has_media INTEGER NOT NULL DEFAULT 0,
                message_date_unix INTEGER NOT NULL,
                created_at_unix INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_summary_messages_chat_date
            ON summary_messages(chat_id, message_date_unix);

            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT NOT NULL,
                chat_username TEXT NOT NULL DEFAULT '',
                period_start_unix INTEGER NOT NULL,
                period_end_unix INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                used_cloud INTEGER NOT NULL DEFAULT 0,
                created_at_unix INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_daily_summaries_chat_period
            ON daily_summaries(chat_id, period_end_unix);

            CREATE TABLE IF NOT EXISTS chat_memory (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT NOT NULL,
                chat_username TEXT NOT NULL DEFAULT '',
                memory_text TEXT NOT NULL,
                updated_at_unix INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS summary_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                period_start_unix INTEGER NOT NULL,
                period_end_unix INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at_unix INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_summary_runs_chat_status
            ON summary_runs(chat_id, status, period_end_unix);
            """
        )
        self._conn.commit()

    @staticmethod
    def _to_ts(dt: datetime) -> int:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.astimezone(timezone.utc).timestamp())

    @staticmethod
    def _from_ts(ts: int) -> datetime:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)

    def save_message(
        self,
        *,
        chat_id: int,
        chat_title: str,
        chat_username: str,
        message_id: int,
        message_date: datetime,
        sender_id: int | None,
        sender_name: str,
        text: str,
        has_media: bool,
    ) -> None:
        max_chars = max(0, self._settings.summary_max_message_chars)
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n[truncated]"
        if not text and not has_media:
            return

        now_ts = self._to_ts(datetime.now(timezone.utc))
        try:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO summary_messages (
                    chat_id, message_id, chat_title, chat_username, sender_id,
                    sender_name, text, has_media, message_date_unix, created_at_unix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    chat_title,
                    chat_username,
                    sender_id,
                    sender_name,
                    text,
                    1 if has_media else 0,
                    self._to_ts(message_date),
                    now_ts,
                ),
            )
            self._conn.commit()
        except sqlite3.Error:
            logger.exception("Failed to save summary message %s/%s", chat_id, message_id)

    def fetch_messages(self, chat_id: int, start: datetime, end: datetime) -> list[SummaryMessage]:
        cur = self._conn.execute(
            """
            SELECT chat_id, chat_title, chat_username, message_id, message_date_unix,
                   sender_id, sender_name, text, has_media
            FROM summary_messages
            WHERE chat_id = ? AND message_date_unix > ? AND message_date_unix <= ?
            ORDER BY message_date_unix, message_id
            """,
            (chat_id, self._to_ts(start), self._to_ts(end)),
        )
        out: list[SummaryMessage] = []
        for row in cur.fetchall():
            out.append(
                SummaryMessage(
                    chat_id=int(row[0]),
                    chat_title=str(row[1]),
                    chat_username=str(row[2] or ""),
                    message_id=int(row[3]),
                    message_date=self._from_ts(int(row[4])),
                    sender_id=int(row[5]) if row[5] is not None else None,
                    sender_name=str(row[6] or ""),
                    text=str(row[7] or ""),
                    has_media=bool(row[8]),
                ),
            )
        return out

    def latest_success_end(self, chat_id: int) -> datetime | None:
        cur = self._conn.execute(
            """
            SELECT period_end_unix FROM summary_runs
            WHERE chat_id = ? AND status = 'success'
            ORDER BY period_end_unix DESC LIMIT 1
            """,
            (chat_id,),
        )
        row = cur.fetchone()
        return self._from_ts(int(row[0])) if row else None

    def latest_any_success_end(self) -> datetime | None:
        cur = self._conn.execute(
            """
            SELECT period_end_unix FROM summary_runs
            WHERE status = 'success'
            ORDER BY period_end_unix DESC LIMIT 1
            """,
        )
        row = cur.fetchone()
        return self._from_ts(int(row[0])) if row else None

    def get_memory(self, chat_id: int) -> str:
        cur = self._conn.execute(
            "SELECT memory_text FROM chat_memory WHERE chat_id = ?",
            (chat_id,),
        )
        row = cur.fetchone()
        return str(row[0] or "") if row else ""

    def save_summary(
        self,
        *,
        chat_id: int,
        chat_title: str,
        chat_username: str,
        period_start: datetime,
        period_end: datetime,
        message_count: int,
        summary_text: str,
        memory_text: str,
        used_cloud: bool,
    ) -> None:
        now_ts = self._to_ts(datetime.now(timezone.utc))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO daily_summaries (
                    chat_id, chat_title, chat_username, period_start_unix,
                    period_end_unix, message_count, summary_text, used_cloud, created_at_unix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    chat_title,
                    chat_username,
                    self._to_ts(period_start),
                    self._to_ts(period_end),
                    message_count,
                    summary_text,
                    1 if used_cloud else 0,
                    now_ts,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO chat_memory (
                    chat_id, chat_title, chat_username, memory_text, updated_at_unix
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    chat_title = excluded.chat_title,
                    chat_username = excluded.chat_username,
                    memory_text = excluded.memory_text,
                    updated_at_unix = excluded.updated_at_unix
                """,
                (chat_id, chat_title, chat_username, memory_text, now_ts),
            )

    def record_run(
        self,
        *,
        chat_id: int,
        period_start: datetime,
        period_end: datetime,
        status: str,
        error: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO summary_runs (
                chat_id, period_start_unix, period_end_unix, status, error, created_at_unix
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                self._to_ts(period_start),
                self._to_ts(period_end),
                status,
                error[:1000],
                self._to_ts(datetime.now(timezone.utc)),
            ),
        )
        self._conn.commit()

    def cleanup(self) -> None:
        retention_days = max(1, self._settings.summary_retention_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_ts = self._to_ts(cutoff)
        with self._conn:
            self._conn.execute(
                "DELETE FROM summary_messages WHERE message_date_unix < ?",
                (cutoff_ts,),
            )
            self._conn.execute(
                "DELETE FROM summary_runs WHERE created_at_unix < ? AND status != 'success'",
                (cutoff_ts,),
            )

        self._enforce_max_size()
        if self._settings.summary_vacuum_after_cleanup:
            try:
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                logger.exception("Failed to VACUUM summary database")

    def _enforce_max_size(self) -> None:
        max_mb = self._settings.summary_max_db_mb
        if max_mb <= 0 or not self._path.exists():
            return
        if self._path.stat().st_size <= max_mb * 1024 * 1024:
            return

        for days in (3, 1):
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            with self._conn:
                self._conn.execute(
                    "DELETE FROM summary_messages WHERE message_date_unix < ?",
                    (self._to_ts(cutoff),),
                )
            if self._path.stat().st_size <= max_mb * 1024 * 1024:
                return

        with self._conn:
            self._conn.execute(
                """
                DELETE FROM summary_messages
                WHERE rowid NOT IN (
                    SELECT rowid FROM summary_messages
                    ORDER BY message_date_unix DESC
                    LIMIT 5000
                )
                """,
            )

    def close(self) -> None:
        self._conn.close()
