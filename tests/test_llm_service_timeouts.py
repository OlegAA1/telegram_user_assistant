import sys
import types
import unittest
from types import SimpleNamespace


aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientError = Exception
aiohttp.ContentTypeError = Exception


class ClientTimeout:
    def __init__(self, total=None):
        self.total = total


aiohttp.ClientTimeout = ClientTimeout
sys.modules.setdefault("aiohttp", aiohttp)

config = types.ModuleType("app.config")
config.Settings = object
sys.modules.setdefault("app.config", config)

assistant_system = types.ModuleType("app.prompts.assistant_system")
assistant_system.ASSISTANT_SYSTEM_RU = "system"
sys.modules.setdefault("app.prompts.assistant_system", assistant_system)

from app.services.llm_service import LLMService


class LLMServiceTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_methods_use_configured_timeout_profiles(self) -> None:
        service = LLMService(
            SimpleNamespace(
                llm_timeout=120,
                llm_intent_timeout=20,
                llm_analyze_timeout=300,
                intent_parser_path=SimpleNamespace(
                    is_file=lambda: True,
                    read_text=lambda encoding: "intent prompt",
                ),
            )
        )
        seen = []

        async def fake_generate(prompt, *, timeout_seconds=None):
            seen.append(timeout_seconds)
            return "ok"

        service._generate = fake_generate  # type: ignore[method-assign]

        await service.generate_plain("hello")
        await service.intent_detection("напомни завтра")
        await service.generate_prompt("long prompt")

        self.assertEqual(seen, [120, 20, 300])


if __name__ == "__main__":
    unittest.main()
