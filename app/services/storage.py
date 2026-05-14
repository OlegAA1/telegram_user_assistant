"""Deduplication: do not process the same (chat_id, message_id) twice."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class ProcessedStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )
        self._conn.commit()

    def is_processed(self, chat_id: int, message_id: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed_messages WHERE chat_id = ? AND message_id = ? LIMIT 1",
            (chat_id, message_id),
        )
        return cur.fetchone() is not None

    def mark_processed(self, chat_id: int, message_id: int) -> None:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO processed_messages (chat_id, message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            logger.exception("Failed to persist processed message %s/%s", chat_id, message_id)

    def close(self) -> None:
        self._conn.close()
