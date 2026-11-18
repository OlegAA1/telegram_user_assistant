import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Some older tests replace app.* / telethon modules with hand-made stubs at import time
# (types.ModuleType -> no __spec__). Drop those so this test imports the real modules.
for _name in [n for n in sys.modules if n.split(".")[0] in {"app", "telethon"}]:
    if getattr(sys.modules[_name], "__spec__", None) is None:
        del sys.modules[_name]

from app.handlers.testnet_handler import is_own_card  # noqa: E402
from app.services.testnet_analyzer import (
    MAX_CARD_CHARS,
    TestnetAnalyzer,
    base_domain,
    classify_link,
    format_card,
    html_to_text,
    name_hint,
    parse_report,
    pick_extract_urls,
    primary_domain,
)
from app.services.testnet_store import TestnetStore, project_key

_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "testnet_analysis.txt"

_REPORT = {
    "relevant": True,
    "project": "Monad",
    "category": "L1",
    "activity_type": "тестнет",
    "summary": "EVM-совместимый L1. Нужно взять токены в кране и сделать свапы.",
    "funding": "$225M",
    "investors": ["Paradigm"],
    "token": "нет",
    "requirements": {"socials": ["X", "Discord"], "wallets": ["EVM (MetaMask/Rabby)"], "other": []},
    "steps": ["Взять токены: https://faucet.monad.xyz", "Сделать свап <b>"],
    "links": {"site": "https://monad.xyz", "x": "https://x.com/monad_xyz", "discord": "javascript:alert(1)"},
    "cost": "0$",
    "time": "~10 минут в день",
    "deadline": "",
    "risks": ["Фейковые краны"],
    "score": 8,
    "verdict": "делать",
    "verdict_reason": "Крупные инвесторы, токена нет.",
}


class LinkHelpersTest(unittest.TestCase):
    def test_classify(self) -> None:
        self.assertEqual(classify_link("https://x.com/monad_xyz"), "x")
        self.assertEqual(classify_link("https://twitter.com/monad_xyz"), "x")
        self.assertEqual(classify_link("https://discord.gg/abc"), "discord")
        self.assertEqual(classify_link("https://t.me/monad"), "telegram")
        self.assertEqual(classify_link("https://app.galxe.com/quest/x"), "tasks")
        self.assertEqual(classify_link("https://faucet.monad.xyz"), "faucet")
        self.assertEqual(classify_link("https://docs.monad.xyz/guide"), "docs")
        self.assertEqual(classify_link("https://monad.xyz"), "site")
        self.assertEqual(classify_link("https://linktr.ee/monad"), "other")

    def test_base_and_primary_domain(self) -> None:
        self.assertEqual(base_domain("https://testnet.monad.xyz/path"), "monad.xyz")
        self.assertEqual(base_domain("https://proj.gitbook.io/docs"), "proj.gitbook.io")
        self.assertEqual(base_domain("https://www.example.co.uk"), "example.co.uk")
        links = ["https://x.com/monad_xyz", "https://t.me/monad", "https://testnet.monad.xyz"]
        self.assertEqual(primary_domain(links), "monad.xyz")
        self.assertEqual(primary_domain(["https://x.com/a", "https://discord.gg/b"]), "")

    def test_name_hint(self) -> None:
        self.assertEqual(name_hint(["https://app.monad.xyz"]), "monad")
        self.assertEqual(name_hint(["https://x.com/somechain", "https://t.me/a"]), "somechain")
        self.assertEqual(name_hint(["https://t.me/a"]), "")

    def test_pick_extract_urls_prioritizes_site(self) -> None:
        links = ["https://x.com/a", "https://app.galxe.com/q", "https://docs.a.xyz", "https://a.xyz"]
        self.assertEqual(pick_extract_urls(links, 2), ["https://a.xyz", "https://docs.a.xyz"])


class ReportFormattingTest(unittest.TestCase):
    def test_parse_report_with_fences(self) -> None:
        raw = "```json\n" + json.dumps(_REPORT, ensure_ascii=False) + "\n```"
        self.assertEqual(parse_report(raw)["project"], "Monad")
        self.assertIsNone(parse_report("не json"))

    def test_card_escapes_and_contains_sections(self) -> None:
        card = format_card(_REPORT, source="Testnet Hub", source_url="https://t.me/hub/5")
        self.assertTrue(card.startswith("🧪 <b>Monad</b>"))
        self.assertIn("Соцсети: X, Discord", card)
        self.assertIn("1. Взять токены", card)
        self.assertIn("&lt;b&gt;", card)  # LLM text is escaped
        self.assertNotIn("javascript:", card)  # only http(s) links are shown
        self.assertIn("8/10", card)
        self.assertIn('<a href="https://t.me/hub/5">Testnet Hub</a>', card)

    def test_card_fits_telegram_limit(self) -> None:
        big = dict(_REPORT, steps=["шаг " + "x" * 290] * 10, risks=["r" * 300] * 6, summary="s" * 700)
        self.assertLessEqual(len(format_card(big)), MAX_CARD_CHARS)

    def test_html_to_text(self) -> None:
        text = html_to_text(
            "<html><head><title>Proj</title><meta name=\"description\" content=\"Fast L1\">"
            "<script>var a=1;</script></head><body><h1>Hello</h1></body></html>",
        )
        self.assertIn("Title: Proj", text)
        self.assertIn("Description: Fast L1", text)
        self.assertIn("Hello", text)
        self.assertNotIn("var a", text)


class TestnetStoreTest(unittest.TestCase):
    def test_save_find_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TestnetStore(Path(tmp) / "t.sqlite3")
            try:
                self.assertFalse(store.is_message_processed(1, 2))
                store.mark_message_processed(1, 2)
                self.assertTrue(store.is_message_processed(1, 2))

                item_id = store.save(
                    name="Monad Testnet", domain="Monad.xyz", score=8, verdict="делать",
                    card="card", report_json="{}", now_unix=1_000_000,
                )
                self.assertEqual(project_key("Monad Testnet"), "monad")
                self.assertEqual(store.find_recent_by_domain("monad.xyz", since_unix=0).id, item_id)
                self.assertIsNone(store.find_recent_by_domain("monad.xyz", since_unix=2_000_000))
                self.assertEqual(store.find_recent_by_name("monad", since_unix=0).id, item_id)
                self.assertEqual(store.get(f"#{item_id}").name, "Monad Testnet")
                self.assertEqual(store.get("mona").id, item_id)
                self.assertEqual(len(store.list_recent()), 1)
            finally:
                store.close()


class _FakeSearch:
    can_extract = True

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.extracted: list[str] = []

    async def extract(self, urls):
        self.extracted = list(urls)
        return {u: "Monad is a high-performance EVM L1." for u in urls}

    async def search(self, query, *, time_range=None, max_results=None):
        self.queries.append(query)
        return [{"title": "Monad raises $225M", "url": "https://news.example/m", "snippet": "Paradigm led"}]


class _FakeOpenRouter:
    is_configured = True
    last_error = ""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    async def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.reply


def _settings(**overrides):
    base = dict(
        testnet_prompt_path=_PROMPT,
        testnet_model="anthropic/claude-sonnet-4.5",
        testnet_max_links=8,
        testnet_max_pages=2,
        testnet_max_page_chars=5000,
        testnet_max_searches=2,
        testnet_max_input_chars=30000,
        testnet_max_output_tokens=2000,
        testnet_direct_fetch=False,
        enable_web_search=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestnetAnalyzerTest(unittest.TestCase):
    def test_full_pipeline(self) -> None:
        search = _FakeSearch()
        llm = _FakeOpenRouter(json.dumps(_REPORT, ensure_ascii=False))
        analyzer = TestnetAnalyzer(_settings(), search=search, openrouter=llm)
        links = ["https://x.com/monad_xyz", "https://testnet.monad.xyz", "https://faucet.monad.xyz"]

        result = asyncio.run(analyzer.analyze("Новый тестнет Monad!", links, source="Hub"))

        self.assertTrue(result.relevant)
        self.assertEqual(result.name, "Monad")
        self.assertEqual(result.domain, "monad.xyz")
        self.assertEqual(result.score, 8)
        self.assertEqual(result.verdict, "делать")
        self.assertIn("🧪 <b>Monad</b>", result.card)
        self.assertEqual(search.extracted, ["https://testnet.monad.xyz", "https://faucet.monad.xyz"])
        self.assertEqual(len(search.queries), 2)
        self.assertTrue(all(q.startswith("monad ") for q in search.queries))
        call = llm.calls[0]
        self.assertEqual(call["model"], "anthropic/claude-sonnet-4.5")
        self.assertIn("Monad is a high-performance EVM L1.", call["prompt"])
        self.assertIn("Monad raises $225M", call["prompt"])
        self.assertIn("[x] https://x.com/monad_xyz", call["prompt"])

    def test_irrelevant_post(self) -> None:
        llm = _FakeOpenRouter('{"relevant": false, "project": ""}')
        analyzer = TestnetAnalyzer(_settings(enable_web_search=False), search=_FakeSearch(), openrouter=llm)
        result = asyncio.run(analyzer.analyze("BTC пробил 100k", []))
        self.assertFalse(result.relevant)

    def test_llm_error_is_reported(self) -> None:
        llm = _FakeOpenRouter("")
        llm.last_error = "Дневной лимит cloud-запросов исчерпан."
        analyzer = TestnetAnalyzer(_settings(), search=_FakeSearch(), openrouter=llm)
        result = asyncio.run(analyzer.analyze("Тестнет", ["https://a.xyz"]))
        self.assertIn("лимит", result.error)


class OwnCardTest(unittest.TestCase):
    def test_skips_only_own_cards(self) -> None:
        self.assertTrue(is_own_card(SimpleNamespace(out=True, fwd_from=None, message="🧪 Разбираю пост…")))
        self.assertFalse(is_own_card(SimpleNamespace(out=True, fwd_from=object(), message="🧪 forwarded")))
        self.assertFalse(is_own_card(SimpleNamespace(out=False, fwd_from=None, message="🧪 from user")))


if __name__ == "__main__":
    unittest.main()
