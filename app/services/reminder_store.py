"""Persistent reminders (SQLite)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"
STATUS_FIRED = "fired"


@dataclass(frozen=True)
class ReminderRow:
    id: int
    user_id: int
    chat_id: int
    body: str


@dataclass(frozen=True)
class ReminderHistoryRow:
    id: int
    body: str
    fire_at: datetime
    status: str


class ReminderStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                fire_at_unix INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at_unix INTEGER,
                updated_at_unix INTEGER,
                cancelled_at_unix INTEGER,
                fired_at_unix INTEGER
            )
            """
        )
        self._migrate()
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_fire ON reminders(fire_at_unix)",
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_user_status_fire ON reminders(user_id, status, fire_at_unix)",
        )
        self._conn.commit()

    def _migrate(self) -> None:
        columns = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        migrations = {
            "status": "ALTER TABLE reminders ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "created_at_unix": "ALTER TABLE reminders ADD COLUMN created_at_unix INTEGER",
            "updated_at_unix": "ALTER TABLE reminders ADD COLUMN updated_at_unix INTEGER",
            "cancelled_at_unix": "ALTER TABLE reminders ADD COLUMN cancelled_at_unix INTEGER",
            "fired_at_unix": "ALTER TABLE reminders ADD COLUMN fired_at_unix INTEGER",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self._conn.execute(sql)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        self._conn.execute(
            "UPDATE reminders SET status = ? WHERE status IS NULL OR status = ''",
            (STATUS_ACTIVE,),
        )
        self._conn.execute(
            "UPDATE reminders SET created_at_unix = fire_at_unix WHERE created_at_unix IS NULL",
        )
        self._conn.execute(
            "UPDATE reminders SET updated_at_unix = ? WHERE updated_at_unix IS NULL",
            (now_ts,),
        )

    def add(self, user_id: int, chat_id: int, body: str, fire_at: datetime) -> int:
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
        ts = int(fire_at.astimezone(timezone.utc).timestamp())
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cur = self._conn.execute(
            """
            INSERT INTO reminders
                (user_id, chat_id, body, fire_at_unix, status, created_at_unix, updated_at_unix)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, body, ts, STATUS_ACTIVE, now_ts, now_ts),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def fetch_due(self, now: datetime) -> list[ReminderRow]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        ts = int(now.astimezone(timezone.utc).timestamp())
        cur = self._conn.execute(
            """
            SELECT id, user_id, chat_id, body FROM reminders
            WHERE status = ? AND fire_at_unix <= ?
            ORDER BY fire_at_unix
            """,
            (STATUS_ACTIVE, ts),
        )
        rows = cur.fetchall()
        return [ReminderRow(id=r[0], user_id=r[1], chat_id=r[2], body=r[3]) for r in rows]

    def delete_reminder(self, reminder_id: int) -> None:
        self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._conn.commit()

    def list_pending(self, user_id: int, limit: int = 20) -> list[tuple[int, str, datetime]]:
        cur = self._conn.execute(
            """
            SELECT id, body, fire_at_unix FROM reminders
            WHERE user_id = ? AND status = ?
            ORDER BY fire_at_unix LIMIT ?
            """,
            (user_id, STATUS_ACTIVE, limit),
        )
        out: list[tuple[int, str, datetime]] = []
        for rid, body, fts in cur.fetchall():
            out.append(
                (
                    int(rid),
                    str(body),
                    datetime.fromtimestamp(int(fts), tz=timezone.utc),
                ),
            )
        return out

    def list_history(self, user_id: int, limit: int = 20) -> list[ReminderHistoryRow]:
        cur = self._conn.execute(
            """
            SELECT id, body, fire_at_unix, status FROM reminders
            WHERE user_id = ?
            ORDER BY COALESCE(updated_at_unix, fire_at_unix) DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [
            ReminderHistoryRow(
                id=int(rid),
                body=str(body),
                fire_at=datetime.fromtimestamp(int(fts), tz=timezone.utc),
                status=str(status),
            )
            for rid, body, fts, status in cur.fetchall()
        ]

    def cancel(self, user_id: int, reminder_id: int) -> bool:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cur = self._conn.execute(
            """
            UPDATE reminders
            SET status = ?, cancelled_at_unix = ?, updated_at_unix = ?
            WHERE id = ? AND user_id = ? AND status = ?
            """,
            (STATUS_CANCELLED, now_ts, now_ts, reminder_id, user_id, STATUS_ACTIVE),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def mark_fired(self, reminder_id: int) -> bool:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cur = self._conn.execute(
            """
            UPDATE reminders
            SET status = ?, fired_at_unix = ?, updated_at_unix = ?
            WHERE id = ? AND status = ?
            """,
            (STATUS_FIRED, now_ts, now_ts, reminder_id, STATUS_ACTIVE),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
