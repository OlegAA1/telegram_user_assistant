import unittest
import sys
import types
from types import SimpleNamespace


aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientError = Exception
aiohttp.ClientTimeout = lambda total=None: None
sys.modules.setdefault("aiohttp", aiohttp)

from app.services.llm_router import LLMRouter


class FakeOpenRouter:
    is_configured = True

    def __init__(self) -> None:
        self.calls = []

    async def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return "ok"

    def usage_status(self) -> str:
        return "used today `0/30`, remaining `30`"


class FakePath:
    def __init__(self, text: str) -> None:
        self.text = text

    def is_file(self) -> bool:
        return True

    def read_text(self, encoding: str) -> str:
        return self.text


class LLMRouterOpenRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_methods_use_openrouter(self) -> None:
        openrouter = FakeOpenRouter()
        router = LLMRouter(
            settings=SimpleNamespace(
                prompt_path=FakePath("analysis prompt"),
                intent_parser_path=FakePath("intent prompt"),
                enable_web_search=False,
                enable_crypto_price=True,
                openrouter_model="openai/gpt-4o-mini",
                web_search_provider="",
                default_crypto_vs_currency="usdt",
            ),
            openrouter=openrouter,
        )

        await router.ask("hello")
        await router.analyze("source text")
        await router.generate_prompt("long prompt")
        await router.intent_detection("напомни завтра")

        self.assertEqual(len(openrouter.calls), 4)
        self.assertEqual(openrouter.calls[0][0], "hello")
        self.assertIn("analysis prompt", openrouter.calls[1][0])
        self.assertEqual(openrouter.calls[2][0], "long prompt")
        self.assertIn("intent prompt", openrouter.calls[3][0])


if __name__ == "__main__":
    unittest.main()
