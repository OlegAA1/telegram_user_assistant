import sys
import types
import unittest
from types import SimpleNamespace


config = types.ModuleType("app.config")
config.Settings = object
sys.modules.setdefault("app.config", config)

command_actions = types.ModuleType("app.handlers.assistant_command_actions")


async def _command_not_handled(*args, **kwargs):
    return False


command_actions.handle_command_action_intent = _command_not_handled
sys.modules.setdefault("app.handlers.assistant_command_actions", command_actions)

reminder_actions = types.ModuleType("app.handlers.assistant_reminder_actions")


async def _reminder_not_handled(*args, **kwargs):
    return False


reminder_actions.handle_reminder_action_intent = _reminder_not_handled
sys.modules.setdefault("app.handlers.assistant_reminder_actions", reminder_actions)

assistant_system = types.ModuleType("app.prompts.assistant_system")
assistant_system.ASSISTANT_SYSTEM_RU = "system"
assistant_system.SEARCH_SUMMARY_SYSTEM_RU = "search-system"
sys.modules.setdefault("app.prompts.assistant_system", assistant_system)

crypto_service = types.ModuleType("app.services.crypto_price_service")


class CryptoPriceError(Exception):
    def __init__(self, message, *, code="error"):
        super().__init__(message)
        self.message = message
        self.code = code


crypto_service.CryptoPriceError = CryptoPriceError
crypto_service.CryptoPriceService = object
crypto_service.format_crypto_price_reply = lambda data: f"{data['asset']}={data['price']}"
sys.modules.setdefault("app.services.crypto_price_service", crypto_service)

llm_router = types.ModuleType("app.services.llm_router")
llm_router.LLMRouter = object
sys.modules.setdefault("app.services.llm_router", llm_router)

reminder_store = types.ModuleType("app.services.reminder_store")
reminder_store.ReminderStore = object
sys.modules.setdefault("app.services.reminder_store", reminder_store)

web_search = types.ModuleType("app.services.web_search_service")
web_search.WebSearchService = object
sys.modules.setdefault("app.services.web_search_service", web_search)

from app.handlers.assistant_action_router import handle_parsed_assistant_intent


class FakeEvent:
    def __init__(self):
        self.replies = []

    async def reply(self, text):
        self.replies.append(text)


class FakeRouter:
    def __init__(self):
        self.local_queries = []
        self.cloud_queries = []

    async def ask_local(self, text):
        self.local_queries.append(text)
        return SimpleNamespace(text="local reply", error="")

    async def ask_cloud(self, text, *, system=None):
        self.cloud_queries.append((text, system))
        return SimpleNamespace(text="cloud reply", error="")


class FakeSearch:
    async def search(self, query):
        return []


class AssistantActionRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_ask_routes_to_local_model(self):
        event = FakeEvent()
        router = FakeRouter()

        handled = await handle_parsed_assistant_intent(
            event,
            parsed={"intent": "local_ask", "text": "объясни asyncio"},
            user_text="ignored",
            settings=SimpleNamespace(default_crypto_vs_currency="usdt"),
            router=router,
            reminders=object(),
            search=FakeSearch(),
            crypto=object(),
        )

        self.assertTrue(handled)
        self.assertEqual(router.local_queries, ["объясни asyncio"])
        self.assertEqual(event.replies, ["local reply"])

    async def test_crypto_price_missing_asset_is_handled(self):
        event = FakeEvent()

        handled = await handle_parsed_assistant_intent(
            event,
            parsed={"intent": "crypto_price"},
            user_text="цена",
            settings=SimpleNamespace(default_crypto_vs_currency="usdt"),
            router=FakeRouter(),
            reminders=object(),
            search=FakeSearch(),
            crypto=object(),
        )

        self.assertTrue(handled)
        self.assertEqual(event.replies, ["Не понял монету. Примеры: btc, eth, sol, ton, bnb"])

    async def test_web_search_disabled_without_results(self):
        event = FakeEvent()

        handled = await handle_parsed_assistant_intent(
            event,
            parsed={"intent": "web_search", "query": "новости Ethereum"},
            user_text="ignored",
            settings=SimpleNamespace(
                default_crypto_vs_currency="usdt",
                enable_web_search=False,
            ),
            router=FakeRouter(),
            reminders=object(),
            search=FakeSearch(),
            crypto=object(),
        )

        self.assertTrue(handled)
        self.assertEqual(
            event.replies,
            ["Для актуальной информации включи ENABLE_WEB_SEARCH или используй /cloud."],
        )


if __name__ == "__main__":
    unittest.main()
