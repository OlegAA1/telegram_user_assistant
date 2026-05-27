import sys
import types
import unittest
from types import SimpleNamespace


config = types.ModuleType("app.config")
config.Settings = object
sys.modules["app.config"] = config

command_actions = types.ModuleType("app.handlers.assistant_command_actions")


async def _command_not_handled(*args, **kwargs):
    return False


command_actions.handle_command_action_intent = _command_not_handled
command_actions.handle_pending_command_confirmation = _command_not_handled
sys.modules["app.handlers.assistant_command_actions"] = command_actions

reminder_actions = types.ModuleType("app.handlers.assistant_reminder_actions")


async def _reminder_not_handled(*args, **kwargs):
    return False


reminder_actions.handle_reminder_action_intent = _reminder_not_handled
reminder_actions.handle_reminder_text_shortcut = _reminder_not_handled
sys.modules["app.handlers.assistant_reminder_actions"] = reminder_actions

llm_service = types.ModuleType("app.services.llm_service")
llm_service.LLMService = object
sys.modules["app.services.llm_service"] = llm_service

llm_router = types.ModuleType("app.services.llm_router")
llm_router.LLMRouter = object
sys.modules["app.services.llm_router"] = llm_router

reminder_store = types.ModuleType("app.services.reminder_store")
reminder_store.ReminderStore = object
sys.modules["app.services.reminder_store"] = reminder_store

reply_context = types.ModuleType("app.services.reply_context")


async def _no_followup(*args, **kwargs):
    return None


reply_context.build_reply_followup_prompt = _no_followup
sys.modules["app.services.reply_context"] = reply_context

sys.modules.pop("app.handlers.owner_ask", None)
from app.handlers.assistant_intents import ACTION_UNCLEAR_REPLY
from app.handlers.owner_ask import handle_owner_ask


class FakeMessage:
    out = False

    def __init__(self, message: str) -> None:
        self.message = message


class FakeEvent:
    is_private = True
    sender_id = 100
    chat_id = 100

    def __init__(self, message: str) -> None:
        self.message = FakeMessage(message)
        self.replies = []

    async def reply(self, text: str) -> None:
        self.replies.append(text)


class FakeLLM:
    async def intent_detection(self, text: str) -> str:
        return "not json"


class FakeRouter:
    def __init__(self) -> None:
        self.local_queries = []

    async def ask_local(self, text: str):
        self.local_queries.append(text)
        return SimpleNamespace(text="local reply", error="")


class OwnerAskTest(unittest.IsolatedAsyncioTestCase):
    async def test_action_like_invalid_intent_does_not_fall_back_to_chat(self) -> None:
        event = FakeEvent("/ask отмени напоминание")
        router = FakeRouter()

        await handle_owner_ask(
            event,
            settings=SimpleNamespace(ask_sender_ids={100}),
            llm=FakeLLM(),
            router=router,
            reminders=object(),
        )

        self.assertEqual(event.replies, [ACTION_UNCLEAR_REPLY])
        self.assertEqual(router.local_queries, [])


if __name__ == "__main__":
    unittest.main()
