import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


telethon = types.ModuleType("telethon")
telethon_utils = types.ModuleType("telethon.utils")
telethon_utils.get_peer_id = lambda chat: chat.id
telethon.utils = telethon_utils
sys.modules.setdefault("telethon", telethon)
sys.modules.setdefault("telethon.utils", telethon_utils)

dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenv
sys.modules.pop("app.config", None)
sys.modules.pop("app.services.filter_service", None)

from app.config import SourceKeywordRule
from app.services.filter_service import FilterService


class FakeEvent:
    chat_id = -1001

    def __init__(self, text: str) -> None:
        self.raw_text = text

    async def get_chat(self):
        return SimpleNamespace(id=-1001, username=None)


class FilterServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_matching_rules_for_same_source_merge_targets(self) -> None:
        service = FilterService(
            SimpleNamespace(
                filter_keywords=[],
                source_keyword_rules=(
                    SourceKeywordRule(source="-1001", keywords=("testnet",), targets=("-2001",)),
                    SourceKeywordRule(source="-1001", keywords=("airdrop",), targets=("-2002",)),
                ),
                explicit_source_chats=(),
                target_chats=[],
            ),
        )

        with patch("app.services.filter_service.utils.get_peer_id", return_value=-1001):
            match = await service.match(FakeEvent("new testnet airdrop"))

        self.assertIsNotNone(match)
        self.assertEqual(match.targets, ("-2001", "-2002"))


if __name__ == "__main__":
    unittest.main()
