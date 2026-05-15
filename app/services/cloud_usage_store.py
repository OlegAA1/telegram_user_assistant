"""Daily OpenRouter/cloud request usage counters (SQLite).

Stores only aggregate counters by UTC date. It never stores request text,
responses, API keys, model names, or user identifiers.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class CloudUsageStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_usage (
                usage_date TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL DEFAULT 0
            )
            """,
        )
        self._conn.commit()

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def get_used_today(self) -> int:
        cur = self._conn.execute(
            "SELECT request_count FROM cloud_usage WHERE usage_date = ?",
            (self._today_key(),),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def can_use(self, max_per_day: int) -> bool:
        if max_per_day <= 0:
            return False
        return self.get_used_today() < max_per_day

    def record_request(self) -> None:
        today = self._today_key()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO cloud_usage (usage_date, request_count)
                VALUES (?, 1)
                ON CONFLICT(usage_date)
                DO UPDATE SET request_count = request_count + 1
                """,
                (today,),
            )

    def close(self) -> None:
        self._conn.close()
