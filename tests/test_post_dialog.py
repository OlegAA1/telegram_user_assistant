import asyncio
import json
import sys
import unittest
from types import SimpleNamespace

# Some older tests replace app.* / telethon modules with hand-made stubs (no __spec__).
for _name in [n for n in sys.modules if n.split(".")[0] in {"app", "telethon"}]:
    if getattr(sys.modules[_name], "__spec__", None) is None:
        del sys.modules[_name]

from app.handlers.post_dialog_handler import post_dialog_predicate  # noqa: E402
from app.services.post_dialog import (  # noqa: E402
    PostDialogService,
    build_context,
    build_prompt,
)


def _msg(text, *, out=False, fwd=False, reply_to=None):
    return SimpleNamespace(message=text, out=out, fwd_from=object() if fwd else None, reply_to_msg_id=reply_to)


def _event(message, *, private=False, sender_id=777):
    return SimpleNamespace(message=message, is_private=private, sender_id=sender_id)


_SETTINGS = SimpleNamespace(ask_sender_ids=frozenset({777}))


class PredicateTest(unittest.TestCase):
    def test_allowed_user_reply_in_group(self) -> None:
        self.assertTrue(post_dialog_predicate(_event(_msg("а нода нужна?", reply_to=5)), _SETTINGS))

    def test_rejects_non_replies_strangers_commands_and_own_answers(self) -> None:
        self.assertFalse(post_dialog_predicate(_event(_msg("вопрос")), _SETTINGS))
        self.assertFalse(post_dialog_predicate(_event(_msg("вопрос", reply_to=5), sender_id=1), _SETTINGS))
        self.assertFalse(post_dialog_predicate(_event(_msg("/testnets", reply_to=5)), _SETTINGS))
        self.assertFalse(post_dialog_predicate(_event(_msg("💬 ответ", out=True, reply_to=5)), _SETTINGS))
        self.assertFalse(
            post_dialog_predicate(_event(_msg("⚠️ Не удалось получить ответ", out=True, reply_to=5)), _SETTINGS),
        )
        self.assertFalse(post_dialog_predicate(_event(_msg("вопрос", reply_to=5), private=True), _SETTINGS))

    def test_owner_writing_from_assistant_account(self) -> None:
        self.assertTrue(post_dialog_predicate(_event(_msg("а сколько стоит?", out=True, reply_to=5)), _SETTINGS))


class ContextTest(unittest.TestCase):
    def test_chain_post_card_and_history(self) -> None:
        chain = [
            _msg("Новый тестнет Monad https://monad.xyz", out=True, fwd=True),
            _msg("🧪 <b>Monad</b> ...\n\n#testnet · /testnet 7", out=True, reply_to=1),
            _msg("а нода нужна?", reply_to=2),
            _msg("💬 Нет, нода не нужна.", out=True, reply_to=3),
        ]
        ctx = build_context(chain, links_of=lambda m: ["https://monad.xyz"])
        self.assertIn("Monad", ctx.post_text)
        self.assertEqual(ctx.post_links, ["https://monad.xyz"])
        self.assertEqual(ctx.card_id, 7)
        self.assertEqual([h.role for h in ctx.history], ["assistant", "user", "assistant"])

        prompt = build_prompt(ctx, "а сколько по времени?", report_json='{"project": "Monad"}')
        self.assertIn("Пост:\nНовый тестнет Monad", prompt)
        self.assertIn("AI-разбор проекта", prompt)
        self.assertIn("Пользователь: а нода нужна?", prompt)
        self.assertTrue(prompt.rstrip().endswith("а сколько по времени?"))


class _FakeStore:
    def get_report_json(self, item_id):
        return json.dumps({"project": "Monad"}) if item_id == 7 else ""


class _FakeSearch:
    def __init__(self):
        self.queries = []

    async def search(self, query, *, time_range=None, max_results=None):
        self.queries.append(query)
        return [{"title": "Monad node guide", "url": "https://x.example", "snippet": "no node needed"}]


class _FakeLLM:
    is_configured = True
    last_error = ""

    def __init__(self):
        self.calls = []

    async def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return "Нода не нужна."


class ServiceTest(unittest.TestCase):
    def test_answer_uses_card_report_and_search(self) -> None:
        settings = SimpleNamespace(
            post_dialog_web_search=True, enable_web_search=True, post_dialog_model="",
            testnet_model="anthropic/claude-haiku-5.5", max_cloud_output_tokens=1000,
        )
        llm, search = _FakeLLM(), _FakeSearch()
        service = PostDialogService(settings, openrouter=llm, search=search, testnets=_FakeStore())
        ctx = build_context(
            [_msg("пост", out=True, fwd=True), _msg("🧪 card /testnet 7", out=True, reply_to=1)],
            links_of=lambda m: [],
        )
        answer = asyncio.run(service.answer(ctx, "нужна нода?"))
        self.assertEqual(answer, "💬 Нода не нужна.")
        self.assertEqual(search.queries, ["Monad нужна нода?"])
        self.assertEqual(llm.calls[0]["model"], "anthropic/claude-haiku-5.5")
        self.assertIn('"project": "Monad"', llm.calls[0]["prompt"])
        self.assertIn("Monad node guide", llm.calls[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
