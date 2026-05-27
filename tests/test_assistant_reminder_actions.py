import sys
import types
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace


dateparser = types.ModuleType("dateparser")
dateparser.parse = lambda *args, **kwargs: None
sys.modules.setdefault("dateparser", dateparser)

config = types.ModuleType("app.config")
config.Settings = object
sys.modules.setdefault("app.config", config)

reminder_store = types.ModuleType("app.services.reminder_store")
reminder_store.ReminderStore = object
sys.modules.setdefault("app.services.reminder_store", reminder_store)

sys.modules.pop("app.handlers.assistant_reminder_actions", None)
from app.handlers.assistant_reminder_actions import (
    _normalize_ru_colloquial_time,
    handle_reminder_text_shortcut,
)


class FakeEvent:
    sender_id = 100
    chat_id = 100

    def __init__(self) -> None:
        self.replies = []

    async def reply(self, text: str) -> None:
        self.replies.append(text)


class FakeReminderStore:
    def __init__(self, pending):
        self._pending = list(pending)
        self.cancelled = []

    def list_pending(self, user_id: int):
        return list(self._pending)

    def cancel(self, user_id: int, reminder_id: int) -> bool:
        self.cancelled.append((user_id, reminder_id))
        before = len(self._pending)
        self._pending = [row for row in self._pending if row[0] != reminder_id]
        return len(self._pending) < before


class AssistantReminderActionsTest(unittest.TestCase):
    def test_normalizes_today_three_in_the_afternoon(self) -> None:
        self.assertEqual(
            _normalize_ru_colloquial_time("в 3 дня сегодня"),
            "сегодня в 15:00",
        )

    def test_normalizes_daytime_phrase_with_hour_word(self) -> None:
        self.assertEqual(
            _normalize_ru_colloquial_time("сегодня в 3 часа дня"),
            "сегодня в 15:00",
        )

    def test_keeps_relative_three_days(self) -> None:
        self.assertEqual(
            _normalize_ru_colloquial_time("через 3 дня"),
            "через 3 дня",
        )

    def test_normalizes_midnight_phrase(self) -> None:
        self.assertEqual(
            _normalize_ru_colloquial_time("в 12 ночи завтра"),
            "завтра в 00:00",
        )


class AssistantReminderShortcutTest(unittest.IsolatedAsyncioTestCase):
    async def test_implicit_cancel_single_pending_reminder(self) -> None:
        event = FakeEvent()
        store = FakeReminderStore(
            [(3, "забрать пиццу", datetime(2026, 5, 30, 11, 22, tzinfo=timezone.utc))],
        )

        handled = await handle_reminder_text_shortcut(
            event,
            user_text="отмени его",
            settings=SimpleNamespace(reminder_tz="Europe/Moscow"),
            reminders=store,
        )

        self.assertTrue(handled)
        self.assertEqual(store.cancelled, [(100, 3)])
        self.assertEqual(event.replies, ["Ок, отменил напоминание #3: забрать пиццу"])

    async def test_implicit_cancel_asks_for_id_when_multiple_pending(self) -> None:
        event = FakeEvent()
        store = FakeReminderStore(
            [
                (3, "забрать пиццу", datetime(2026, 5, 30, 11, 22, tzinfo=timezone.utc)),
                (4, "позвонить", datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)),
            ],
        )

        handled = await handle_reminder_text_shortcut(
            event,
            user_text="отмени его",
            settings=SimpleNamespace(reminder_tz="Europe/Moscow"),
            reminders=store,
        )

        self.assertTrue(handled)
        self.assertEqual(store.cancelled, [])
        self.assertIn("несколько активных напоминаний", event.replies[0])


if __name__ == "__main__":
    unittest.main()
