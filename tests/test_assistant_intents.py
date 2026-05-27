import unittest

from app.handlers.assistant_intents import (
    extract_json_object,
    looks_like_command_action_text,
)


class AssistantIntentHelpersTest(unittest.TestCase):
    def test_extracts_json_from_markdown_block(self) -> None:
        raw = '```json\n{"intent":"server_status"}\n```'

        self.assertEqual(extract_json_object(raw), {"intent": "server_status"})

    def test_extracts_first_json_object_from_text(self) -> None:
        raw = 'Ответ: {"intent":"list_reminders"} спасибо'

        self.assertEqual(extract_json_object(raw), {"intent": "list_reminders"})

    def test_command_action_keyword_gate(self) -> None:
        self.assertTrue(looks_like_command_action_text("какая модель сейчас используется?"))
        self.assertFalse(looks_like_command_action_text("объясни asyncio в Python"))


if __name__ == "__main__":
    unittest.main()
