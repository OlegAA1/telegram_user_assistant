"""Store last forwarded/post message per owner for manual scam check."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class PendingPost:
    owner_id: int
    message_id: int
    chat_id: int
    text: str
    forward_title: str | None
    entities_json: str | None
    saved_at: datetime


class PendingPostStore:
    def __init__(self, db_path: Path, *, ttl_minutes: int = 60) -> None:
        self._path = db_path
        self._ttl_seconds = max(1, int(ttl_minutes)) * 60
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_posts (
                owner_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                forward_title TEXT,
                entities_json TEXT,
                saved_at_unix INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def save(
        self,
        *,
        owner_id: int,
        message_id: int,
        chat_id: int,
        text: str,
        forward_title: str | None = None,
        entities_json: str | None = None,
    ) -> None:
        ts = int(time.time())
        self._conn.execute(
            """
            INSERT INTO pending_posts (
                owner_id, message_id, chat_id, text, forward_title, entities_json, saved_at_unix
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                message_id=excluded.message_id,
                chat_id=excluded.chat_id,
                text=excluded.text,
                forward_title=excluded.forward_title,
                entities_json=excluded.entities_json,
                saved_at_unix=excluded.saved_at_unix
            """,
            (owner_id, message_id, chat_id, text, forward_title, entities_json, ts),
        )
        self._conn.commit()

    def get_fresh(self, owner_id: int, *, expected_chat_id: int) -> PendingPost | None:
        row = self._conn.execute(
            """
            SELECT message_id, chat_id, text, forward_title, entities_json, saved_at_unix
            FROM pending_posts WHERE owner_id = ?
            """,
            (owner_id,),
        ).fetchone()
        if not row:
            return None
        message_id, chat_id, text, forward_title, entities_json, saved_at_unix = row
        if int(chat_id) != int(expected_chat_id):
            return None
        saved_at = datetime.fromtimestamp(int(saved_at_unix), tz=timezone.utc)
        age = time.time() - saved_at_unix
        if age > self._ttl_seconds:
            return None
        return PendingPost(
            owner_id=owner_id,
            message_id=int(message_id),
            chat_id=int(chat_id),
            text=str(text or ""),
            forward_title=str(forward_title) if forward_title else None,
            entities_json=str(entities_json) if entities_json else None,
            saved_at=saved_at,
        )

    def close(self) -> None:
        self._conn.close()


def serialize_entities(entities: list | None) -> str | None:
    if not entities:
        return None
    out: list[dict] = []
    for ent in entities:
        item: dict = {"type": type(ent).__name__}
        if hasattr(ent, "url"):
            item["url"] = ent.url
        if hasattr(ent, "offset"):
            item["offset"] = ent.offset
        if hasattr(ent, "length"):
            item["length"] = ent.length
        out.append(item)
    return json.dumps(out, ensure_ascii=False)
