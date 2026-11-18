"""SQLite storage for analyzed testnet / activity posts."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


def project_key(name: str) -> str:
    """Normalized project name used for de-duplication ("Monad Testnet" -> "monad")."""
    s = (name or "").lower()
    s = re.sub(r"\b(testnet|devnet|incentivized|incentivised|mainnet|network|protocol|labs?)\b", " ", s)
    s = re.sub(r"[^a-z0-9а-яё]+", "", s)
    return s


@dataclass(frozen=True)
class StoredTestnet:
    id: int
    name: str
    domain: str
    score: int | None
    verdict: str
    card: str
    created_at_unix: int


class TestnetStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS testnet_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_key TEXT NOT NULL,
                name TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT '',
                score INTEGER,
                verdict TEXT NOT NULL DEFAULT '',
                card TEXT NOT NULL,
                report_json TEXT NOT NULL DEFAULT '',
                source_chat_id INTEGER,
                source_message_id INTEGER,
                created_at_unix INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_testnet_projects_key ON testnet_projects(project_key);
            CREATE INDEX IF NOT EXISTS idx_testnet_projects_domain ON testnet_projects(domain);

            CREATE TABLE IF NOT EXISTS testnet_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                created_at_unix INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- processed messages -------------------------------------------------

    def is_message_processed(self, chat_id: int, message_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM testnet_messages WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ).fetchone()
        return row is not None

    def mark_message_processed(self, chat_id: int, message_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO testnet_messages(chat_id, message_id, created_at_unix) VALUES (?, ?, ?)",
            (chat_id, message_id, int(time.time())),
        )
        self._conn.commit()

    # --- projects -----------------------------------------------------------

    def save(
        self,
        *,
        name: str,
        domain: str,
        score: int | None,
        verdict: str,
        card: str,
        report_json: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
        now_unix: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO testnet_projects(
                project_key, name, domain, score, verdict, card, report_json,
                source_chat_id, source_message_id, created_at_unix
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_key(name),
                name,
                (domain or "").lower(),
                score,
                verdict,
                card,
                report_json,
                source_chat_id,
                source_message_id,
                int(now_unix if now_unix is not None else time.time()),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def find_recent_by_domain(self, domain: str, *, since_unix: int) -> StoredTestnet | None:
        if not domain:
            return None
        return self._one(
            "WHERE domain = ? AND created_at_unix >= ? ORDER BY created_at_unix DESC, id DESC LIMIT 1",
            (domain.lower(), since_unix),
        )

    def find_recent_by_name(self, name: str, *, since_unix: int) -> StoredTestnet | None:
        key = project_key(name)
        if not key:
            return None
        return self._one(
            "WHERE project_key = ? AND created_at_unix >= ? ORDER BY created_at_unix DESC, id DESC LIMIT 1",
            (key, since_unix),
        )

    def get(self, query: str) -> StoredTestnet | None:
        """Find by numeric id (#12 / 12) or by name / domain substring (latest match)."""
        q = (query or "").strip().lstrip("#")
        if not q:
            return None
        if q.isdigit():
            found = self._one("WHERE id = ?", (int(q),))
            if found:
                return found
        like = f"%{q.lower()}%"
        key_like = f"%{project_key(q) or q.lower()}%"
        return self._one(
            "WHERE lower(name) LIKE ? OR domain LIKE ? OR project_key LIKE ? "
            "ORDER BY created_at_unix DESC, id DESC LIMIT 1",
            (like, like, key_like),
        )

    def get_report_json(self, item_id: int) -> str:
        row = self._conn.execute(
            "SELECT report_json FROM testnet_projects WHERE id = ?",
            (int(item_id),),
        ).fetchone()
        return str(row[0] or "") if row else ""

    def list_recent(self, limit: int = 15) -> list[StoredTestnet]:
        rows = self._conn.execute(
            f"SELECT {self._COLUMNS} FROM testnet_projects ORDER BY created_at_unix DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [self._row(r) for r in rows]

    _COLUMNS = "id, name, domain, score, verdict, card, created_at_unix"

    def _one(self, where: str, params: tuple) -> StoredTestnet | None:
        row = self._conn.execute(
            f"SELECT {self._COLUMNS} FROM testnet_projects {where}",
            params,
        ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row) -> StoredTestnet:
        return StoredTestnet(
            id=int(row[0]),
            name=str(row[1]),
            domain=str(row[2] or ""),
            score=None if row[3] is None else int(row[3]),
            verdict=str(row[4] or ""),
            card=str(row[5] or ""),
            created_at_unix=int(row[6]),
        )
