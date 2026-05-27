import importlib
import sys
import types
import unittest
from unittest.mock import patch


class ConfigAssistantOnlyTest(unittest.TestCase):
    def test_private_assistant_mode_does_not_require_source_chats(self) -> None:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda: None
        sys.modules["dotenv"] = dotenv
        sys.modules.pop("app.config", None)

        with patch.dict(
            "os.environ",
            {
                "API_ID": "123",
                "API_HASH": "hash",
                "ASK_SENDER_IDS": "[777]",
                "SOURCE_CHATS": "[]",
                "TARGET_CHATS": "[]",
                "SUMMARY_CHATS": "[]",
                "SCRIPT_DIGEST_CHATS": "[]",
            },
            clear=True,
        ):
            config = importlib.import_module("app.config")
            settings = config.load_settings()

        self.assertEqual(settings.ask_sender_ids, frozenset({777}))
        self.assertEqual(settings.source_chats, [])


if __name__ == "__main__":
    unittest.main()
