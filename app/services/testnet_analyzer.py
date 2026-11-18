"""AI analysis of testnet / airdrop activity posts.

Pipeline: links from the post -> page texts (Tavily Extract) -> web search about the
project -> LLM (OpenRouter, any model) returns JSON -> formatted Telegram card (HTML).
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from app.config import Settings
from app.services.openrouter_service import OpenRouterService
from app.services.web_search_service import WebSearchService

logger = logging.getLogger(__name__)

CARD_PREFIX = "🧪"
DUPLICATE_PREFIX = "♻️"
MAX_CARD_CHARS = 3900

# --- link classification -----------------------------------------------------

_SOCIAL_HOSTS: dict[str, tuple[str, ...]] = {
    "x": ("x.com", "twitter.com"),
    "discord": ("discord.gg", "discord.com", "discordapp.com"),
    "telegram": ("t.me", "telegram.me"),
    "github": ("github.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "medium": ("medium.com", "mirror.xyz", "substack.com", "paragraph.xyz", "paragraph.com"),
    "tasks": (
        "galxe.com", "app.galxe.com", "zealy.io", "layer3.xyz", "guild.xyz", "intract.io",
        "questn.com", "taskon.xyz", "quest3.xyz", "deform.cc", "gleam.io", "crew3.xyz",
        "wallchain.xyz", "kaito.ai",
    ),
}
# Hosting/aggregator platforms: the full host identifies the project, not the base domain.
_PLATFORM_SUFFIXES = (
    "gitbook.io", "notion.site", "vercel.app", "netlify.app", "github.io", "pages.dev",
    "medium.com", "substack.com", "linktr.ee", "link3.to", "carrd.co", "webflow.io",
)
_NOT_PROJECT_HOSTS = (
    "linktr.ee", "link3.to", "google.com", "docs.google.com", "forms.gle", "bit.ly",
    "coinmarketcap.com", "coingecko.com", "cryptorank.io", "defillama.com", "dropstab.com",
    "rootdata.com", "airdrops.io", "teletype.in", "telegra.ph",
)
_TWO_LEVEL_TLDS = ("co.uk", "com.au", "co.jp", "com.br", "co.in", "org.uk")
_EXTRACT_PRIORITY = ("site", "docs", "faucet", "tasks", "medium", "github")


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def base_domain(url_or_host: str) -> str:
    host = _host(url_or_host) if "/" in url_or_host else url_or_host.lower()
    if not host:
        return ""
    if any(host == p or host.endswith("." + p) for p in _PLATFORM_SUFFIXES):
        return host
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_link(url: str) -> str:
    host = _host(url)
    if not host:
        return "other"
    for category, domains in _SOCIAL_HOSTS.items():
        if _host_matches(host, domains):
            return category
    lower = url.lower()
    if "faucet" in lower:
        return "faucet"
    if host.startswith("docs.") or _host_matches(host, ("gitbook.io",)) or "/docs" in lower:
        return "docs"
    if _host_matches(host, _NOT_PROJECT_HOSTS):
        return "other"
    return "site"


def classify_links(links: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for link in links:
        out.setdefault(classify_link(link), []).append(link)
    return out


def primary_domain(links: list[str]) -> str:
    """Base domain of the project's own website (used for de-duplication)."""
    grouped = classify_links(links)
    for category in ("site", "docs", "faucet"):
        for link in grouped.get(category, []):
            domain = base_domain(link)
            if domain:
                return domain
    return ""


def name_hint(links: list[str]) -> str:
    """Best guess of the project name before the LLM call (for web search)."""
    domain = primary_domain(links)
    if domain:
        label = domain.split(".")[0]
        if label and label not in {"app", "docs", "testnet", "www"}:
            return label
    for link in classify_links(links).get("x", []):
        path = urlparse(link).path.strip("/").split("/")
        if path and path[0] and path[0].lower() not in {"i", "intent", "home", "search", "hashtag"}:
            return path[0]
    return ""


def pick_extract_urls(links: list[str], limit: int) -> list[str]:
    grouped = classify_links(links)
    out: list[str] = []
    for category in _EXTRACT_PRIORITY:
        for link in grouped.get(category, []):
            if link not in out:
                out.append(link)
    return out[: max(0, limit)]


# --- LLM output ----------------------------------------------------------------


def parse_report(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_str(v) for v in value if _str(v))
    return str(value).strip()


def _list(value, *, limit: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    items = [_str(v)[:300] for v in value]
    return [v for v in items if v][:limit]


def _score(value) -> int | None:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(10, score))


def _is_unknown(value: str) -> bool:
    return value.strip().lower() in {"", "неизвестно", "unknown", "n/a", "нет данных", "-", "—"}


_VERDICT_ICON = {"делать": "🟢", "наблюдать": "🟡", "пропустить": "🔴"}
_LINK_LABELS = (
    ("site", "Сайт"), ("app", "Приложение"), ("docs", "Docs"), ("faucet", "Кран"),
    ("tasks", "Задания"), ("x", "X"), ("discord", "Discord"), ("telegram", "Telegram"),
    ("github", "GitHub"),
)


def format_card(report: dict, *, source: str = "", source_url: str = "") -> str:
    """Telegram HTML card. All dynamic values are escaped."""
    e = html.escape
    name = _str(report.get("project")) or "Без названия"
    header_bits = [b for b in (_str(report.get("category")), _str(report.get("activity_type"))) if not _is_unknown(b)]
    header = f"{CARD_PREFIX} <b>{e(name)}</b>"
    if header_bits:
        header += " — " + e(" · ".join(header_bits))

    sections: list[str] = [header]
    summary = " ".join(_str(report.get("summary")).split())[:700]
    if summary:
        sections[0] += f"\n<i>{e(summary)}</i>"

    facts: list[str] = []
    funding = _str(report.get("funding"))
    investors = _list(report.get("investors"), limit=8)
    if not _is_unknown(funding) or investors:
        line = "💰 Инвестиции: " + e(funding if not _is_unknown(funding) else "сумма неизвестна")
        if investors:
            line += f" ({e(', '.join(investors))})"
        facts.append(line)
    else:
        facts.append("💰 Инвестиции: не найдены")
    token = _str(report.get("token"))
    if token:
        facts.append(f"🪙 Токен: {e(token)}")
    score = _score(report.get("score"))
    verdict = _str(report.get("verdict")).lower()
    reason = _str(report.get("verdict_reason"))
    if score is not None or verdict:
        icon = _VERDICT_ICON.get(verdict, "⚪")
        line = f"{icon} Оценка: <b>{score if score is not None else '?'}/10</b>"
        if verdict:
            line += f" — <b>{e(verdict)}</b>"
        if reason:
            line += f". {e(reason[:300])}"
        facts.append(line)
    sections.append("\n".join(facts))

    req = report.get("requirements") if isinstance(report.get("requirements"), dict) else {}
    req_lines = []
    for key, label in (("socials", "Соцсети"), ("wallets", "Кошелёк"), ("other", "Другое")):
        items = _list(req.get(key), limit=10)
        if items:
            req_lines.append(f"• {label}: {e(', '.join(items))}")
    if req_lines:
        sections.append("<b>Понадобится:</b>\n" + "\n".join(req_lines))

    steps = _list(report.get("steps"), limit=10)
    if steps:
        sections.append(
            "<b>Что делать:</b>\n" + "\n".join(f"{i}. {e(s)}" for i, s in enumerate(steps, start=1)),
        )

    effort = []
    for key, label in (("time", "⏱ Время"), ("cost", "💸 Затраты"), ("deadline", "⏳ Дедлайн")):
        value = _str(report.get(key))
        if not _is_unknown(value):
            effort.append(f"{label}: {e(value[:200])}")
    if effort:
        sections.append("\n".join(effort))

    risks = _list(report.get("risks"), limit=6)
    if risks:
        sections.append("⚠️ <b>Риски:</b>\n" + "\n".join(f"• {e(r)}" for r in risks))

    links = report.get("links") if isinstance(report.get("links"), dict) else {}
    link_lines = []
    for key, label in _LINK_LABELS:
        url = _str(links.get(key))
        if url.startswith(("http://", "https://")):
            link_lines.append(f"{label}: {e(url[:300])}")
    if link_lines:
        sections.append("<b>Ссылки:</b>\n" + "\n".join(link_lines))

    if source or source_url:
        src = e(source or "пост")
        if source_url:
            src = f'<a href="{e(source_url, quote=True)}">{src}</a>'
        sections.append(f"Источник: {src}")

    # Drop the least important sections until the card fits into one Telegram message.
    card = "\n\n".join(sections)
    droppable = ["Ссылки:", "⚠️", "⏱", "Источник:"]
    while len(card) > MAX_CARD_CHARS and droppable:
        marker = droppable.pop(0)
        sections = [s for s in sections if marker not in s.split("\n", 1)[0]]
        card = "\n\n".join(sections)
    if len(card) > MAX_CARD_CHARS:
        card = card[:MAX_CARD_CHARS]
        card = card[: card.rfind("\n")] if "\n" in card else card
    return card


# --- direct page fetch (optional fallback) -----------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_DROP_BLOCKS_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r"<meta[^>]+(?:name|property)=[\"'](?:description|og:description)[\"'][^>]*content=[\"']([^\"']*)",
    re.IGNORECASE,
)


def html_to_text(raw_html: str) -> str:
    title = _TITLE_RE.search(raw_html)
    desc = _META_DESC_RE.search(raw_html)
    body = _DROP_BLOCKS_RE.sub(" ", raw_html)
    body = _TAG_RE.sub(" ", body)
    body = re.sub(r"\s+", " ", html.unescape(body)).strip()
    parts = []
    if title:
        parts.append("Title: " + html.unescape(_TAG_RE.sub("", title.group(1))).strip())
    if desc:
        parts.append("Description: " + html.unescape(desc.group(1)).strip())
    parts.append(body)
    return "\n".join(p for p in parts if p)


def _is_public_host(host: str) -> bool:
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return "." in host
    return False  # literal IPs are never fetched


# --- service ---------------------------------------------------------------------


@dataclass
class TestnetAnalysis:
    relevant: bool
    name: str = ""
    domain: str = ""
    score: int | None = None
    verdict: str = ""
    card: str = ""
    report_json: str = ""
    error: str = ""
    sources_used: list[str] = field(default_factory=list)


class TestnetAnalyzer:
    def __init__(
        self,
        settings: Settings,
        *,
        search: WebSearchService,
        openrouter: OpenRouterService,
    ) -> None:
        self._settings = settings
        self._search = search
        self._openrouter = openrouter
        self._system_prompt: str | None = None
        self._semaphore = asyncio.Semaphore(2)

    def _load_prompt(self) -> str:
        if self._system_prompt is None:
            path: Path = self._settings.testnet_prompt_path
            self._system_prompt = path.read_text(encoding="utf-8").strip()
        return self._system_prompt

    async def analyze(
        self,
        text: str,
        links: list[str],
        *,
        source: str = "",
        source_url: str = "",
    ) -> TestnetAnalysis:
        async with self._semaphore:
            return await self._analyze(text, links, source=source, source_url=source_url)

    async def _analyze(self, text: str, links: list[str], *, source: str, source_url: str) -> TestnetAnalysis:
        if not self._openrouter.is_configured:
            return TestnetAnalysis(relevant=True, error="OpenRouter не настроен (OPENROUTER_API_KEY / OPENROUTER_MODEL).")

        s = self._settings
        links = links[: max(1, s.testnet_max_links)]
        domain = primary_domain(links)
        hint = name_hint(links)

        pages, search_notes = await asyncio.gather(
            self._fetch_pages(pick_extract_urls(links, s.testnet_max_pages)),
            self._search_project(hint),
        )

        prompt = self._build_prompt(
            text=text,
            links=links,
            pages=pages,
            search_notes=search_notes,
            source=source,
        )
        raw = await self._openrouter.generate(
            prompt,
            system=self._load_prompt(),
            model=s.testnet_model or None,
            max_tokens=s.testnet_max_output_tokens,
            max_input_chars=s.testnet_max_input_chars + 1000,
        )
        if not raw:
            return TestnetAnalysis(
                relevant=True,
                domain=domain,
                error=self._openrouter.last_error or "пустой ответ модели",
            )

        report = parse_report(raw)
        if report is None:
            logger.warning("Testnet analyzer: model returned non-JSON output (%s chars)", len(raw))
            card = f"{CARD_PREFIX} <b>Разбор (модель ответила не в JSON)</b>\n\n{html.escape(raw[:3500])}"
            return TestnetAnalysis(relevant=True, domain=domain, card=card, report_json="")

        relevant = report.get("relevant") is not False
        name = _str(report.get("project")) or hint or domain
        return TestnetAnalysis(
            relevant=relevant,
            name=name,
            domain=domain,
            score=_score(report.get("score")),
            verdict=_str(report.get("verdict")).lower(),
            card=format_card(report, source=source, source_url=source_url),
            report_json=json.dumps(report, ensure_ascii=False),
            sources_used=list(pages),
        )

    def _build_prompt(
        self,
        *,
        text: str,
        links: list[str],
        pages: dict[str, str],
        search_notes: list[str],
        source: str,
    ) -> str:
        s = self._settings
        grouped = classify_links(links)
        link_lines = [f"- [{cat}] {url}" for cat, urls in grouped.items() for url in urls]
        parts = []
        if source:
            parts.append(f"Источник поста: {source}")
        parts.append("Текст поста:\n" + (text.strip()[:6000] or "(пусто)"))
        parts.append("Ссылки из поста:\n" + ("\n".join(link_lines) or "(нет)"))
        budget = max(2000, s.testnet_max_input_chars - sum(len(p) for p in parts) - 500)

        search_block = ""
        if search_notes:
            search_block = "Результаты веб-поиска:\n" + "\n".join(search_notes)
            search_block = search_block[: budget // 3]
            budget -= len(search_block)

        page_blocks = []
        per_page = min(s.testnet_max_page_chars, budget // max(1, len(pages))) if pages else 0
        for url, content in pages.items():
            page_blocks.append(f"--- Страница {url} ---\n{content[:per_page]}")
        if page_blocks:
            parts.append("Текст страниц проекта:\n" + "\n\n".join(page_blocks))
        else:
            parts.append("Текст страниц проекта: недоступен (сайты не загружены).")
        if search_block:
            parts.append(search_block)
        else:
            parts.append("Результаты веб-поиска: поиск не выполнялся или ничего не найдено.")
        return "\n\n".join(parts)[: s.testnet_max_input_chars]

    async def _fetch_pages(self, urls: list[str]) -> dict[str, str]:
        if not urls:
            return {}
        if self._search.can_extract:
            pages = await self._search.extract(urls)
            if pages:
                return pages
        if self._settings.testnet_direct_fetch:
            results = await asyncio.gather(*(self._direct_fetch(u) for u in urls))
            return {u: t for u, t in zip(urls, results) if t}
        return {}

    async def _direct_fetch(self, url: str) -> str:
        if not url.startswith(("http://", "https://")) or not _is_public_host(_host(url)):
            return ""
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; telegram-assistant/1.0)"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as resp:
                    if resp.status >= 400 or "html" not in resp.headers.get("Content-Type", "html"):
                        return ""
                    raw = await resp.content.read(1_500_000)
        except Exception:
            logger.info("Direct fetch failed for %s", _host(url))
            return ""
        return html_to_text(raw.decode("utf-8", errors="replace"))

    async def _search_project(self, hint: str) -> list[str]:
        s = self._settings
        if not hint or not s.enable_web_search or s.testnet_max_searches <= 0:
            return []
        queries = [
            f"{hint} crypto project funding investors",
            f"{hint} testnet airdrop guide",
            f"{hint} crypto scam",
        ][: s.testnet_max_searches]
        results = await asyncio.gather(
            *(self._search.search(q, time_range="year", max_results=5) for q in queries),
        )
        notes: list[str] = []
        for query, items in zip(queries, results):
            if not items:
                notes.append(f"• «{query}»: ничего не найдено")
                continue
            lines = []
            for r in items[:5]:
                date = f" [{r['published_date']}]" if r.get("published_date") else ""
                lines.append(f"  - {r.get('title', '')}{date} ({r.get('url', '')}): {(r.get('snippet') or '')[:400]}")
            notes.append(f"• «{query}»:\n" + "\n".join(lines))
        return notes
