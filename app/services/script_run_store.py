"""SQLite storage and reports for structured script run messages."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.script_run_parser import ScriptRun


@dataclass(frozen=True)
class StoredScriptRun:
    status: str
    script_name: str
    action: str
    profile_number: int
    wallet: str
    message_date: datetime


class ScriptRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path: Path = settings.script_digest_db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS script_runs (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                chat_title TEXT NOT NULL,
                status TEXT NOT NULL,
                script_name TEXT NOT NULL,
                action TEXT NOT NULL,
                profile_number INTEGER NOT NULL,
                wallet TEXT NOT NULL,
                script_created_at_unix INTEGER,
                message_date_unix INTEGER NOT NULL,
                created_at_unix INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_script_runs_date
            ON script_runs(message_date_unix);

            CREATE INDEX IF NOT EXISTS idx_script_runs_status_profile
            ON script_runs(status, profile_number);

            CREATE TABLE IF NOT EXISTS script_digest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_start_unix INTEGER NOT NULL,
                period_end_unix INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at_unix INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_script_digest_runs_status_end
            ON script_digest_runs(status, period_end_unix);
            """
        )
        self._conn.commit()

    @staticmethod
    def _to_ts(dt: datetime | None) -> int | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.astimezone(timezone.utc).timestamp())

    @staticmethod
    def _from_ts(ts: int) -> datetime:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)

    def save_run(
        self,
        *,
        chat_id: int,
        chat_title: str,
        message_id: int,
        message_date: datetime,
        run: ScriptRun,
    ) -> None:
        now_ts = self._to_ts(datetime.now(timezone.utc))
        self._conn.execute(
            """
            INSERT OR IGNORE INTO script_runs (
                chat_id, message_id, chat_title, status, script_name, action,
                profile_number, wallet, script_created_at_unix, message_date_unix, created_at_unix
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                chat_title,
                run.status,
                run.script_name,
                run.action,
                run.profile_number,
                run.wallet,
                self._to_ts(run.script_created_at),
                self._to_ts(message_date),
                now_ts,
            ),
        )
        self._conn.commit()

    def latest_success_end(self) -> datetime | None:
        cur = self._conn.execute(
            """
            SELECT period_end_unix FROM script_digest_runs
            WHERE status = 'success'
            ORDER BY period_end_unix DESC LIMIT 1
            """,
        )
        row = cur.fetchone()
        return self._from_ts(int(row[0])) if row else None

    def fetch_runs(self, start: datetime, end: datetime) -> list[StoredScriptRun]:
        cur = self._conn.execute(
            """
            SELECT status, script_name, action, profile_number, wallet, message_date_unix
            FROM script_runs
            WHERE message_date_unix > ? AND message_date_unix <= ?
            ORDER BY message_date_unix
            """,
            (self._to_ts(start), self._to_ts(end)),
        )
        return [
            StoredScriptRun(
                status=str(row[0]),
                script_name=str(row[1]),
                action=str(row[2]),
                profile_number=int(row[3]),
                wallet=str(row[4]),
                message_date=self._from_ts(int(row[5])),
            )
            for row in cur.fetchall()
        ]

    def record_digest_run(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        status: str,
        error: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO script_digest_runs (
                period_start_unix, period_end_unix, status, error, created_at_unix
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                self._to_ts(period_start),
                self._to_ts(period_end),
                status,
                error[:1000],
                self._to_ts(datetime.now(timezone.utc)),
            ),
        )
        self._conn.commit()

    def cleanup(self) -> None:
        retention_days = max(1, self._settings.script_digest_retention_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_ts = self._to_ts(cutoff)
        with self._conn:
            self._conn.execute("DELETE FROM script_runs WHERE message_date_unix < ?", (cutoff_ts,))
            self._conn.execute(
                "DELETE FROM script_digest_runs WHERE created_at_unix < ? AND status != 'success'",
                (cutoff_ts,),
            )

    def build_report(self, *, start: datetime, end: datetime) -> str:
        runs = self.fetch_runs(start, end)
        tz = ZoneInfo(self._settings.script_digest_tz)
        start_s = start.astimezone(tz).strftime("%d.%m %H:%M")
        end_s = end.astimezone(tz).strftime("%d.%m %H:%M")
        period_line = f"{start_s} - {end_s} {self._settings.script_digest_tz}"

        total = len(runs)
        ok_count = sum(1 for run in runs if run.status == "OK")
        error_runs = [run for run in runs if run.status == "ERROR"]
        error_count = len(error_runs)
        error_rate = (error_count / total * 100) if total else 0
        top_limit = max(1, self._settings.script_digest_top_limit)

        lines = [
            "Отчет по скриптам",
            f"Период: {period_line}",
            f"Всего запусков: {total}",
            f"OK: {ok_count}",
            f"ERROR: {error_count}",
            f"Error rate: {error_rate:.0f}%",
            "",
        ]

        if not runs:
            lines.append("За период не найдено сообщений скриптов.")
            return "\n".join(lines)

        profile_errors = Counter(run.profile_number for run in error_runs)
        profile_wallets: dict[int, str] = {}
        profile_details: dict[int, Counter[tuple[str, str]]] = defaultdict(Counter)
        for run in error_runs:
            profile_wallets[run.profile_number] = run.wallet
            profile_details[run.profile_number][(run.script_name, run.action)] += 1

        lines.append("Проблемные профили:")
        if profile_errors:
            for idx, (profile, count) in enumerate(profile_errors.most_common(top_limit), start=1):
                wallet = profile_wallets.get(profile, "-")
                lines.append(f"{idx}. #{profile} — {count} ошибок, кошелек {wallet}")
                for (script, action), detail_count in profile_details[profile].most_common(3):
                    lines.append(f"   - {script} / {action}: {detail_count}")
        else:
            lines.append("- нет ошибок")
        lines.append("")

        script_totals = Counter(run.script_name for run in runs)
        script_errors = Counter(run.script_name for run in error_runs)
        lines.append("Проблемные скрипты:")
        if script_errors:
            for script, count in script_errors.most_common(top_limit):
                script_total = script_totals[script]
                pct = count / script_total * 100 if script_total else 0
                lines.append(f"- {script}: {count}/{script_total} ошибок ({pct:.0f}%)")
        else:
            lines.append("- нет ошибок")
        lines.append("")

        combo_errors = Counter(
            (run.profile_number, run.script_name, run.action)
            for run in error_runs
        )
        lines.append("Что проверить:")
        if combo_errors:
            for (profile, script, action), count in combo_errors.most_common(top_limit):
                lines.append(f"- #{profile}: {script} / {action} — {count} ошибок")
        else:
            lines.append("- ничего срочного")

        return "\n".join(lines)

    def close(self) -> None:
        self._conn.close()
