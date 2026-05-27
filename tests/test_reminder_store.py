import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.modules.pop("app.services.reminder_store", None)
from app.services.reminder_store import STATUS_CANCELLED, STATUS_FIRED, ReminderStore


class ReminderStoreTest(unittest.TestCase):
    def test_cancel_keeps_history_and_removes_from_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ReminderStore(Path(tmp) / "reminders.sqlite3")
            try:
                fire_at = datetime.now(timezone.utc) + timedelta(hours=1)
                rid = store.add(100, 200, "проверить сервер", fire_at)

                self.assertEqual(len(store.list_pending(100)), 1)
                self.assertTrue(store.cancel(100, rid))

                self.assertEqual(store.list_pending(100), [])
                history = store.list_history(100)
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0].id, rid)
                self.assertEqual(history[0].status, STATUS_CANCELLED)
            finally:
                store.close()

    def test_mark_fired_keeps_history_and_removes_from_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ReminderStore(Path(tmp) / "reminders.sqlite3")
            try:
                fire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                rid = store.add(100, 200, "сработать", fire_at)

                due = store.fetch_due(datetime.now(timezone.utc))
                self.assertEqual([row.id for row in due], [rid])
                self.assertTrue(store.mark_fired(rid))

                self.assertEqual(store.fetch_due(datetime.now(timezone.utc)), [])
                history = store.list_history(100)
                self.assertEqual(history[0].status, STATUS_FIRED)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
