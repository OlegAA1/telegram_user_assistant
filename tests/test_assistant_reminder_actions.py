import sys
import types
import unittest


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
from app.handlers.assistant_reminder_actions import _normalize_ru_colloquial_time


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


if __name__ == "__main__":
    unittest.main()
