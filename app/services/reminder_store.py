"""Persistent reminders (SQLite)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass(frozen=True)
class ReminderRow:
    id: int
    user_id: int
    chat_id: int
    body: str


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
                fire_at_unix INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_fire ON reminders(fire_at_unix)",
        )
        self._conn.commit()

    def add(self, user_id: int, chat_id: int, body: str, fire_at: datetime) -> int:
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
        ts = int(fire_at.astimezone(timezone.utc).timestamp())
        cur = self._conn.execute(
            "INSERT INTO reminders (user_id, chat_id, body, fire_at_unix) VALUES (?, ?, ?, ?)",
            (user_id, chat_id, body, ts),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def fetch_due(self, now: datetime) -> list[ReminderRow]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        ts = int(now.astimezone(timezone.utc).timestamp())
        cur = self._conn.execute(
            "SELECT id, user_id, chat_id, body FROM reminders WHERE fire_at_unix <= ? ORDER BY fire_at_unix",
            (ts,),
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
            WHERE user_id = ? ORDER BY fire_at_unix LIMIT ?
            """,
            (user_id, limit),
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

    def cancel(self, user_id: int, reminder_id: int) -> bool:
        cur = self._conn.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
