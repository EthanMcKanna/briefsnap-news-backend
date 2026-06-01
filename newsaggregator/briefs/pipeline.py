"""Daily brief pipeline focused on useful, lightweight output.

This module is intentionally independent from the older rotating article
manager. It gathers a compact, source-diverse packet of current articles,
asks Gemini for one structured daily brief, and publishes that contract for
the iOS app.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse
from urllib.parse import parse_qs

import feedparser
import requests
from google import genai

from newsaggregator.fetchers.article_fetcher import ArticleFetcher


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
BRIEF_DIR = DATA_DIR / "daily_briefs"

DEFAULT_MODEL = "gemini-2.5-flash"
GROUNDING_MODEL = "gemini-3-flash-preview"
QUALITY_MODEL = "gemini-3.1-pro-preview"
FAST_MODEL = "gemini-2.5-flash-lite"

TRUSTED_SOURCE_DOMAINS: dict[str, int] = {
    "apnews.com": 10,
    "reuters.com": 10,
    "npr.org": 8,
    "bbc.com": 8,
    "bbc.co.uk": 8,
    "wsj.com": 8,
    "nytimes.com": 8,
    "washingtonpost.com": 8,
    "bloomberg.com": 8,
    "cnbc.com": 7,
    "axios.com": 7,
    "politico.com": 7,
    "theguardian.com": 7,
    "statnews.com": 7,
    "theverge.com": 7,
    "techcrunch.com": 7,
    "espn.com": 7,
    "theathletic.com": 7,
    "cbssports.com": 6,
    "nbcsports.com": 6,
}

LOW_VALUE_SOURCE_DOMAINS: tuple[str, ...] = (
    "prnewswire.com",
    "globenewswire.com",
    "businesswire.com",
    "accesswire.com",
)

LOW_VALUE_SOURCE_MARKERS: tuple[str, ...] = (
    "business wire",
    "ein presswire",
    "globenewswire",
    "pr newswire",
    "prnewswire",
    "accesswire",
    "newsfile",
)

LOW_VALUE_URL_MARKERS: tuple[str, ...] = (
    "/press-release/",
    "/press-releases/",
    "/press_release/",
    "/press_releases/",
    "/ein-presswire-",
    "/business-wire/",
    "/globenewswire/",
)

LOW_VALUE_TITLE_MARKERS: tuple[str, ...] = (
    "announces pricing of",
    "apparently over bluetooth",
    "bluetooth device name",
    "class action alert",
    "doesn't matter that people hate",
    "doesn’t matter that people hate",
    "investor alert",
    "pulls u-turn",
    "reports first quarter fiscal",
    "reports fiscal",
    "to host conference call",
    "why shares",
)

BOILERPLATE_COPY_MARKERS: tuple[str, ...] = (
    "add ap news as your preferred source",
    "advertisement",
    "hide caption",
    "is a senior editor and founding member",
    "read more from",
    "sign up for",
    "subscribe to",
    "toggle caption",
)

TOPIC_PRIORITY: tuple[str, ...] = (
    "TOP_NEWS",
    "WORLD",
    "BUSINESS",
    "TECHNOLOGY",
    "HEALTH",
    "SCIENCE",
    "SPORTS",
    "ENTERTAINMENT",
)

PRIMARY_SPORTS_DOMAINS: tuple[str, ...] = (
    "espn.com",
    "theathletic.com",
    "cbssports.com",
    "nbcsports.com",
    "foxsports.com",
    "mlb.com",
    "nba.com",
    "nfl.com",
    "nhl.com",
    "mlssoccer.com",
)

SPORTS_SIGNAL_TERMS: tuple[str, ...] = (
    "nfl",
    "nba",
    "wnba",
    "mlb",
    "nhl",
    "mls",
    "ncaa",
    "college football",
    "college basketball",
    "college sports",
    "nil",
    "transfer portal",
    "salary cap",
    "playoff",
    "finals",
    "standings",
    "trade",
    "injury",
    "coach",
    "draft",
    "contract",
    "game",
    "match",
    "score",
    "win",
    "loss",
    "beat",
    "defeat",
    "season",
    "tournament",
    "championship",
)

SPORTS_SECTION_DRIFT_TERMS: tuple[str, ...] = (
    "white house",
    "president",
    "administration",
    "campaign",
    "congress",
    "senate",
    "supreme court",
    "tariff",
    "lawsuit",
    "stock",
    "earnings",
    "box office",
    "celebrity",
)

TOP_LEVEL_COPY_ENTITY_STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "briefsnap",
    "by",
    "for",
    "from",
    "in",
    "it",
    "its",
    "news",
    "of",
    "on",
    "or",
    "president",
    "senator",
    "senators",
    "the",
    "to",
    "u",
    "us",
    "usa",
    "with",
    "carries",
    "impact",
    "latest",
    "public",
    "readers",
    "source",
    "story",
    "summary",
    "top",
    "verified",
}

MAX_ARTICLES_PER_DOMAIN = int(os.environ.get("BRIEFSNAP_MAX_ARTICLES_PER_DOMAIN", "3"))
MAX_LEADING_STORIES_PER_DOMAIN = int(os.environ.get("BRIEFSNAP_MAX_LEADING_STORIES_PER_DOMAIN", "2"))
MIN_LEADING_TRUSTED_STORIES = int(os.environ.get("BRIEFSNAP_MIN_LEADING_TRUSTED_STORIES", "4"))
MIN_VISIBLE_STORY_TOPICS = int(os.environ.get("BRIEFSNAP_MIN_VISIBLE_STORY_TOPICS", "4"))
MIN_V8_VISIBLE_STORY_TOPICS = int(os.environ.get("BRIEFSNAP_MIN_V8_VISIBLE_STORY_TOPICS", "7"))
MIN_NORMALIZED_STORIES = int(os.environ.get("BRIEFSNAP_MIN_NORMALIZED_STORIES", "10"))
MIN_V8_SOURCE_PACKET_COUNT = int(os.environ.get("BRIEFSNAP_MIN_V8_SOURCE_PACKET_COUNT", "26"))
MIN_V8_SOURCE_PACKET_DOMAINS = int(os.environ.get("BRIEFSNAP_MIN_V8_SOURCE_PACKET_DOMAINS", "12"))
MAX_STALE_LEADING_STORY_HOURS = int(os.environ.get("BRIEFSNAP_MAX_STALE_LEADING_STORY_HOURS", "72"))
SOURCE_PACKET_TOPIC_MINIMUMS: dict[str, int] = {
    "TOP_NEWS": 8,
    "WORLD": 4,
    "BUSINESS": 4,
    "TECHNOLOGY": 4,
    "HEALTH": 2,
    "SCIENCE": 2,
    "SPORTS": 3,
    "ENTERTAINMENT": 1,
}

SPORT_SCORE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("NFL", "football/nfl"),
    ("NCAAF", "football/college-football"),
    ("NBA", "basketball/nba"),
    ("WNBA", "basketball/wnba"),
    ("NCAAB", "basketball/mens-college-basketball"),
    ("MLB", "baseball/mlb"),
    ("NHL", "hockey/nhl"),
    ("MLS", "soccer/usa.1"),
)
SPORT_SCORE_LEAGUE_PRIORITY = {
    "NBA": 0,
    "NHL": 1,
    "WNBA": 2,
    "MLB": 3,
    "MLS": 4,
    "NFL": 5,
    "NCAAF": 6,
    "NCAAB": 7,
}
POSTGAME_SCORE_TTL = timedelta(hours=6)

ARTICLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "dek": {"type": "string"},
        "summary": {"type": "string"},
        "quick_hits": {
            "type": "array",
            "items": {"type": "string"}
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "story_ids": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                },
                "required": ["topic", "title", "summary", "why_it_matters", "story_ids"],
            },
        },
        "custom_widgets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                },
                "required": ["topic", "title", "summary", "items"],
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "topic": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "url": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "urgency": {"type": "string"},
                },
                "required": [
                    "id",
                    "topic",
                    "title",
                    "source",
                    "url",
                    "summary",
                    "why_it_matters",
                    "urgency",
                ],
            },
        },
    },
    "required": [
        "headline",
        "dek",
        "summary",
        "quick_hits",
        "sections",
        "custom_widgets",
        "stories",
    ],
}

CUSTOM_WIDGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "summary", "items"],
}

EDITORIAL_FILLER_PHRASES: tuple[str, ...] = (
    "selected as one of the strongest current stories in the source packet",
    "a compact view of current developments in this category",
    "high source weight and current relevance put it in the lead scan",
    "enough current signal to merit a dedicated scan",
    "latest selected updates",
    "significant developments",
    "continues to unfold",
    "it remains to be seen",
    "the situation is developing",
)
DANGLING_COPY_ENDINGS: set[str] = {
    "a",
    "an",
    "and",
    "another",
    "as",
    "at",
    "because",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "over",
    "the",
    "to",
    "under",
    "while",
    "with",
    "without",
}


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for phrase in EDITORIAL_FILLER_PHRASES:
        if phrase in text.lower():
            text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE).strip(" .;-")
    return text


def _word_count(value: Any) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(value or "")))


def _trim_words(value: Any, max_words: int) -> str:
    text = _trim_text_naturally(value, max_words)
    return text


def _trim_words_plain(value: Any, max_words: int) -> str:
    text = _trim_text_naturally(value, max_words)
    return text


def _trim_text_naturally(value: Any, max_words: int) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    text = _collapse_visible_truncation(text)
    words = text.split()
    if len(words) <= max_words:
        return _strip_dangling_copy_ending(text)

    natural = _natural_boundary_trim(text, max_words)
    if natural:
        return natural

    trimmed = " ".join(words[:max_words]).rstrip(" ,;:-")
    return _strip_dangling_copy_ending(trimmed)


def _collapse_visible_truncation(text: str) -> str:
    parts = [part.strip(" .") for part in re.split(r"\.{3,}|…", text) if part.strip(" .")]
    if not parts:
        return text
    if _word_count(parts[0]) >= 5:
        return parts[0]
    return _clean_text(" ".join(parts))


def _natural_boundary_trim(text: str, max_words: int) -> str:
    best = ""
    minimum_words = min(max(5, max_words // 2), max_words)
    for match in re.finditer(r"([.!?])\s+|[,;:]\s+|\s+[–—-]\s+", text):
        boundary_end = match.end(1) if match.group(1) else match.start()
        candidate = text[:boundary_end].strip(" ,;:-")
        word_count = _word_count(candidate)
        if minimum_words <= word_count <= max_words:
            best = candidate
    if best:
        return _strip_dangling_copy_ending(best)
    return ""


def _strip_dangling_copy_ending(text: str) -> str:
    cleaned = _clean_text(text).rstrip(" ,;:-")
    while cleaned:
        words = cleaned.split()
        if not words:
            return ""
        last_word = re.sub(r"[^a-z0-9']+", "", words[-1].lower())
        if last_word in DANGLING_COPY_ENDINGS:
            cleaned = " ".join(words[:-1]).rstrip(" ,;:-")
            continue
        break
    return cleaned


def _trim_items(items: Any, *, max_items: int, max_words: int) -> list[str]:
    if not isinstance(items, list):
        return []
    trimmed: list[str] = []
    for item in items:
        text = _trim_words(item, max_words)
        if text:
            trimmed.append(text)
        if len(trimmed) >= max_items:
            break
    return trimmed


@dataclass(frozen=True)
class TopicSource:
    code: str
    name: str
    search_queries: tuple[str, ...]
    feeds: tuple[str, ...] = ()


@dataclass
class ArticleCandidate:
    id: str
    topic: str
    title: str
    source: str
    url: str
    published_at: str | None = None
    description: str = ""
    content: str = ""
    image_url: str | None = None
    score: float = 0

    def prompt_record(self, max_chars: int = 900) -> dict[str, Any]:
        body = self.content or self.description
        return {
            "id": self.id,
            "topic": self.topic,
            "title": self.title,
            "source": self.source,
            "domain": DailyBriefPipeline._domain_name(self.url),
            "url": self.url,
            "published_at": self.published_at,
            "image_url": self.image_url,
            "source_score": round(self.score, 2),
            "excerpt": body[:max_chars],
        }


@dataclass
class PipelineOptions:
    dry_run: bool = False
    publish: bool = True
    max_articles_per_topic: int = int(os.environ.get("BRIEFSNAP_ARTICLES_PER_TOPIC", "8"))
    max_total_articles: int = int(os.environ.get("BRIEFSNAP_MAX_TOTAL_ARTICLES", "48"))
    fetch_workers: int = int(os.environ.get("BRIEFSNAP_FETCH_WORKERS", "8"))
    model: str = os.environ.get("BRIEFSNAP_GEMINI_MODEL", DEFAULT_MODEL)
    max_custom_widget_requests: int = int(os.environ.get("BRIEFSNAP_MAX_CUSTOM_WIDGETS", "40"))
    allow_fallback_publish: bool = os.environ.get("BRIEFSNAP_ALLOW_FALLBACK_PUBLISH", "").lower() == "true"


TOPICS: tuple[TopicSource, ...] = (
    TopicSource(
        code="TOP_NEWS",
        name="Top News",
        search_queries=(
            "top US news today",
            "major US headlines today",
            "breaking national news today",
        ),
        feeds=("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="WORLD",
        name="World",
        search_queries=("major world news today", "international headlines today"),
        feeds=("https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="BUSINESS",
        name="Business",
        search_queries=("markets economy business news today", "major company earnings economy today"),
        feeds=("https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="TECHNOLOGY",
        name="Technology",
        search_queries=("technology AI startup news today", "big tech policy AI news today"),
        feeds=("https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="SCIENCE",
        name="Science",
        search_queries=("science space climate research news today",),
        feeds=("https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="HEALTH",
        name="Health",
        search_queries=("health medicine public health news today",),
        feeds=("https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="SPORTS",
        name="Sports",
        search_queries=(
            "ESPN The Athletic NFL NBA MLB NHL WNBA MLS news today",
            "NFL NBA MLB NHL trade injury playoff standings news today",
            "major sports news today confirmed team league",
        ),
        feeds=("https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",),
    ),
    TopicSource(
        code="ENTERTAINMENT",
        name="Culture",
        search_queries=("entertainment culture media news today",),
        feeds=("https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en",),
    ),
)


class DailyBriefPipeline:
    """Collect, summarize, and publish BriefSnap's daily brief."""

    def __init__(self, options: PipelineOptions | None = None):
        self.options = options or PipelineOptions()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "BriefSnapBot/2.0 (+https://briefsnap.com; "
                    "daily brief aggregator)"
                )
            }
        )
        self.newsapi_key = os.environ.get("NEWSAPI_KEY") or os.environ.get("NEWS_API_KEY")
        self.gemini_keys = [
            key
            for key in (
                os.environ.get("GEMINI_API_KEY"),
                os.environ.get("GEMINI_API_KEY_2"),
            )
            if key
        ]
        self.gemini_key = self.gemini_keys[0] if self.gemini_keys else None
        self.today_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.sports_score_cards: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        start = time.time()
        BRIEF_DIR.mkdir(parents=True, exist_ok=True)
        print("====== BriefSnap Daily Brief Started ======")
        print(f"Model: {self.options.model}")

        articles = self.collect_articles()
        if not articles:
            raise RuntimeError("No article candidates survived discovery and extraction")
        sports_source_count = sum(1 for article in articles if self._normalize_topic(article.topic) == "SPORTS")
        print(f"Source packet sports stories: {sports_source_count}")

        if self.options.publish:
            self._archive_stale_firestore_scores()
        self.sports_score_cards = self._fetch_top_sports_scores()
        print(f"Sports scores: selected {len(self.sports_score_cards)} game(s)")

        if self.options.dry_run:
            brief = self._fallback_brief(articles, model_used="dry-run")
        else:
            brief = self.generate_brief(articles)

        quality_issues = self._brief_quality_issues(brief)
        if quality_issues:
            print("[WARN] Daily brief quality issues:")
            for issue in quality_issues:
                print(f"  - {issue}")
            if not self.options.dry_run:
                raise RuntimeError("Daily brief quality gate failed: " + "; ".join(quality_issues))

        artifact_path = self.write_artifact(brief)
        if self.options.publish and not self.options.dry_run:
            self.publish_firestore(brief)

        elapsed = time.time() - start
        print(f"Saved daily brief artifact: {artifact_path}")
        print(f"Completed in {elapsed:.1f}s with {len(articles)} source articles")
        return brief

    def collect_articles(self) -> list[ArticleCandidate]:
        candidates: list[ArticleCandidate] = []
        for topic in TOPICS:
            topic_candidates = self._collect_topic(topic)
            candidates.extend(topic_candidates[: self.options.max_articles_per_topic])
            print(f"{topic.code}: selected {len(topic_candidates[: self.options.max_articles_per_topic])}")

        deduped = self._dedupe(candidates)
        source_packet = self._diversify_articles(deduped, limit=self.options.max_total_articles)
        enriched = self._enrich_articles(source_packet)
        ranked = sorted(enriched, key=lambda article: article.score, reverse=True)
        return self._diversify_articles(ranked, limit=self.options.max_total_articles)

    def _collect_topic(self, topic: TopicSource) -> list[ArticleCandidate]:
        raw: list[dict[str, Any]] = []
        for feed_url in topic.feeds:
            raw.extend(self._fetch_rss(feed_url, topic))
        for query in topic.search_queries:
            raw.extend(self._fetch_rss(self._google_news_search_url(query), topic))
        raw.extend(self._fetch_newsapi(topic))
        if topic.code == "SPORTS":
            raw.extend(self._fetch_espn_sports_news())

        candidates = [self._candidate_from_raw(item, topic) for item in raw]
        candidates = [candidate for candidate in candidates if candidate]
        candidates = self._dedupe(candidates)
        for candidate in candidates:
            candidate.score = self._score_candidate(candidate)
        return sorted(candidates, key=lambda article: article.score, reverse=True)

    def _fetch_rss(self, url: str, topic: TopicSource) -> list[dict[str, Any]]:
        try:
            response = self.session.get(url, timeout=12)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as exc:
            print(f"[WARN] RSS fetch failed for {topic.code}: {exc}")
            return []

        source_name = feed.feed.get("title") or topic.name
        items = []
        for entry in feed.entries[:25]:
            items.append(
                {
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link"),
                    "source": self._entry_source(entry, source_name),
                    "published_at": self._entry_date(entry),
                    "description": self._clean_html(entry.get("summary", "")),
                }
            )
        return items

    def _fetch_newsapi(self, topic: TopicSource) -> list[dict[str, Any]]:
        if not self.newsapi_key:
            return []

        params = {
            "apiKey": self.newsapi_key,
            "language": "en",
            "pageSize": "20",
            "sortBy": "publishedAt",
        }
        if topic.code == "TOP_NEWS":
            url = "https://newsapi.org/v2/top-headlines"
            params.update({"country": "us"})
        else:
            url = "https://newsapi.org/v2/everything"
            params.update({"q": topic.search_queries[0]})

        try:
            response = self.session.get(url, params=params, timeout=12)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"[WARN] NewsAPI fetch failed for {topic.code}: {exc}")
            return []

        items = []
        for article in payload.get("articles", []):
            items.append(
                {
                    "title": article.get("title"),
                    "url": article.get("url"),
                    "source": (article.get("source") or {}).get("name") or "NewsAPI",
                    "published_at": article.get("publishedAt"),
                    "description": article.get("description") or "",
                    "image_url": article.get("urlToImage"),
                }
            )
        return items

    def _fetch_espn_sports_news(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for league, path in SPORT_SCORE_ENDPOINTS:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/news"
            try:
                response = self.session.get(url, params={"limit": 5}, timeout=10)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                print(f"[WARN] ESPN sports news fetch failed for {league}: {exc}")
                continue

            for article in payload.get("articles", []) or []:
                headline = article.get("headline") or article.get("title")
                links = article.get("links") or {}
                web_link = links.get("web") if isinstance(links, dict) else {}
                if not isinstance(web_link, dict):
                    web_link = {}
                href = web_link.get("href") or web_link.get("url") or article.get("link")
                normalized_url = self._normalize_url(href)
                if not headline or not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)

                raw_source = article.get("source")
                if isinstance(raw_source, dict):
                    source = raw_source.get("name") or raw_source.get("displayName")
                else:
                    source = raw_source

                items.append(
                    {
                        "title": headline,
                        "url": normalized_url,
                        "source": source or "ESPN",
                        "published_at": article.get("published") or article.get("lastModified"),
                        "description": article.get("description") or article.get("story") or "",
                        "image_url": self._espn_article_image_url(article),
                    }
                )
        return items

    @staticmethod
    def _espn_article_image_url(article: dict[str, Any]) -> str | None:
        images = article.get("images") or []
        if not isinstance(images, list):
            return None
        for image in images:
            if not isinstance(image, dict):
                continue
            image_url = image.get("url") or image.get("href")
            if image_url:
                return str(image_url)
        return None

    def _candidate_from_raw(self, item: dict[str, Any], topic: TopicSource) -> ArticleCandidate | None:
        url = self._normalize_url(item.get("url"))
        source = _clean_text(item.get("source") or (self._domain_name(url) if url else ""))
        title = self._clean_title(item.get("title"), source=source)
        if not title or len(title) < 12 or not url:
            return None
        domain = self._domain_name(url)
        description = self._clean_description(
            item.get("description") or "",
            title=title,
            source=source,
        )
        if any(domain.endswith(blocked) for blocked in LOW_VALUE_SOURCE_DOMAINS):
            return None
        candidate_topic = self._classify_candidate_topic(
            topic_code=topic.code,
            title=title,
            source=source,
            url=url,
            description=description,
        )
        if self._is_low_value_candidate(
            title=title,
            topic_code=candidate_topic,
            source=source,
            url=url,
            description=description,
        ):
            return None
        if candidate_topic == "SPORTS" and not self._is_high_signal_sports_candidate(
            title=title,
            source=source or domain,
            url=url,
            description=description,
        ):
            return None

        stable = hashlib.sha1(f"{candidate_topic}:{url}".encode("utf-8")).hexdigest()[:16]
        return ArticleCandidate(
            id=stable,
            topic=candidate_topic,
            title=title,
            source=source or self._domain_name(url),
            url=url,
            published_at=item.get("published_at"),
            description=description,
            image_url=item.get("image_url"),
        )

    def _enrich_articles(self, candidates: list[ArticleCandidate]) -> list[ArticleCandidate]:
        if not candidates:
            return []

        enriched: list[ArticleCandidate] = []
        with ThreadPoolExecutor(max_workers=self.options.fetch_workers) as executor:
            future_map = {
                executor.submit(self._scrape_candidate, candidate): candidate
                for candidate in candidates
            }
            for future in as_completed(future_map):
                candidate = future_map[future]
                try:
                    enriched_candidate = future.result()
                except Exception as exc:
                    print(f"[WARN] Extraction crashed for {candidate.title}: {exc}")
                    enriched_candidate = candidate
                if (
                    enriched_candidate.content
                    or enriched_candidate.description
                    or self._should_keep_thin_candidate(enriched_candidate)
                ):
                    enriched.append(enriched_candidate)

        return enriched

    def _should_keep_thin_candidate(self, candidate: ArticleCandidate) -> bool:
        if self._is_low_value_candidate(
            title=candidate.title,
            topic_code=candidate.topic,
            source=candidate.source,
            url=candidate.url,
            description=candidate.description or candidate.content[:400],
        ):
            return False
        if self._normalize_topic(candidate.topic) == "SPORTS":
            return self._is_high_signal_sports_candidate(
                title=candidate.title,
                source=candidate.source,
                url=candidate.url,
                description=candidate.description or candidate.content[:400],
            )
        domain = self._domain_name(candidate.url)
        if self._is_trusted_domain(domain):
            return True
        trusted_source_names = (
            "ap news",
            "associated press",
            "bbc",
            "bloomberg",
            "cbs news",
            "cnbc",
            "cnn",
            "npr",
            "reuters",
            "the guardian",
            "the new york times",
            "the verge",
            "washington post",
            "wsj",
        )
        return any(source in candidate.source.lower() for source in trusted_source_names)

    def _scrape_candidate(self, candidate: ArticleCandidate) -> ArticleCandidate:
        if "news.google.com" in candidate.url:
            resolved_url = ArticleFetcher.extract_real_url_from_google(candidate.url)
            normalized_url = self._normalize_url(resolved_url)
            if not normalized_url:
                return candidate
            candidate.url = normalized_url
            candidate.score = max(candidate.score, self._score_candidate(candidate))

        content, published = ArticleFetcher.scrape_article_content(candidate.url)
        if content:
            candidate.content = content
            candidate.score += min(len(content) / 1200, 8)
        if published and not candidate.published_at:
            candidate.published_at = published.isoformat()
        image_candidates = [candidate.image_url] if candidate.image_url else []
        fetched_article_images = False
        if not candidate.image_url:
            image_candidates.extend(ArticleFetcher.find_article_images(candidate.url))
            fetched_article_images = True
        best_image = ArticleFetcher.select_best_image(
            image_candidates,
            fallback_urls=[] if fetched_article_images else [candidate.url],
            max_fallback_articles=1,
        )
        if best_image:
            candidate.image_url = best_image
            candidate.score += 1.5
        return candidate

    def generate_brief(self, articles: list[ArticleCandidate]) -> dict[str, Any]:
        if not self.gemini_keys:
            raise RuntimeError("GEMINI_API_KEY is required for non-dry-run brief generation")

        prompt = self._brief_prompt(articles)
        clients = self._gemini_clients()
        grounded_models = self._unique_models(
            model
            for model in (self.options.model, GROUNDING_MODEL, QUALITY_MODEL)
            if self._supports_grounded_structured_output(model)
        )
        source_packet_models = self._unique_models(
            (self.options.model, DEFAULT_MODEL, FAST_MODEL, GROUNDING_MODEL, QUALITY_MODEL)
        )

        last_error: Exception | None = None
        grounded_config = {
            "tools": [{"google_search": {}}],
            "response_mime_type": "application/json",
            "response_json_schema": ARTICLE_SCHEMA,
            "max_output_tokens": 8192,
            "temperature": 0.35,
        }
        for client_label, client in clients:
            for model in grounded_models:
                for attempt in range(1, 3):
                    try:
                        print(
                            "Generating search-grounded structured brief "
                            f"with {model} via {client_label} (attempt {attempt})"
                        )
                        response = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=grounded_config,
                        )
                        payload = self._parse_json_response(response.text)
                        return self._normalize_brief(payload, articles, f"{model}-search-grounded")
                    except Exception as exc:
                        print(f"[WARN] Gemini search-grounded model {model} via {client_label} failed: {exc}")
                        last_error = exc
                        if attempt >= 2 or not self._should_retry_generation(exc):
                            break
                        time.sleep(4 * attempt)

        grounded_text_config = {
            "tools": [{"google_search": {}}],
            "max_output_tokens": 8192,
            "temperature": 0.25,
        }
        grounded_text_models = self._unique_models((self.options.model, DEFAULT_MODEL, FAST_MODEL))
        for client_label, client in clients:
            for model in grounded_text_models:
                for prompt_label, source_prompt in (
                    ("full", prompt),
                    ("compact", self._brief_prompt(articles[:24], max_excerpt_chars=450)),
                ):
                    try:
                        print(
                            "Generating search-grounded text JSON brief "
                            f"with {model} via {client_label} ({prompt_label})"
                        )
                        response = client.models.generate_content(
                            model=model,
                            contents=source_prompt,
                            config=grounded_text_config,
                        )
                        payload = self._parse_json_response(response.text)
                        return self._normalize_brief(payload, articles, f"{model}-search-grounded-text")
                    except Exception as exc:
                        print(f"[WARN] Gemini search-grounded text model {model} via {client_label} failed: {exc}")
                        last_error = exc

        source_config = {
            "response_mime_type": "application/json",
            "response_json_schema": ARTICLE_SCHEMA,
            "max_output_tokens": 8192,
            "temperature": 0.25,
        }
        for client_label, client in clients:
            for model in source_packet_models:
                for prompt_label, source_prompt in (
                    ("full", prompt),
                    ("compact", self._brief_prompt(articles[:24], max_excerpt_chars=450)),
                ):
                    try:
                        print(
                            "Generating structured source-packet brief "
                            f"with {model} via {client_label} ({prompt_label})"
                        )
                        response = client.models.generate_content(
                            model=model,
                            contents=source_prompt,
                            config=source_config,
                        )
                        payload = self._parse_json_response(response.text)
                        return self._normalize_brief(payload, articles, f"{model}-source-packet")
                    except Exception as exc:
                        print(f"[WARN] Gemini source-packet model {model} via {client_label} failed: {exc}")
                        last_error = exc

        message = f"Gemini unavailable after all configured models; refusing to publish fallback brief: {last_error}"
        if not self.options.allow_fallback_publish:
            raise RuntimeError(message)
        print(f"[WARN] {message}")
        return self._fallback_brief(articles, model_used="source-ranked-fallback")

    def _brief_prompt(self, articles: list[ArticleCandidate], max_excerpt_chars: int = 900) -> str:
        records = [article.prompt_record(max_chars=max_excerpt_chars) for article in articles]
        generated_at = datetime.now(timezone.utc).isoformat()
        return f"""
You are the editor of BriefSnap, an iOS app whose entire value proposition is
one excellent short daily brief.

Write a compact, high-signal daily brief for a busy US reader. Prioritize the
most consequential stories, avoid filler, and organize the response so the app
can show:
- a top daily brief,
- weather-adjacent context only when newsworthy,
- and lightweight custom news widgets by topic.
Every word must earn its place. Assume the reader opens the app for one minute
and expects a real payoff.

Rules:
- Use the supplied source packet as the main evidence and cross-check with
  Search before elevating a fast-moving claim.
- Use Google Search to verify recency, importance, and any fast-moving claim.
- Prefer direct reporting from wire services, established national/local
  outlets, and subject-matter publications over aggregated rewrites.
- Preserve source diversity: do not let one publisher or one ideological lane
  dominate unless the facts clearly require it.
- Do not invent URLs. Use article ids and URLs from the source packet when you
  select stories.
- Prefer stories with usable image_url values when editorial importance is
  otherwise comparable, but never choose a weaker story just because it has art.
- Keep the prose crisp and useful. No hype, no generic caveats.
- Prefer US relevance for TOP_NEWS, but preserve important world context.
- The response must match the JSON schema exactly.
- Return sections for TOP_NEWS, BUSINESS, SPORTS, and any other category with
  genuinely strong source support.
- Each section's story_ids must point to distinct story objects in the stories
  array. TOP_NEWS needs at least three separate stories, not one blended recap.
- For SPORTS, incorporate the sports score packet when live or final games are
  present.
- Return at least five custom_widgets when the source packet supports them.
- headline: 10 words max, specific enough to feel reported.
- dek: 22 words max, one sharp reason the day matters.
- summary: 45 to 70 words, no throat-clearing.
- quick_hits: 5 or 6 bullets, 14 words max each.
- story summary: 22 words max. why_it_matters: 18 words max with a concrete consequence.
- custom widget title: 5 words max. summary: 24 words max. items: 3 to 5 bullets, 12 words max each.
- Ban generic phrases like "continues to unfold", "significant developments",
  "it remains to be seen", and "selected as one of the strongest stories".

Generated at: {generated_at}

Source packet:
{json.dumps(records, ensure_ascii=False)}

Sports score packet:
{json.dumps(self.sports_score_cards, ensure_ascii=False)}
""".strip()

    def _gemini_clients(self) -> list[tuple[str, Any]]:
        timeout = int(os.environ.get("BRIEFSNAP_GEMINI_TIMEOUT_MS", "75000"))
        return [
            (
                f"key-{index}",
                genai.Client(
                    api_key=api_key,
                    http_options={"timeout": timeout},
                ),
            )
            for index, api_key in enumerate(self.gemini_keys, start=1)
        ]

    @staticmethod
    def _unique_models(models: Any) -> list[str]:
        unique: list[str] = []
        for model in models:
            if model and model not in unique:
                unique.append(model)
        return unique

    @staticmethod
    def _supports_grounded_structured_output(model: str) -> bool:
        return model.startswith("gemini-3")

    def _normalize_brief(
        self,
        payload: dict[str, Any],
        articles: list[ArticleCandidate],
        model_used: str,
    ) -> dict[str, Any]:
        article_by_id = {article.id: article for article in articles}
        story_ids = set()
        normalized_stories = []

        for story in payload.get("stories", []):
            source_article = article_by_id.get(story.get("id"))
            if not source_article:
                source_article = self._match_story(story, articles)
            if not source_article or source_article.id in story_ids:
                continue
            story_ids.add(source_article.id)
            normalized_stories.append(self._normalized_story_from_article(source_article, story=story))

        if len(normalized_stories) < 6:
            for article in articles:
                if article.id in story_ids:
                    continue
                story_ids.add(article.id)
                normalized_stories.append(self._normalized_story_from_article(article))
                if len(normalized_stories) >= 12:
                    break

        if len(normalized_stories) < 6:
            return self._fallback_brief(articles, model_used=model_used)

        self._ensure_sports_news_stories(normalized_stories, articles, story_ids)
        self._ensure_topic_breadth_stories(normalized_stories, articles, story_ids)
        normalized_stories = self._rebalance_story_order(normalized_stories, articles)
        normalized_stories = self._ensure_story_image_coverage(normalized_stories, articles)

        now = datetime.now(timezone.utc)
        sections = self._normalize_sections(payload.get("sections", []), normalized_stories, articles)
        widgets = self._normalize_widgets(payload.get("custom_widgets", []), normalized_stories, articles)
        headline, dek, summary, quick_hits = self._grounded_top_level_copy(
            payload=payload,
            stories=normalized_stories,
        )

        score_cards = self.sports_score_cards[:6]
        brief = {
            "id": self.today_id,
            "generated_at": now.isoformat(),
            "model_used": model_used,
            "headline": headline,
            "dek": dek,
            "summary": summary,
            "quick_hits": quick_hits,
            "hero_image_url": self._hero_image_url(normalized_stories),
            "sections": sections,
            "custom_widgets": widgets,
            "stories": normalized_stories[:18],
            "sports_scores": score_cards,
            "source_count": len(articles),
            "coverage_report": self._coverage_report(
                stories=normalized_stories[:18],
                articles=articles,
                sections=sections,
            ),
        }
        brief.update(self._sports_scores_metadata(score_cards))
        return brief

    def _normalized_story_from_article(
        self,
        article: ArticleCandidate,
        *,
        story: dict[str, Any] | None = None,
        why_it_matters: str | None = None,
    ) -> dict[str, Any]:
        story = story or {}
        source = _clean_text(story.get("source") or article.source)
        title = self._clean_title(story.get("title") or article.title, source=source)
        summary = self._clean_description(story.get("summary") or "", title=title, source=source)
        if not summary:
            summary = self._clean_description(article.description or "", title=title, source=source)
        if not summary:
            summary = self._clean_description(article.content[:500], title=title, source=source)
        if not summary:
            summary = title

        topic = article.topic
        if self._normalize_topic(topic) != "SPORTS":
            topic = story.get("topic") or article.topic

        return {
            "id": article.id,
            "topic": topic,
            "title": _trim_words(title, 18),
            "source": source,
            "url": article.url,
            "summary": _trim_words(summary, 22),
            "why_it_matters": _trim_words(
                story.get("why_it_matters") or why_it_matters or self._default_why_it_matters(article),
                18,
            ),
            "urgency": _clean_text(story.get("urgency") or "medium").lower() or "medium",
            "published_at": article.published_at,
            "image_url": self._story_image_url(article.image_url),
        }

    @classmethod
    def _default_why_it_matters(cls, article: ArticleCandidate) -> str:
        topic = cls._normalize_topic(article.topic)
        if topic == "TOP_NEWS":
            return "It is one of today's clearest public-impact updates."
        if topic == "BUSINESS":
            return "It can affect markets, companies, or household costs."
        if topic == "TECHNOLOGY":
            return "It can shift products, policy, or platform decisions."
        if topic == "WORLD":
            return "It adds context for global risk and diplomacy."
        if topic == "HEALTH":
            return "It can affect public health guidance or care decisions."
        if topic == "SCIENCE":
            return "It changes the evidence base for an important field."
        if topic == "SPORTS":
            return "It gives fans verified context beyond the scoreboard."
        if topic == "ENTERTAINMENT":
            return "It changes the culture and media conversation."
        return "It gives readers useful context for the day."

    def _ensure_sports_news_stories(
        self,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
        story_ids: set[str],
        *,
        minimum: int = 2,
        max_visible: int = 18,
    ) -> None:
        visible_stories = stories[:max_visible]
        existing = [
            story
            for story in visible_stories
            if self._normalize_topic(story.get("topic")) == "SPORTS"
            and self._is_high_signal_sports_candidate(
                title=str(story.get("title") or ""),
                source=str(story.get("source") or ""),
                url=str(story.get("url") or ""),
                description=" ".join(str(story.get(key) or "") for key in ("summary", "why_it_matters")),
            )
        ]
        if len(existing) >= minimum:
            return

        for index, story in enumerate(stories[max_visible:], start=max_visible):
            if len(existing) >= minimum:
                break
            if self._normalize_topic(story.get("topic")) != "SPORTS":
                continue
            if not self._is_high_signal_sports_candidate(
                title=str(story.get("title") or ""),
                source=str(story.get("source") or ""),
                url=str(story.get("url") or ""),
                description=" ".join(str(story.get(key) or "") for key in ("summary", "why_it_matters")),
            ):
                continue
            replacement_index = self._replacement_index_for_story_topic_minimum(
                stories[:max_visible],
                protected_topic="SPORTS",
            )
            if replacement_index is None:
                break
            stories[replacement_index], stories[index] = stories[index], stories[replacement_index]
            existing.append(stories[replacement_index])

        for article in articles:
            if len(existing) >= minimum:
                break
            if article.id in story_ids or self._normalize_topic(article.topic) != "SPORTS":
                continue
            if not self._is_high_signal_sports_candidate(
                title=article.title,
                source=article.source,
                url=article.url,
                description=article.description or article.content[:400],
            ):
                continue

            story_ids.add(article.id)
            story = self._normalized_story_from_article(
                article,
                why_it_matters="A high-signal sports source adds context beyond the scoreboard.",
            )
            if len(stories) < max_visible:
                stories.append(story)
            else:
                replacement_index = self._replacement_index_for_story_topic_minimum(
                    stories[:max_visible],
                    protected_topic="SPORTS",
                )
                if replacement_index is None:
                    break
                stories[replacement_index] = story
            existing.append(story)

    @staticmethod
    def _replacement_index_for_story_topic_minimum(
        stories: list[dict[str, Any]],
        *,
        protected_topic: str,
    ) -> int | None:
        normalized_protected = DailyBriefPipeline._normalize_topic(protected_topic)
        for index in range(len(stories) - 1, -1, -1):
            topic = DailyBriefPipeline._normalize_topic(stories[index].get("topic"))
            if topic not in {normalized_protected, "TOP_NEWS"}:
                return index
        for index in range(len(stories) - 1, -1, -1):
            if DailyBriefPipeline._normalize_topic(stories[index].get("topic")) != normalized_protected:
                return index
        return None

    def _ensure_topic_breadth_stories(
        self,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
        story_ids: set[str],
    ) -> None:
        topic_groups = self._topic_article_groups(articles)
        if not topic_groups:
            return

        preferred_topics = [
            "TOP_NEWS",
            "WORLD",
            "BUSINESS",
            "TECHNOLOGY",
            "HEALTH",
            "SCIENCE",
            "SPORTS",
            "ENTERTAINMENT",
        ]
        supported_topics = [
            topic
            for topic in preferred_topics
            if len(topic_groups.get(topic, [])) >= self._minimum_sources_for_topic(topic)
        ]
        if not supported_topics:
            return

        target_topic_count = min(
            max(MIN_VISIBLE_STORY_TOPICS, MIN_V8_VISIBLE_STORY_TOPICS),
            len(supported_topics),
        )
        visible_topics = {
            self._normalize_topic(story.get("topic"))
            for story in stories[:18]
            if story.get("topic")
        }
        visible_topics.discard("")

        for topic in supported_topics:
            if len(visible_topics) >= target_topic_count:
                break
            if topic in visible_topics:
                continue
            article = next(
                (
                    candidate
                    for candidate in topic_groups.get(topic, [])
                    if candidate.id not in story_ids
                ),
                None,
            )
            if not article:
                continue
            if topic == "SPORTS" and not self._is_high_signal_sports_candidate(
                title=article.title,
                source=article.source,
                url=article.url,
                description=article.description or article.content[:400],
            ):
                continue
            story_ids.add(article.id)
            stories.append(self._normalized_story_from_article(article))
            visible_topics.add(topic)

        for topic in ("HEALTH", "SCIENCE"):
            if topic not in supported_topics or topic in visible_topics:
                continue
            article = next(
                (
                    candidate
                    for candidate in topic_groups.get(topic, [])
                    if candidate.id not in story_ids
                ),
                None,
            )
            if not article:
                continue
            story_ids.add(article.id)
            stories.append(self._normalized_story_from_article(article))
            visible_topics.add(topic)

        target_story_count = min(max(MIN_NORMALIZED_STORIES, target_topic_count + 3), len(articles), 18)
        if len(stories) >= target_story_count:
            return

        for article in articles:
            if len(stories) >= target_story_count:
                break
            if article.id in story_ids:
                continue
            topic = self._normalize_topic(article.topic)
            if topic == "SPORTS" and not self._is_high_signal_sports_candidate(
                title=article.title,
                source=article.source,
                url=article.url,
                description=article.description or article.content[:400],
            ):
                continue
            story_ids.add(article.id)
            stories.append(self._normalized_story_from_article(article))

    def _rebalance_story_order(
        self,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
    ) -> list[dict[str, Any]]:
        if len(stories) < 4:
            return self._dedupe_story_list(stories)

        article_by_id = {article.id: article for article in articles}
        remaining = list(stories)
        ordered: list[dict[str, Any]] = []
        topic_counts: Counter[str] = Counter()
        domain_counts: Counter[str] = Counter()

        def story_rank(story: dict[str, Any]) -> tuple[float, int]:
            article = article_by_id.get(str(story.get("id") or ""))
            score = article.score if article else 0
            topic = self._normalize_topic(story.get("topic"))
            topic_priority = TOPIC_PRIORITY.index(topic) if topic in TOPIC_PRIORITY else len(TOPIC_PRIORITY)
            return (score, -topic_priority)

        def can_take(story: dict[str, Any], *, relaxed: bool = False) -> bool:
            topic = self._normalize_topic(story.get("topic"))
            domain = self._domain_name(str(story.get("url") or ""))
            first_eight = len(ordered) < 8
            if first_eight and not relaxed:
                topic_cap = 3 if topic == "TOP_NEWS" else 2
                if topic_counts[topic] >= topic_cap:
                    return False
                if domain and domain_counts[domain] >= 2:
                    return False
            return True

        def take_best(topic: str | None = None, *, relaxed: bool = False) -> bool:
            candidates = [
                story
                for story in remaining
                if (topic is None or self._normalize_topic(story.get("topic")) == topic)
                and can_take(story, relaxed=relaxed)
            ]
            if not candidates:
                return False
            best = max(candidates, key=story_rank)
            remaining.remove(best)
            ordered.append(best)
            topic_counts[self._normalize_topic(best.get("topic"))] += 1
            domain = self._domain_name(str(best.get("url") or ""))
            if domain:
                domain_counts[domain] += 1
            return True

        take_best("TOP_NEWS", relaxed=True)

        for topic in TOPIC_PRIORITY:
            if len(ordered) >= 8:
                break
            if topic_counts[topic]:
                continue
            take_best(topic)

        while remaining and len(ordered) < min(8, len(stories)):
            if not take_best():
                if not take_best(relaxed=True):
                    break

        ordered.extend(remaining)
        return self._dedupe_story_list(ordered)

    def _ensure_story_image_coverage(
        self,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
    ) -> list[dict[str, Any]]:
        if not stories:
            return stories

        required_images = (len(stories) * 3 + 3) // 4
        current_images = sum(1 for story in stories if self._story_has_valid_image(story))
        if current_images >= required_images:
            return stories

        story_ids = {str(story.get("id") or "") for story in stories if story.get("id")}
        used_replacement_ids: set[str] = set()
        image_articles = [
            article
            for article in articles
            if article.id not in story_ids
            and ArticleFetcher._is_valid_image_url(str(article.image_url or ""))
            and not self._is_low_value_candidate(
                title=article.title,
                topic_code=article.topic,
                source=article.source,
                url=article.url,
                description=article.description or article.content[:400],
            )
        ]
        image_articles.sort(key=lambda article: article.score, reverse=True)

        def replacement_for(topic: str) -> ArticleCandidate | None:
            normalized_topic = self._normalize_topic(topic)
            for prefer_same_topic in (True, False):
                for article in image_articles:
                    if article.id in used_replacement_ids:
                        continue
                    if prefer_same_topic and self._normalize_topic(article.topic) != normalized_topic:
                        continue
                    if not prefer_same_topic and self._normalize_topic(article.topic) == "SPORTS":
                        continue
                    replacement = self._normalized_story_from_article(article)
                    if any(self._stories_are_near_duplicates(replacement, story) for story in stories):
                        continue
                    used_replacement_ids.add(article.id)
                    return article
            return None

        repaired = list(stories)
        missing_indices = [
            index
            for index, story in enumerate(repaired)
            if not self._story_has_valid_image(story)
            and index >= 3
        ]
        for index in reversed(missing_indices):
            if current_images >= required_images:
                break
            replacement = replacement_for(str(repaired[index].get("topic") or ""))
            if not replacement:
                continue
            repaired[index] = self._normalized_story_from_article(replacement)
            current_images += 1

        while repaired and current_images < (len(repaired) * 3 + 3) // 4 and len(repaired) > MIN_NORMALIZED_STORIES:
            drop_index = next(
                (
                    index
                    for index in range(len(repaired) - 1, -1, -1)
                    if not self._story_has_valid_image(repaired[index])
                ),
                None,
            )
            if drop_index is None:
                break
            repaired.pop(drop_index)

        return repaired

    @staticmethod
    def _story_has_valid_image(story: dict[str, Any]) -> bool:
        return ArticleFetcher._is_valid_image_url(str(story.get("image_url") or ""))

    @classmethod
    def _dedupe_story_list(cls, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for story in stories:
            if any(cls._stories_are_near_duplicates(story, existing) for existing in deduped):
                continue
            deduped.append(story)
        return deduped

    @classmethod
    def _stories_are_near_duplicates(cls, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_tokens = cls._story_title_tokens(left)
        right_tokens = cls._story_title_tokens(right)
        if not left_tokens or not right_tokens:
            return False
        common_tokens = left_tokens & right_tokens
        if len(common_tokens) >= 4:
            return True

        left_bigrams = cls._story_title_bigrams(left)
        right_bigrams = cls._story_title_bigrams(right)
        if left_bigrams & right_bigrams and len(common_tokens) >= 3:
            return True
        return False

    @staticmethod
    def _story_title_tokens(story: dict[str, Any]) -> set[str]:
        title = str(story.get("title") or "").lower()
        tokens = {
            token
            for token in re.findall(r"[a-z0-9']+", title)
            if len(token) > 2 and token not in TOP_LEVEL_COPY_ENTITY_STOPWORDS
        }
        return tokens

    @staticmethod
    def _story_title_bigrams(story: dict[str, Any]) -> set[tuple[str, str]]:
        title = str(story.get("title") or "").lower()
        tokens = [
            token
            for token in re.findall(r"[a-z0-9']+", title)
            if len(token) > 2 and token not in TOP_LEVEL_COPY_ENTITY_STOPWORDS
        ]
        return set(zip(tokens, tokens[1:]))

    @staticmethod
    def _minimum_sources_for_topic(topic: str) -> int:
        normalized = DailyBriefPipeline._normalize_topic(topic)
        if normalized == "TOP_NEWS":
            return 3
        if normalized in {"WORLD", "HEALTH", "SCIENCE", "ENTERTAINMENT"}:
            return 1
        return 2

    def _fallback_brief(self, articles: list[ArticleCandidate], model_used: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        top = articles[:12]
        stories = []
        story_ids: set[str] = set()
        for article in top:
            story_ids.add(article.id)
            stories.append(self._normalized_story_from_article(article))
        self._ensure_sports_news_stories(stories, articles, story_ids)
        self._ensure_topic_breadth_stories(stories, articles, story_ids)
        stories = self._rebalance_story_order(stories, articles)
        stories = self._ensure_story_image_coverage(stories, articles)
        score_cards = self.sports_score_cards[:6]
        headline, dek, summary, quick_hits = self._grounded_top_level_copy(payload={}, stories=stories)
        sections = self._normalize_sections([], stories, articles)
        brief = {
            "id": self.today_id,
            "generated_at": now.isoformat(),
            "model_used": model_used,
            "headline": headline,
            "dek": dek,
            "summary": summary,
            "quick_hits": quick_hits,
            "hero_image_url": self._hero_image_url(stories),
            "sections": sections,
            "custom_widgets": self._normalize_widgets([], stories, articles),
            "stories": stories,
            "sports_scores": score_cards,
            "source_count": len(articles),
            "coverage_report": self._coverage_report(
                stories=stories,
                articles=articles,
                sections=sections,
            ),
        }
        brief.update(self._sports_scores_metadata(score_cards))
        return brief

    def _normalize_sections(
        self,
        raw_sections: Any,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        seen_topics: set[str] = set()
        valid_story_ids = {str(story.get("id")) for story in stories if story.get("id")}

        if isinstance(raw_sections, list):
            for section in raw_sections:
                if not isinstance(section, dict):
                    continue
                topic = self._normalize_topic(section.get("topic"))
                title = _trim_words(section.get("title"), 6)
                summary = _trim_words(section.get("summary"), 24)
                why_it_matters = _trim_words(section.get("why_it_matters"), 18)
                story_ids = [
                    str(story_id)
                    for story_id in section.get("story_ids", [])
                    if str(story_id).strip() and str(story_id).strip() in valid_story_ids
                ]
                if not story_ids:
                    story_ids = self._story_ids_for_topic(topic, stories, limit=4)
                if topic == "SPORTS":
                    story_ids = self._filter_sports_story_ids(story_ids, stories)
                if not story_ids:
                    continue
                if not topic or (not summary and not why_it_matters):
                    continue
                if topic in seen_topics:
                    continue
                sections.append(
                    {
                        "topic": topic,
                        "title": title or self._topic_name(topic),
                        "summary": summary,
                        "why_it_matters": why_it_matters,
                        "story_ids": story_ids,
                    }
                )
                seen_topics.add(topic)
                if len(sections) >= 7:
                    break

        if self.sports_score_cards and "SPORTS" not in seen_topics:
            sports_story_ids = self._sports_story_ids(stories, limit=4)
            sections.append(
                {
                    "topic": "SPORTS",
                    "title": "Sports",
                    "summary": _trim_words(
                        " • ".join(
                            score.get("context_line") or score.get("display", "")
                            for score in self.sports_score_cards[:3]
                        ),
                        24,
                    ),
                    "why_it_matters": "ESPN-verified live and final context keeps the scoreboard dependable.",
                    "story_ids": sports_story_ids,
                }
            )
            seen_topics.add("SPORTS")

        for topic, group in self._topic_article_groups(articles).items():
            if topic in seen_topics or not group:
                continue
            related_stories = [
                story
                for story in stories
                if self._normalize_topic(story.get("topic")) == topic
            ]
            if not related_stories:
                continue
            story_ids = [story["id"] for story in related_stories[:4] if story.get("id")]
            sections.append(
                {
                    "topic": topic,
                    "title": self._topic_name(topic),
                    "summary": _trim_words(" • ".join(article.title for article in group[:3]), 24),
                    "why_it_matters": "Enough current signal to merit a dedicated scan.",
                    "story_ids": story_ids,
                }
            )
            seen_topics.add(topic)
            if len(sections) >= 7:
                break

        return self._sanitize_sections(sections, stories)[:8]

    def _sanitize_sections(
        self,
        sections: list[dict[str, Any]],
        stories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        valid_story_ids = {str(story.get("id")) for story in stories if story.get("id")}
        cleaned_sections: list[dict[str, Any]] = []
        seen_topics: set[str] = set()

        for section in sections:
            topic = self._normalize_topic(section.get("topic"))
            if not topic or topic in seen_topics:
                continue
            story_ids = [
                str(story_id).strip()
                for story_id in section.get("story_ids", [])
                if str(story_id).strip() in valid_story_ids
            ]
            if topic == "SPORTS":
                story_ids = self._filter_sports_story_ids(story_ids, stories)
            if not story_ids:
                story_ids = self._story_ids_for_topic(topic, stories, limit=4)
                if topic == "SPORTS":
                    story_ids = self._filter_sports_story_ids(story_ids, stories)
            elif topic == "TOP_NEWS" and len(story_ids) < 2:
                for story_id in self._story_ids_for_topic(topic, stories, limit=4):
                    if story_id not in story_ids:
                        story_ids.append(story_id)
                    if len(story_ids) >= 2:
                        break
            if not story_ids and not (topic == "SPORTS" and self.sports_score_cards):
                continue
            cleaned = dict(section)
            cleaned["topic"] = topic
            cleaned["story_ids"] = story_ids
            cleaned_sections.append(cleaned)
            seen_topics.add(topic)

        return cleaned_sections

    @staticmethod
    def _story_image_url(image_url: str | None) -> str | None:
        candidate = str(image_url or "").strip()
        if candidate and ArticleFetcher._is_valid_image_url(candidate):
            return candidate
        return None

    @classmethod
    def _grounded_top_level_copy(
        cls,
        *,
        payload: dict[str, Any],
        stories: list[dict[str, Any]],
        grounding_texts: list[str] | None = None,
    ) -> tuple[str, str, str, list[str]]:
        raw_headline = payload.get("headline") or ""
        raw_dek = payload.get("dek") or ""
        raw_summary = payload.get("summary") or ""
        headline = _trim_words_plain(raw_headline, 10)
        dek = _trim_words(raw_dek, 22)
        summary = _trim_words(raw_summary, 70)
        quick_hits = _trim_items(payload.get("quick_hits", []), max_items=6, max_words=14)

        derived_dek, derived_summary, derived_quick_hits = cls._top_level_copy_from_stories(stories)
        if (
            cls._is_generic_headline(headline)
            or cls._is_unpolished_copy(headline)
            or cls._has_visible_truncation(raw_headline)
            or not cls._copy_is_grounded_in_stories(
                headline,
                stories,
                grounding_texts=grounding_texts,
            )
        ):
            headline = cls._headline_from_stories(stories)
        if (
            not dek
            or cls._is_unpolished_copy(dek)
            or cls._has_visible_truncation(raw_dek)
            or not cls._copy_is_grounded_in_stories(dek, stories, grounding_texts=grounding_texts)
        ):
            dek = derived_dek
        if (
            not summary
            or cls._is_unpolished_copy(summary)
            or cls._has_visible_truncation(raw_summary)
            or not cls._copy_is_grounded_in_stories(
                summary,
                stories,
                grounding_texts=grounding_texts,
            )
        ):
            summary = derived_summary
        if not quick_hits or any(
            cls._is_unpolished_copy(hit)
            or cls._has_visible_truncation(hit)
            or not cls._copy_is_grounded_in_stories(hit, stories, grounding_texts=grounding_texts)
            for hit in quick_hits
        ):
            quick_hits = derived_quick_hits

        return headline, dek, summary, quick_hits

    @classmethod
    def _top_level_copy_from_stories(
        cls,
        stories: list[dict[str, Any]],
    ) -> tuple[str, str, list[str]]:
        titles = [_clean_text(story.get("title")) for story in stories if story.get("title")]
        if len(titles) >= 2:
            dek = _trim_words(f"{titles[0]} leads alongside {titles[1]}.", 22)
        elif titles:
            dek = _trim_words(titles[0], 22)
        else:
            dek = "A compact scan of today's strongest verified stories."

        sentences: list[str] = []
        for story in stories[:6]:
            sentence = _clean_text(story.get("summary") or story.get("title"))
            if not sentence:
                continue
            sentences.append(cls._ensure_sentence(sentence))
            summary = _trim_words(" ".join(sentences), 70)
            if _word_count(summary) >= 45:
                break

        summary = _trim_words(" ".join(sentences), 70)
        if _word_count(summary) < 45 and titles:
            title_sentences = [cls._ensure_sentence(title) for title in titles[:6]]
            summary = _trim_words(" ".join(sentences + title_sentences), 70)
        if not summary:
            summary = _trim_words(" ".join(titles[:6]), 70)

        quick_hits = [
            _trim_words_plain(title, 14)
            for title in titles[:6]
            if _trim_words_plain(title, 14)
        ]
        return dek, summary, quick_hits

    @staticmethod
    def _ensure_sentence(value: str) -> str:
        text = _collapse_visible_truncation(_clean_text(value)).rstrip()
        if not text:
            return ""
        if text[-1] in ".!?":
            return text
        return f"{text}."

    @classmethod
    def _copy_is_grounded_in_stories(
        cls,
        text: Any,
        stories: list[dict[str, Any]],
        *,
        grounding_texts: list[str] | None = None,
    ) -> bool:
        terms = cls._entity_terms(text)
        if not terms:
            return True

        corpus_parts: list[str] = []
        for story in stories:
            corpus_parts.extend(
                str(story.get(key) or "")
                for key in ("topic", "title", "source", "summary", "why_it_matters", "url")
            )
        corpus_parts.extend(grounding_texts or [])
        corpus = " ".join(corpus_parts)
        corpus_terms = cls._entity_terms(corpus)
        corpus_tokens = {
            re.sub(r"[^a-z0-9]+", "", token)
            for token in re.findall(r"\b[\w'-]+\b", corpus.lower())
        }
        corpus_tokens.discard("")
        return all(term in corpus_terms or term in corpus_tokens for term in terms)

    @staticmethod
    def _entity_terms(text: Any) -> set[str]:
        normalized = (
            str(text or "")
            .replace("U.S.", "US")
            .replace("U.K.", "UK")
            .replace("U.N.", "UN")
        )
        terms: set[str] = set()
        for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9'-]{2,}|[A-Z]{2,})\b", normalized):
            term = re.sub(r"[^a-z0-9]+", "", match.group(0).lower())
            if term and term not in TOP_LEVEL_COPY_ENTITY_STOPWORDS:
                terms.add(term)
        return terms

    @classmethod
    def _headline_from_stories(cls, stories: list[dict[str, Any]]) -> str:
        for story in stories:
            title = _trim_words_plain(story.get("title"), 10)
            if title and not cls._is_generic_headline(title):
                return title
        return "BriefSnap current news"

    @staticmethod
    def _is_generic_headline(headline: str | None) -> bool:
        normalized = re.sub(r"\W+", " ", str(headline or "").lower()).strip()
        return normalized in {
            "",
            "daily brief",
            "today s brief",
            "today s news",
            "top news",
            "useful daily brief",
            "briefsnap daily brief",
        }

    @staticmethod
    def _has_visible_truncation(text: Any) -> bool:
        return bool(re.search(r"\.{3,}|…", str(text or "")))

    @staticmethod
    def _is_unpolished_copy(text: Any) -> bool:
        cleaned = _clean_text(text)
        if not cleaned:
            return True
        lowered = cleaned.lower()
        if any(marker in lowered for marker in BOILERPLATE_COPY_MARKERS):
            return True
        if DailyBriefPipeline._has_visible_truncation(cleaned):
            return True
        if cleaned[-1:] in {",", ":", ";", "-", "–", "—"}:
            return True
        words = cleaned.split()
        if not words:
            return True
        last_word = re.sub(r"[^a-z0-9']+", "", words[-1].lower())
        return last_word in DANGLING_COPY_ENDINGS

    @staticmethod
    def _hero_image_url(stories: list[dict[str, Any]]) -> str | None:
        if not stories:
            return None
        image_url = str(stories[0].get("image_url") or "").strip()
        if image_url and ArticleFetcher._is_valid_image_url(image_url):
            return image_url
        return None

    @staticmethod
    def _sports_scores_metadata(score_cards: list[dict[str, Any]]) -> dict[str, Any]:
        if not score_cards:
            return {}

        verified_times: list[datetime] = []
        for score in score_cards:
            if not isinstance(score, dict):
                continue
            verified_at = str(score.get("verified_at") or "").strip()
            if not verified_at:
                continue
            try:
                verified_times.append(datetime.fromisoformat(verified_at.replace("Z", "+00:00")).astimezone(timezone.utc))
            except ValueError:
                continue

        refreshed_at = max(verified_times) if verified_times else datetime.now(timezone.utc)
        return {
            "sports_scores_refreshed_at": refreshed_at.isoformat(),
            "sports_scores_verified_at": refreshed_at.isoformat(),
            "sports_scores_source": "ESPN",
        }

    @staticmethod
    def _archive_stale_firestore_scores() -> int:
        try:
            from newsaggregator.storage.sports_storage import SportsStorage

            archived = SportsStorage.archive_stale_final_scores()
        except Exception as exc:
            print(f"[WARN] Stale final score cleanup skipped: {exc}")
            return 0

        if archived:
            print(f"Archived {archived} stale Firestore final score(s)")
        return archived

    @classmethod
    def _coverage_report(
        cls,
        *,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate] | None = None,
        sections: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        articles = articles or []
        sections = sections or []
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

        article_domains = [cls._domain_name(article.url) for article in articles if article.url]
        story_domains = [
            cls._domain_name(str(story.get("url") or ""))
            for story in stories
            if story.get("url")
        ]
        leading_stories = stories[: min(8, len(stories))]
        leading_domains = [
            cls._domain_name(str(story.get("url") or ""))
            for story in leading_stories
            if story.get("url")
        ]
        topic_counts = Counter(cls._normalize_topic(article.topic) for article in articles if article.topic)
        story_topic_counts = Counter(cls._normalize_topic(story.get("topic")) for story in stories if story.get("topic"))
        leading_domain_counts = Counter(domain for domain in leading_domains if domain)
        leading_ages = [
            age
            for age in (cls._story_age_hours(story, now=now) for story in leading_stories)
            if age is not None
        ]

        return {
            "source_packet_count": len(articles),
            "source_packet_domains": len(set(article_domains)),
            "trusted_source_packet_count": sum(
                1 for article in articles if cls._is_trusted_domain(cls._domain_name(article.url))
            ),
            "story_count": len(stories),
            "story_domains": len(set(story_domains)),
            "leading_story_domains": len(set(leading_domains)),
            "leading_trusted_story_count": sum(
                1
                for story in leading_stories
                if cls._is_trusted_domain(cls._domain_name(str(story.get("url") or "")))
            ),
            "max_leading_domain_count": max(leading_domain_counts.values(), default=0),
            "story_image_count": sum(
                1
                for story in stories
                if ArticleFetcher._is_valid_image_url(str(story.get("image_url") or ""))
            ),
            "sports_story_count": story_topic_counts.get("SPORTS", 0),
            "topic_counts": dict(sorted(topic_counts.items())),
            "story_topic_counts": dict(sorted(story_topic_counts.items())),
            "section_topics": [
                cls._normalize_topic(section.get("topic"))
                for section in sections
                if section.get("topic")
            ],
            "dated_leading_story_count": len(leading_ages),
            "stale_leading_story_count": sum(
                1 for age in leading_ages if age > MAX_STALE_LEADING_STORY_HOURS
            ),
        }

    def _fetch_top_sports_scores(self) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc)
        verified_at = today.isoformat()
        dates = [
            (today - timedelta(days=1)).strftime("%Y%m%d"),
            today.strftime("%Y%m%d"),
        ]
        games: list[dict[str, Any]] = []

        for league, path in SPORT_SCORE_ENDPOINTS:
            for date in dates:
                url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
                try:
                    response = self.session.get(url, params={"dates": date, "limit": 80}, timeout=10)
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    print(f"[WARN] ESPN scoreboard fetch failed for {league} {date}: {exc}")
                    continue

                for event in payload.get("events", []) or []:
                    parsed = self._parse_score_event(
                        league=league,
                        event=event,
                        source_url=response.url,
                        verified_at=verified_at,
                    )
                    if parsed and self._score_card_is_displayable(parsed, today):
                        games.append(parsed)

        deduped: dict[str, dict[str, Any]] = {}
        for game in games:
            deduped[game["id"]] = game

        sorted_games = sorted(deduped.values(), key=self._score_card_sort_key)
        selected: list[dict[str, Any]] = []
        league_counts: dict[str, int] = {}
        for game in sorted_games:
            league = str(game.get("league") or "")
            if league_counts.get(league, 0) >= 2:
                continue
            selected.append(game)
            league_counts[league] = league_counts.get(league, 0) + 1
            if len(selected) == 6:
                return selected

        seen_ids = {game.get("id") for game in selected}
        for game in sorted_games:
            if game.get("id") in seen_ids:
                continue
            selected.append(game)
            if len(selected) == 6:
                break
        return selected

    @staticmethod
    def _parse_score_event(
        league: str,
        event: dict[str, Any],
        source_url: str = "",
        verified_at: str = "",
    ) -> dict[str, Any] | None:
        competitions = event.get("competitions") or []
        if not competitions:
            return None

        status = (event.get("status") or {}).get("type") or {}
        state = status.get("state") or ""
        completed = bool(status.get("completed"))
        detail = status.get("shortDetail") or status.get("detail") or status.get("description") or "Scheduled"
        competition = competitions[0]
        competitors = competition.get("competitors") or []
        venue_data = competition.get("venue") or {}
        broadcasts = competition.get("broadcasts") or []

        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if not home or not away:
            return None

        def team(item: dict[str, Any]) -> dict[str, Any]:
            team_data = item.get("team") or {}
            raw_score = item.get("score")
            score = int(raw_score) if state != "pre" and str(raw_score).isdigit() else None
            records = item.get("records") or []
            record = ""
            for record_item in records:
                record = record_item.get("summary") or record
                if record:
                    break
            curated_rank = item.get("curatedRank") or {}
            rank = curated_rank.get("current") or item.get("rank")
            try:
                if rank and int(rank) > 99:
                    rank = None
            except (TypeError, ValueError):
                rank = None
            return {
                "name": team_data.get("displayName") or team_data.get("name") or "",
                "abbreviation": team_data.get("abbreviation") or "",
                "short_name": team_data.get("shortDisplayName") or team_data.get("shortName") or "",
                "score": score,
                "winner": item.get("winner"),
                "record": record,
                "rank": rank,
                "logo": team_data.get("logo"),
            }

        home_team = team(home)
        away_team = team(away)
        has_score = home_team["score"] is not None and away_team["score"] is not None

        if has_score:
            display = (
                f"{away_team['abbreviation'] or away_team['name']} {away_team['score']} at "
                f"{home_team['abbreviation'] or home_team['name']} {home_team['score']}"
            )
        else:
            display = f"{away_team['name']} at {home_team['name']}"

        if detail:
            display = f"{display} ({detail})"

        winner = home_team if home_team["winner"] else away_team if away_team["winner"] else None
        if has_score and winner:
            loser = away_team if winner is home_team else home_team
            margin = abs(int(home_team["score"]) - int(away_team["score"]))
            result_note = f"{winner['abbreviation'] or winner['short_name'] or winner['name']} by {margin}"
            if margin == 0:
                result_note = "Tied"
            if completed or state == "post":
                context_line = (
                    f"{winner['abbreviation'] or winner['short_name'] or winner['name']} beat "
                    f"{loser['abbreviation'] or loser['short_name'] or loser['name']} by {margin}"
                )
            else:
                context_line = f"{winner['abbreviation'] or winner['short_name'] or winner['name']} leads by {margin}"
        elif has_score and home_team["score"] == away_team["score"]:
            result_note = "Tied"
            context_line = f"{away_team['abbreviation']} and {home_team['abbreviation']} tied"
        else:
            result_note = detail
            context_line = display

        venue = venue_data.get("fullName") or ""
        venue_city = (venue_data.get("address") or {}).get("city") or ""
        venue_state = (venue_data.get("address") or {}).get("state") or ""
        venue_location = ", ".join(part for part in (venue_city, venue_state) if part)
        broadcast = ""
        if broadcasts:
            names = [
                name
                for broadcast_item in broadcasts[:2]
                for name in ((broadcast_item.get("names") or [])[:1])
                if name
            ]
            broadcast = ", ".join(names)

        timestamp = None
        event_date = None
        if event.get("date"):
            try:
                event_date = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
                timestamp = event_date.timestamp()
            except ValueError:
                timestamp = None

        rank = 0 if state == "in" else 1 if state == "pre" else 2
        verified_dt = None
        if verified_at:
            try:
                verified_dt = datetime.fromisoformat(verified_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                verified_dt = None
        if state == "in" and verified_dt:
            expires_at = (verified_dt + timedelta(minutes=15)).isoformat()
        elif (completed or state == "post") and event_date:
            expires_at = (event_date + POSTGAME_SCORE_TTL).isoformat()
        elif event_date:
            expires_at = (event_date + timedelta(minutes=30)).isoformat()
        else:
            expires_at = None
        raw_event_id = event.get("id") or hashlib.sha1(
            f"{league}:{event.get('name')}:{event.get('date')}".encode("utf-8")
        ).hexdigest()[:12]

        return {
            "id": f"{league.lower()}-{raw_event_id}",
            "league": league,
            "source": "ESPN",
            "source_url": source_url,
            "verified_at": verified_at,
            "event_date": event_date.isoformat() if event_date else event.get("date"),
            "expires_at": expires_at,
            "event_id": str(raw_event_id),
            "name": event.get("name") or f"{away_team['name']} at {home_team['name']}",
            "status": detail,
            "state": state,
            "is_live": state == "in",
            "is_final": completed or state == "post",
            "home_team": home_team,
            "away_team": away_team,
            "display": display,
            "context_line": context_line,
            "result_note": result_note,
            "venue": venue,
            "venue_location": venue_location,
            "broadcast": broadcast,
            "timestamp": timestamp,
            "rank": rank,
        }

    @staticmethod
    def _score_card_is_displayable(score: dict[str, Any], now: datetime | None = None) -> bool:
        if not isinstance(score, dict):
            return False

        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires_at = score.get("expires_at")
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                return expires_dt.astimezone(timezone.utc) > now
            except ValueError:
                return False

        return bool(score.get("is_live") or score.get("is_final"))

    @staticmethod
    def _score_card_sort_key(score: dict[str, Any]) -> tuple[int, int, float]:
        timestamp = score.get("timestamp") or 0
        try:
            timestamp_value = float(timestamp)
        except (TypeError, ValueError):
            timestamp_value = 0

        league = str(score.get("league") or "").upper()
        league_priority = SPORT_SCORE_LEAGUE_PRIORITY.get(league, 99)
        state = str(score.get("state") or "").lower()
        if score.get("is_live") or state == "in":
            return (0, league_priority, -timestamp_value)
        if state == "pre":
            return (1, league_priority, timestamp_value)
        return (2, league_priority, -timestamp_value)

    def _brief_quality_issues(self, brief: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        model_used = str(brief.get("model_used") or "").lower()
        stories = [story for story in brief.get("stories", []) if isinstance(story, dict)]
        sections = [section for section in brief.get("sections", []) if isinstance(section, dict)]
        valid_story_ids = {str(story.get("id")) for story in stories if story.get("id")}

        if (model_used == "dry-run" or "fallback" in model_used) and not self.options.allow_fallback_publish:
            issues.append(f"model_used is backup output ({brief.get('model_used')})")
        if len(stories) < 6:
            issues.append(f"only {len(stories)} stories normalized")

        normalized_titles = {
            re.sub(r"\W+", " ", str(story.get("title") or "").lower()).strip()
            for story in stories
            if story.get("title")
        }
        if len(normalized_titles) < min(6, len(stories)):
            issues.append("stories are not distinct enough")
        for index, story in enumerate(stories):
            if any(
                self._stories_are_near_duplicates(story, prior)
                for prior in stories[:index]
            ):
                issues.append("stories include near-duplicate coverage")
                break

        story_domains: list[str] = []
        story_image_count = 0
        for story in stories:
            story_id = str(story.get("id") or "<unknown>").strip()
            url = str(story.get("url") or "").strip()
            parsed_url = urlparse(url)
            domain = self._domain_name(url) if url else ""
            if domain:
                story_domains.append(domain)
            if not url:
                issues.append(f"story {story_id} missing url")
            elif parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                issues.append(f"story {story_id} has invalid url")
            elif domain.endswith("news.google.com"):
                issues.append(f"story {story_id} still uses Google News wrapper URL")

            image_url = str(story.get("image_url") or "").strip()
            if image_url and ArticleFetcher._is_valid_image_url(image_url):
                story_image_count += 1
            elif image_url:
                issues.append(f"story {story_id} image_url is not suitable for story art")

            if self._normalize_topic(story.get("topic")) == "SPORTS":
                if not self._is_high_signal_sports_candidate(
                    title=str(story.get("title") or ""),
                    source=str(story.get("source") or ""),
                    url=url,
                    description=" ".join(
                        str(story.get(key) or "")
                        for key in ("summary", "why_it_matters")
                    ),
                ):
                    issues.append(f"sports story {story_id} failed sports relevance gate")
            elif self._is_low_value_candidate(
                title=str(story.get("title") or ""),
                topic_code=str(story.get("topic") or ""),
                source=str(story.get("source") or ""),
                url=url,
                description=" ".join(
                    str(story.get(key) or "")
                    for key in ("summary", "why_it_matters")
                ),
            ):
                issues.append(f"story {story_id} failed editorial value gate")
            if any(
                "&nbsp;" in str(story.get(key) or "") or "\xa0" in str(story.get(key) or "")
                for key in ("title", "summary", "why_it_matters")
            ):
                issues.append(f"story {story_id} contains HTML entities")
            if any(self._has_visible_truncation(story.get(key)) for key in ("title", "summary", "why_it_matters")):
                issues.append(f"story {story_id} contains visible truncation")
            if any(self._is_unpolished_copy(story.get(key)) for key in ("title", "summary", "why_it_matters")):
                issues.append(f"story {story_id} has clipped copy")

        leading_domain_count = len(set(story_domains[: min(len(story_domains), 8)]))
        if len(stories) >= 8 and leading_domain_count < 4:
            issues.append("leading stories need at least four distinct source domains")
        elif len(stories) >= 6 and leading_domain_count < 3:
            issues.append("leading stories need at least three distinct source domains")

        leading_stories = stories[: min(8, len(stories))]
        leading_domains = [
            self._domain_name(str(story.get("url") or ""))
            for story in leading_stories
            if story.get("url")
        ]
        leading_domain_counts = Counter(leading_domains)
        overrepresented_domains = [
            domain
            for domain, count in leading_domain_counts.items()
            if domain and count > MAX_LEADING_STORIES_PER_DOMAIN
        ]
        if overrepresented_domains:
            issues.append(
                "leading stories overrepresent a single source domain: "
                + ", ".join(sorted(overrepresented_domains))
            )

        trusted_leading_count = sum(
            1
            for story in leading_stories
            if self._is_trusted_domain(self._domain_name(str(story.get("url") or "")))
        )
        if len(stories) >= 6 and trusted_leading_count < min(MIN_LEADING_TRUSTED_STORIES, len(leading_stories)):
            issues.append("leading stories need more trusted primary or established sources")

        visible_topics = {
            self._normalize_topic(story.get("topic"))
            for story in stories[: min(12, len(stories))]
            if story.get("topic")
        }
        visible_topics.discard("")
        if len(stories) >= 6 and len(visible_topics) < MIN_VISIBLE_STORY_TOPICS:
            issues.append("visible stories need broader topic coverage")

        coverage = brief.get("coverage_report") if isinstance(brief.get("coverage_report"), dict) else {}
        if coverage:
            source_packet_count = int(coverage.get("source_packet_count") or brief.get("source_count") or 0)
            source_packet_domains = int(coverage.get("source_packet_domains") or 0)
            if source_packet_count < MIN_V8_SOURCE_PACKET_COUNT:
                issues.append(
                    f"source packet is too thin for V8 coverage: {source_packet_count}"
                )
            if source_packet_domains < MIN_V8_SOURCE_PACKET_DOMAINS:
                issues.append(
                    f"source packet needs broader domain coverage: {source_packet_domains}"
                )

            source_topic_counts = {
                self._normalize_topic(topic): int(count or 0)
                for topic, count in (coverage.get("topic_counts") or {}).items()
            }
            supported_topics = [
                topic
                for topic in TOPIC_PRIORITY
                if source_topic_counts.get(topic, 0) >= self._minimum_sources_for_topic(topic)
            ]
            visible_supported_topics = [
                topic for topic in supported_topics if topic in visible_topics
            ]
            target_supported_topics = min(MIN_V8_VISIBLE_STORY_TOPICS, len(supported_topics))
            if (
                target_supported_topics
                and len(visible_supported_topics) < target_supported_topics
            ):
                missing_topics = [
                    topic for topic in supported_topics if topic not in visible_topics
                ][:4]
                issues.append(
                    "visible stories miss source-supported coverage lanes: "
                    + ", ".join(missing_topics)
                )
            if (
                (source_topic_counts.get("HEALTH", 0) or source_topic_counts.get("SCIENCE", 0))
                and not ({"HEALTH", "SCIENCE"} & visible_topics)
            ):
                issues.append("visible stories need at least one health or science item when supported")
            for required_topic in ("HEALTH", "SCIENCE"):
                if (
                    source_topic_counts.get(required_topic, 0) >= self._minimum_sources_for_topic(required_topic)
                    and required_topic not in visible_topics
                ):
                    issues.append(
                        "visible stories need a "
                        + required_topic.lower()
                        + " item when source-supported"
                    )

        if stories[:3] and not any(
            self._normalize_topic(story.get("topic")) == "TOP_NEWS"
            for story in stories[:3]
        ):
            issues.append("one of the first three stories must be TOP_NEWS")

        leading_topic_counts = Counter(
            self._normalize_topic(story.get("topic"))
            for story in stories[: min(8, len(stories))]
            if story.get("topic")
        )
        crowded_topics = [
            topic
            for topic, count in leading_topic_counts.items()
            if topic != "TOP_NEWS" and count > 2
        ]
        if crowded_topics:
            issues.append("leading stories overrepresent a topic: " + ", ".join(sorted(crowded_topics)))

        leading_ages = [
            age
            for age in (self._story_age_hours(story) for story in leading_stories)
            if age is not None
        ]
        stale_leading_count = sum(1 for age in leading_ages if age > MAX_STALE_LEADING_STORY_HOURS)
        if len(leading_ages) >= 3 and stale_leading_count >= max(3, len(leading_ages) // 2):
            issues.append("too many leading stories are stale")

        hero_image_url = str(brief.get("hero_image_url") or "").strip()
        lead_image_url = str(stories[0].get("image_url") or "").strip() if stories else ""
        if lead_image_url and not hero_image_url:
            issues.append("lead story has art but hero_image_url is missing")
        elif hero_image_url and not ArticleFetcher._is_valid_image_url(hero_image_url):
            issues.append("hero_image_url is not suitable for story art")
        elif hero_image_url and hero_image_url != lead_image_url:
            issues.append("hero_image_url must come from the lead story")
        if len(stories) >= 6 and story_image_count < 2:
            issues.append("leading stories need at least two image_url values")

        thin_summaries = [
            story
            for story in stories[:8]
            if len(str(story.get("summary") or "").strip()) < 40
        ]
        if len(thin_summaries) > 2:
            issues.append("too many leading stories have thin summaries")

        headline = str(brief.get("headline") or "").strip()
        if self._is_generic_headline(headline):
            issues.append("headline is generic")
        if headline.endswith("..."):
            issues.append("headline is visibly truncated")
        top_level_copy = [
            brief.get("headline"),
            brief.get("dek"),
            brief.get("summary"),
            *brief.get("quick_hits", []),
        ]
        if any("&nbsp;" in str(item) or "\xa0" in str(item) for item in top_level_copy if item):
            issues.append("top-level brief copy contains HTML entities")
        if any(self._has_visible_truncation(item) for item in top_level_copy if item):
            issues.append("top-level brief copy contains visible truncation")
        if any(self._is_unpolished_copy(item) for item in top_level_copy if item):
            issues.append("top-level brief copy has clipped phrasing")
        if any(
            not self._copy_is_grounded_in_stories(item, stories)
            for item in top_level_copy
            if item
        ):
            issues.append("top-level brief copy includes unsupported named entities")
        if _word_count(brief.get("summary")) > 85:
            issues.append("summary is too long for the one-minute brief")
        verbose_hits = [
            hit
            for hit in brief.get("quick_hits", [])
            if _word_count(hit) > 18
        ]
        if verbose_hits:
            issues.append("quick hits exceed the brief word budget")
        verbose_story_copy = [
            story
            for story in stories[:8]
            if _word_count(story.get("summary")) > 28 or _word_count(story.get("why_it_matters")) > 24
        ]
        if verbose_story_copy:
            issues.append("leading stories are too verbose")

        section_topics = [self._normalize_topic(section.get("topic")) for section in sections]
        if "TOP_NEWS" not in section_topics:
            issues.append("missing TOP_NEWS section")
        sports_story_ids = self._sports_story_ids(stories, limit=4)
        if brief.get("sports_scores") and not sports_story_ids:
            issues.append("sports desk needs at least one sports news story")

        for section in sections:
            topic = self._normalize_topic(section.get("topic"))
            story_ids = [
                str(story_id).strip()
                for story_id in section.get("story_ids", [])
                if str(story_id).strip()
            ]
            valid_refs = [story_id for story_id in story_ids if story_id in valid_story_ids]
            if topic == "SPORTS" and self.sports_score_cards:
                continue
            if len(valid_refs) == 0:
                issues.append(f"{topic or 'UNKNOWN'} section has no valid story_ids")

        top_sections = [
            section
            for section in sections
            if self._normalize_topic(section.get("topic")) == "TOP_NEWS"
        ]
        if top_sections:
            top_refs = [
                str(story_id).strip()
                for story_id in top_sections[0].get("story_ids", [])
                if str(story_id).strip() in valid_story_ids
            ]
            if len(top_refs) < 2:
                issues.append("TOP_NEWS section needs at least two real story references")

        if self.sports_score_cards and not brief.get("sports_scores"):
            issues.append("sports scores were fetched but omitted from the brief")
        if brief.get("sports_scores"):
            if brief.get("sports_scores_source") != "ESPN":
                issues.append("sports scores missing top-level ESPN source metadata")
            if not brief.get("sports_scores_refreshed_at"):
                issues.append("sports scores missing top-level refreshed_at timestamp")
            if not brief.get("sports_scores_verified_at"):
                issues.append("sports scores missing top-level verified_at timestamp")
        for score in brief.get("sports_scores", []):
            if not isinstance(score, dict):
                issues.append("sports score entry is not an object")
                continue
            score_id = str(score.get("id") or "").strip()
            league = str(score.get("league") or "").strip()
            if not score_id:
                issues.append("sports score missing id")
            if league not in {league for league, _ in SPORT_SCORE_ENDPOINTS}:
                issues.append(f"sports score {score_id or '<unknown>'} has unsupported league {league or '<blank>'}")
            if score.get("source") != "ESPN" or not score.get("source_url"):
                issues.append(f"sports score {score_id or '<unknown>'} missing ESPN source metadata")
            if not score.get("verified_at"):
                issues.append(f"sports score {score_id or '<unknown>'} missing verified_at")
            for side in ("away_team", "home_team"):
                team = score.get(side)
                if not isinstance(team, dict):
                    issues.append(f"sports score {score_id or '<unknown>'} missing {side}")
                    continue
                if not (team.get("abbreviation") or team.get("name")):
                    issues.append(f"sports score {score_id or '<unknown>'} missing {side} identity")
                if score.get("state") != "pre" and team.get("score") is None:
                    issues.append(f"sports score {score_id or '<unknown>'} missing {side} score")

        return issues

    @classmethod
    def _story_ids_for_topic(
        cls,
        topic: str,
        stories: list[dict[str, Any]],
        limit: int = 4,
    ) -> list[str]:
        normalized_topic = cls._normalize_topic(topic)
        if normalized_topic == "TOP_NEWS":
            candidates = stories
        else:
            candidates = [
                story
                for story in stories
                if cls._normalize_topic(story.get("topic")) == normalized_topic
            ]
        return [str(story["id"]) for story in candidates[:limit] if story.get("id")]

    @classmethod
    def _sports_story_ids(cls, stories: list[dict[str, Any]], limit: int = 4) -> list[str]:
        story_ids = [
            str(story["id"])
            for story in stories
            if cls._normalize_topic(story.get("topic")) == "SPORTS" and story.get("id")
        ]
        return cls._filter_sports_story_ids(story_ids, stories)[:limit]

    @classmethod
    def _filter_sports_story_ids(
        cls,
        story_ids: list[str],
        stories: list[dict[str, Any]],
    ) -> list[str]:
        stories_by_id = {str(story.get("id")): story for story in stories if story.get("id")}
        filtered: list[str] = []
        for story_id in story_ids:
            story = stories_by_id.get(str(story_id))
            if not story:
                continue
            if cls._is_high_signal_sports_candidate(
                title=str(story.get("title") or ""),
                source=str(story.get("source") or ""),
                url=str(story.get("url") or ""),
                description=" ".join(
                    str(story.get(key) or "")
                    for key in ("summary", "why_it_matters")
                ),
            ):
                filtered.append(str(story_id))
        return filtered

    @classmethod
    def _is_high_signal_sports_candidate(
        cls,
        *,
        title: str,
        source: str,
        url: str,
        description: str = "",
    ) -> bool:
        text = f"{title} {source} {description}".lower()
        domain = cls._domain_name(url)
        is_primary_sports_source = (
            any(domain.endswith(sports_domain) for sports_domain in PRIMARY_SPORTS_DOMAINS)
            or cls._sports_path_signal(url)
        )
        has_sports_signal = cls._contains_any_term(text, SPORTS_SIGNAL_TERMS)
        has_section_drift = cls._contains_any_term(text, SPORTS_SECTION_DRIFT_TERMS)

        if has_section_drift and not (is_primary_sports_source or has_sports_signal):
            return False
        return is_primary_sports_source or has_sports_signal

    @staticmethod
    def _sports_path_signal(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        path = parsed.path.lower()
        sports_markers = (
            "/athletic/",
            "/sports/",
            "/sport/",
            "/nba/",
            "/wnba/",
            "/mlb/",
            "/nhl/",
            "/nfl/",
            "/mls/",
            "/soccer/",
            "/college-football/",
            "/college-basketball/",
        )
        return any(marker in path for marker in sports_markers)

    @staticmethod
    def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
        for term in terms:
            if " " in term:
                if term in text:
                    return True
                continue
            if re.search(rf"\b{re.escape(term)}\b", text):
                return True
        return False

    def _normalize_widgets(
        self,
        raw_widgets: Any,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
    ) -> list[dict[str, Any]]:
        widgets: list[dict[str, Any]] = []
        seen_topics: set[str] = set()

        if isinstance(raw_widgets, list):
            for widget in raw_widgets:
                if not isinstance(widget, dict):
                    continue
                topic = _clean_text(widget.get("topic"))
                title = _trim_words(widget.get("title"), 5)
                summary = _trim_words(widget.get("summary"), 24)
                items = _trim_items(widget.get("items", []), max_items=5, max_words=12)
                if not topic or (not summary and not items):
                    continue
                if topic in seen_topics:
                    continue
                widgets.append(
                    {
                        "topic": topic,
                        "title": title or self._topic_name(topic),
                        "summary": summary,
                        "items": items,
                    }
                )
                seen_topics.add(topic)
                if len(widgets) >= 8:
                    return widgets

        for topic, group in self._topic_article_groups(articles).items():
            if topic in seen_topics or not group:
                continue
            related_stories = [story for story in stories if story.get("topic") == topic]
            items = [story["title"] for story in related_stories[:4] if story.get("title")]
            if not items:
                items = [article.title for article in group[:4]]
            summary = ""
            if related_stories:
                summary = str(related_stories[0].get("summary") or "").strip()
            if not summary:
                summary = (group[0].description or group[0].content[:220] or "Latest selected updates.").strip()
            widgets.append(
                {
                    "topic": topic,
                    "title": self._topic_name(topic),
                    "summary": _trim_words(summary, 24),
                    "items": _trim_items(items, max_items=5, max_words=12),
                }
            )
            seen_topics.add(topic)
            if len(widgets) >= 8:
                break

        return widgets

    @staticmethod
    def _topic_article_groups(articles: list[ArticleCandidate]) -> dict[str, list[ArticleCandidate]]:
        groups: dict[str, list[ArticleCandidate]] = {}
        preferred_order = {topic.code: index for index, topic in enumerate(TOPICS)}
        for article in sorted(articles, key=lambda item: item.score, reverse=True):
            group = groups.setdefault(article.topic, [])
            if len(group) < 5:
                group.append(article)
        return dict(
            sorted(
                groups.items(),
                key=lambda item: (
                    preferred_order.get(item[0], len(preferred_order)),
                    -sum(article.score for article in item[1]),
                ),
            )
        )

    @staticmethod
    def _should_retry_generation(exc: Exception) -> bool:
        text = str(exc).upper()
        return any(
            marker in text
            for marker in (
                "UNAVAILABLE",
                "RESOURCE_EXHAUSTED",
                "DEADLINE_EXCEEDED",
                "INTERNAL",
                "503",
                "504",
                "429",
            )
        )

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise

    def write_artifact(self, brief: dict[str, Any]) -> Path:
        path = BRIEF_DIR / f"daily_brief_{self.today_id}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(brief, handle, indent=2, ensure_ascii=False)
        return path

    def publish_firestore(self, brief: dict[str, Any]) -> None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred_obj = self._firebase_credentials()
            firebase_admin.initialize_app(cred_obj)

        db = firestore.client()
        payload = dict(brief)
        generated_at = self._parse_iso(payload["generated_at"])
        payload["generated_at"] = generated_at
        for story in payload.get("stories", []):
            if story.get("published_at"):
                try:
                    story["published_at"] = self._parse_iso(story["published_at"])
                except Exception:
                    story["published_at"] = None
        for timestamp_field in ("sports_scores_refreshed_at", "sports_scores_verified_at"):
            if payload.get(timestamp_field):
                try:
                    payload[timestamp_field] = self._parse_iso(str(payload[timestamp_field]))
                except Exception:
                    payload.pop(timestamp_field, None)

        doc_id = payload["id"]
        db.collection("daily_briefs").document(doc_id).set(payload)
        db.collection("daily_brief_history").document(doc_id).set(payload)
        self._publish_legacy_summary(db, payload)
        self._refresh_custom_widget_requests(db, payload)
        print(f"Published daily brief to Firestore document daily_briefs/{doc_id}")

    def refresh_latest_firestore_sports_scores(self) -> dict[str, Any]:
        import firebase_admin
        from firebase_admin import firestore

        if not firebase_admin._apps:
            cred_obj = self._firebase_credentials()
            firebase_admin.initialize_app(cred_obj)

        db = firestore.client()
        self._archive_stale_firestore_scores()
        score_cards = self._fetch_top_sports_scores()[:6]
        refreshed_at = datetime.now(timezone.utc)

        latest_docs = list(
            db.collection("daily_briefs")
            .order_by("generated_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if not latest_docs:
            return {
                "success": False,
                "error": "No daily_briefs documents found",
                "scores_count": len(score_cards),
            }

        doc = latest_docs[0]
        metadata = self._sports_scores_metadata(score_cards)
        update_payload = {
            "sports_scores": score_cards,
            **metadata,
            "sports_scores_refreshed_at": refreshed_at,
            "sports_scores_source": "ESPN",
        }
        if update_payload.get("sports_scores_verified_at"):
            update_payload["sports_scores_verified_at"] = self._parse_iso(str(update_payload["sports_scores_verified_at"]))
        doc.reference.set(update_payload, merge=True)
        db.collection("daily_brief_history").document(doc.id).set(update_payload, merge=True)

        return {
            "success": True,
            "doc_id": doc.id,
            "scores_count": len(score_cards),
            "refreshed_at": refreshed_at.isoformat(),
            "verified_at": metadata.get("sports_scores_verified_at"),
        }

    def _refresh_custom_widget_requests(self, db: Any, brief: dict[str, Any]) -> None:
        if not self.gemini_key:
            print("[WARN] GEMINI_API_KEY missing; custom widget refresh skipped")
            return

        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            requests_query = (
                db.collection("custom_widget_requests")
                .where(filter=FieldFilter("active", "==", True))
                .limit(self.options.max_custom_widget_requests)
                .stream()
            )
            requests = list(requests_query)
        except Exception as exc:
            print(f"[WARN] Could not load custom widget requests: {exc}")
            return

        if not requests:
            print("No active custom widget requests to refresh")
            return

        client = genai.Client(
            api_key=self.gemini_key,
            http_options={
                "timeout": int(os.environ.get("BRIEFSNAP_WIDGET_GEMINI_TIMEOUT_MS", "30000"))
            },
        )
        refreshed = 0
        for request_doc in requests:
            data = request_doc.to_dict() or {}
            prompt = str(data.get("prompt") or data.get("description") or "").strip()
            if len(prompt) < 4:
                continue
            try:
                widget = self._generate_custom_widget(client, prompt, data, brief)
                now = datetime.now(timezone.utc)
                request_doc.reference.set(
                    {
                        "latest_widget": widget,
                        "latest_title": widget["title"],
                        "latest_summary": widget["summary"],
                        "latest_items": widget["items"],
                        "latest_generated_at": now,
                        "latest_model_used": widget["model_used"],
                        "status": "ready",
                        "error_message": None,
                        "updated_at": now,
                    },
                    merge=True,
                )
                db.collection("custom_widget_history").document(
                    f"{request_doc.id}_{self.today_id}"
                ).set(
                    {
                        "request_id": request_doc.id,
                        "device_id": data.get("device_id"),
                        "prompt": prompt,
                        "widget": widget,
                        "generated_at": now,
                    }
                )
                refreshed += 1
            except Exception as exc:
                now = datetime.now(timezone.utc)
                request_doc.reference.set(
                    {
                        "status": "error",
                        "error_message": str(exc)[:500],
                        "updated_at": now,
                    },
                    merge=True,
                )
                print(f"[WARN] Custom widget {request_doc.id} failed: {exc}")

        print(f"Refreshed {refreshed} custom widget request(s)")

    def _generate_custom_widget(
        self,
        client: Any,
        prompt: str,
        request_data: dict[str, Any],
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        context_stories = [
            {
                "title": story.get("title"),
                "source": story.get("source"),
                "summary": story.get("summary"),
            }
            for story in brief.get("stories", [])[:8]
        ]
        requested_title = str(request_data.get("title") or "").strip()
        generated_at = datetime.now(timezone.utc).isoformat()
        widget_prompt = f"""
Create one BriefSnap custom news widget for a user-defined topic.

User request:
{prompt}

Existing daily brief context:
{json.dumps(context_stories, ensure_ascii=False)}

Rules:
- Use Google Search for current facts.
- Keep it concise and scannable for a phone widget. Every word must earn its place.
- Include only facts that are relevant to the user's request.
- If the request is too broad, choose the most important current angle.
- Return JSON with title, summary, and 3 to 5 short items.
- title: 5 words max. summary: 24 words max. items: 12 words max each.
- Avoid filler, generic caveats, markdown, and phrases like "continues to unfold".
- Do not mention that you used Search.

Preferred title, if useful: {requested_title or "none"}
Generated at: {generated_at}
""".strip()

        configs = (
            (
                GROUNDING_MODEL,
                {
                    "tools": [{"google_search": {}}],
                    "response_mime_type": "application/json",
                    "response_json_schema": CUSTOM_WIDGET_SCHEMA,
                    "max_output_tokens": 2048,
                    "temperature": 0.25,
                },
                "search-grounded",
            ),
            (
                DEFAULT_MODEL,
                {
                    "tools": [{"google_search": {}}],
                    "max_output_tokens": 2048,
                    "temperature": 0.25,
                },
                "search-grounded-text",
            ),
            (
                DEFAULT_MODEL,
                {
                    "response_mime_type": "application/json",
                    "response_json_schema": CUSTOM_WIDGET_SCHEMA,
                    "max_output_tokens": 2048,
                    "temperature": 0.25,
                },
                "source-packet",
            ),
        )

        last_error: Exception | None = None
        for model, config, mode in configs:
            for attempt in range(1, 3):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=widget_prompt,
                        config=config,
                    )
                    payload = self._parse_json_response(response.text)
                    title = _trim_words(payload.get("title") or requested_title or prompt[:48], 5)
                    summary = _trim_words(payload.get("summary") or "", 24)
                    items = _trim_items(payload.get("items", []), max_items=5, max_words=12)
                    if not summary and not items:
                        raise RuntimeError("Gemini returned an empty custom widget")
                    return {
                        "topic": "CUSTOM",
                        "title": title[:80],
                        "summary": summary[:280],
                        "items": items,
                        "prompt": prompt,
                        "model_used": f"{model}-{mode}",
                    }
                except Exception as exc:
                    last_error = exc
                    if attempt < 2 and self._should_retry_generation(exc):
                        time.sleep(2 * attempt)
                        continue
                    break

        raise RuntimeError(f"Gemini custom widget failed after retries: {last_error}")

    def _publish_legacy_summary(self, db: Any, brief: dict[str, Any]) -> None:
        stories = []
        for story in brief.get("stories", [])[:10]:
            stories.append(
                {
                    "id": story.get("id"),
                    "StoryTitle": story.get("title"),
                    "StoryDescription": story.get("summary"),
                    "FullArticle": story.get("why_it_matters"),
                    "Citations": [story.get("url")] if story.get("url") else [],
                    "img_url": story.get("image_url"),
                }
            )

        legacy = {
            "topic": "TOP_NEWS",
            "summary": brief.get("summary", ""),
            "brief_summary": brief.get("dek") or brief.get("summary", ""),
            "bullet_points": brief.get("quick_hits", [])[:5],
            "timestamp": brief["generated_at"],
            "Stories": stories,
            "model_used": brief.get("model_used"),
        }
        db.collection("news_summaries").document(f"TOP_NEWS_{brief['id']}").set(legacy)

    def _firebase_credentials(self) -> Any:
        from firebase_admin import credentials

        inline = os.environ.get("FIREBASE_CREDENTIALS")
        if inline:
            return credentials.Certificate(json.loads(inline))

        path = os.environ.get("FIREBASE_CREDENTIALS_PATH") or str(BASE_DIR / "firebase-credentials.json")
        if not Path(path).exists():
            raise RuntimeError(
                "Firebase credentials not found. Set FIREBASE_CREDENTIALS or "
                "FIREBASE_CREDENTIALS_PATH."
            )
        return credentials.Certificate(path)

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        cleaned = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _google_news_search_url(query: str) -> str:
        return (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
        )

    @staticmethod
    def _entry_source(entry: Any, fallback: str) -> str:
        source = entry.get("source")
        if isinstance(source, dict):
            return source.get("title") or fallback
        if hasattr(source, "title"):
            return source.title
        return fallback

    @staticmethod
    def _entry_date(entry: Any) -> str | None:
        for key in ("published", "updated", "created"):
            value = entry.get(key)
            if value:
                try:
                    return parsedate_to_datetime(value).isoformat()
                except Exception:
                    return value
        return None

    @staticmethod
    def _clean_html(raw: str) -> str:
        text = html.unescape(raw or "")
        text = re.sub(r"(?:\s*\xa0\s*){2,}", " | ", text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"<[^>]+>", " ", text)
        return _clean_text(text)

    @classmethod
    def _clean_title(cls, value: Any, *, source: str = "") -> str:
        title = _clean_text(value)
        source_names = {
            _clean_text(source),
            "AP News",
            "Associated Press",
            "Reuters",
            "NPR",
            "The Verge",
            "TechCrunch",
            "CNBC",
            "BBC",
            "Washington Post",
            "The New York Times",
        }
        for source_name in sorted((name for name in source_names if name), key=len, reverse=True):
            title = re.sub(
                rf"\s+(?:-|\u2013|\u2014|\|)\s*{re.escape(source_name)}\s*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()
        return title

    @classmethod
    def _clean_description(cls, value: Any, *, title: str = "", source: str = "") -> str:
        text = cls._clean_html(str(value or ""))
        if not text:
            return ""

        segments = [segment.strip() for segment in re.split(r"\s+\|\s+", text) if segment.strip()]
        if len(segments) > 1 and title and cls._same_title_fragment(segments[0], title):
            return ""

        cleaned_title = _clean_text(title)
        cleaned_source = _clean_text(source)
        if cleaned_title and text.lower().startswith(cleaned_title.lower()):
            text = text[len(cleaned_title):].strip(" -|.;:")
        if cleaned_source and text.lower().startswith(cleaned_source.lower()):
            text = text[len(cleaned_source):].strip(" -|.;:")

        cleaned = _clean_text(text)
        lowered = cleaned.lower()
        if any(marker in lowered for marker in BOILERPLATE_COPY_MARKERS):
            return ""
        return cleaned

    @staticmethod
    def _same_title_fragment(left: Any, right: Any) -> bool:
        left_key = re.sub(r"\W+", " ", _clean_text(left).lower()).strip()
        right_key = re.sub(r"\W+", " ", _clean_text(right).lower()).strip()
        if not left_key or not right_key:
            return False
        return left_key == right_key or left_key.startswith(right_key) or right_key.startswith(left_key)

    @staticmethod
    def _normalize_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed_original = urlparse(url)
        if "news.google.com" in parsed_original.netloc:
            query_url = parse_qs(parsed_original.query).get("url")
            cleaned = query_url[0] if query_url else url
        else:
            cleaned = url

        parsed = urlparse(cleaned)
        if not parsed.scheme or not parsed.netloc:
            return None
        parsed = parsed._replace(fragment="")
        query_parts = [
            part
            for part in parsed.query.split("&")
            if part and not part.startswith(("utm_", "fbclid=", "gclid="))
        ]
        parsed = parsed._replace(query="&".join(query_parts))
        return urlunparse(parsed)

    @staticmethod
    def _domain_name(url: str) -> str:
        host = urlparse(url).netloc.removeprefix("www.")
        return host.split(":")[0]

    @staticmethod
    def _is_trusted_domain(domain: str) -> bool:
        normalized = str(domain or "").lower().removeprefix("www.")
        return any(normalized.endswith(trusted) for trusted in TRUSTED_SOURCE_DOMAINS)

    @classmethod
    def _story_age_hours(cls, story: dict[str, Any], *, now: datetime | None = None) -> float | None:
        published_at = story.get("published_at")
        if not published_at:
            return None
        try:
            if isinstance(published_at, datetime):
                parsed = published_at
            else:
                parsed = cls._parse_iso(str(published_at))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return max(0.0, (reference - parsed.astimezone(timezone.utc)).total_seconds() / 3600)

    @staticmethod
    def _score_candidate(candidate: ArticleCandidate) -> float:
        score = 10
        title_lower = candidate.title.lower()
        if any(term in title_lower for term in ("live updates", "what to know", "latest")):
            score -= 1.5
        if any(term in title_lower for term in ("explainer", "analysis", "why it matters")):
            score += 1
        if candidate.description:
            score += 2
        if candidate.published_at:
            score += 2 + DailyBriefPipeline._recency_score(candidate.published_at)
        if candidate.image_url:
            score += 1
        domain = DailyBriefPipeline._domain_name(candidate.url)
        for trusted_domain, weight in TRUSTED_SOURCE_DOMAINS.items():
            if domain.endswith(trusted_domain):
                score += weight
                break
        trusted_sources = (
            "associated press",
            "ap news",
            "reuters",
            "abc news",
            "cbs news",
            "cnn",
            "npr",
            "the wall street journal",
            "wsj",
            "the new york times",
            "washington post",
            "the verge",
            "techcrunch",
            "cnbc",
        )
        if any(source in candidate.source.lower() for source in trusted_sources):
            score += 4
        if candidate.topic == "SPORTS":
            sports_text = f"{candidate.title} {candidate.description}".lower()
            if any(domain.endswith(sports_domain) for sports_domain in PRIMARY_SPORTS_DOMAINS):
                score += 5
            if DailyBriefPipeline._contains_any_term(sports_text, SPORTS_SIGNAL_TERMS):
                score += 3
            if DailyBriefPipeline._contains_any_term(sports_text, SPORTS_SECTION_DRIFT_TERMS):
                score -= 8
        if any(
            marker in title_lower
            for marker in (
                "horoscope",
                "lottery",
                "stock market today:",
                "fantasy football",
                "odds",
                "betting",
                "watch live",
            )
        ):
            score -= 5
        return score

    @staticmethod
    def _recency_score(published_at: str | None) -> float:
        if not published_at:
            return 0
        try:
            parsed = DailyBriefPipeline._parse_iso(published_at)
        except Exception:
            return 0
        hours_old = max(
            0.0,
            (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600,
        )
        if hours_old <= 6:
            return 3
        if hours_old <= 18:
            return 2
        if hours_old <= 36:
            return 1
        return -2

    @staticmethod
    def _is_low_value_title(title: str, topic_code: str) -> bool:
        lowered = title.lower()
        low_value = (
            "film festivals and markets calendar",
            "transfer news",
            "rumours and gossip",
            "injury tracker",
            "latest headlines - as",
            "horoscope",
        )
        if any(pattern in lowered for pattern in low_value):
            return True
        if topic_code in {"TOP_NEWS", "WORLD"} and any(
            pattern in lowered for pattern in ("world cup", "premier league", "arsenal")
        ):
            return True
        return False

    @classmethod
    def _is_low_value_candidate(
        cls,
        *,
        title: str,
        topic_code: str,
        source: str = "",
        url: str = "",
        description: str = "",
    ) -> bool:
        lowered_title = title.lower()
        lowered_source = source.lower()
        lowered_url = url.lower()
        text = f"{lowered_title} {lowered_source} {description.lower()}"
        domain = cls._domain_name(url)

        if cls._is_low_value_title(title, topic_code):
            return True
        if any(domain.endswith(blocked) for blocked in LOW_VALUE_SOURCE_DOMAINS):
            return True
        if any(marker in lowered_source for marker in LOW_VALUE_SOURCE_MARKERS):
            return True
        if any(marker in lowered_url for marker in LOW_VALUE_URL_MARKERS):
            return True
        if "press release" in text:
            return True
        if any(marker in lowered_title for marker in LOW_VALUE_TITLE_MARKERS):
            return True

        normalized_topic = cls._normalize_topic(topic_code)
        if normalized_topic == "TECHNOLOGY" and any(
            marker in lowered_title
            for marker in (
                "i put ",
                "hands-on:",
                "review:",
                "actually pretty useful",
                "huge sales hit",
                "this is the ",
            )
        ):
            return True
        if normalized_topic == "TECHNOLOGY" and (
            lowered_url.rstrip("/").endswith("/pictures")
            or "/pictures" in lowered_url
            or "/gallery" in lowered_url
        ):
            return True
        if normalized_topic == "BUSINESS" and (
            "techcrunch mobility:" in lowered_title
            or ("here are the" in lowered_title and "we're watching" in lowered_title)
            or ("here are the" in lowered_title and "we are watching" in lowered_title)
        ):
            return True
        if normalized_topic in {"BUSINESS", "TOP_NEWS"} and any(
            marker in lowered_title
            for marker in (
                "unruly passenger",
                "longest-serving flight attendant",
                "flight attendant prepares to retire",
                "pulls u-turn",
                "bluetooth device name",
            )
        ):
            return True
        if normalized_topic == "TOP_NEWS" and any(
            marker in lowered_title
            for marker in (
                "extramarital",
                "wife says",
                "family of four killed",
                "wedding. bus driver charged",
                "two biggest movies",
                "directed by youtubers",
            )
        ):
            return True
        if normalized_topic == "TOP_NEWS" and "bus crash" in lowered_title and "family" in lowered_title:
            return True
        if normalized_topic == "SPORTS" and (
            "/video/clip/" in lowered_url
            or "preview?gameid=" in lowered_url
            or any(
                marker in lowered_title
                for marker in (
                    "takes on ",
                    "seeks ",
                    "why stephen a.",
                    "trophy image",
                    "script logo",
                    "finals courts",
                    "court design",
                )
            )
        ):
            return True
        return False

    @classmethod
    def _classify_candidate_topic(
        cls,
        *,
        topic_code: str,
        title: str,
        source: str,
        url: str,
        description: str = "",
    ) -> str:
        normalized_topic = cls._normalize_topic(topic_code)
        if normalized_topic != "TOP_NEWS":
            return normalized_topic

        lowered_url = url.lower()
        text = f"{title} {source} {description} {lowered_url}".lower()
        path = urlparse(url).path.lower()

        if cls._is_high_signal_sports_candidate(
            title=title,
            source=source,
            url=url,
            description=description,
        ):
            return "SPORTS"
        if any(marker in path for marker in ("/technology/", "/tech/", "/ai-", "/cyber")) or cls._contains_any_term(
            text,
            (
                "ai",
                "chip",
                "chips",
                "nvidia",
                "software",
                "startup",
                "cybersecurity",
                "windows pc",
                "data centre",
                "data center",
            ),
        ):
            return "TECHNOLOGY"
        if any(marker in path for marker in ("/business/", "/finance/", "/markets/", "/economy/")) or cls._contains_any_term(
            text,
            (
                "market",
                "markets",
                "stocks",
                "earnings",
                "inflation",
                "tariff",
                "oil",
                "merger",
                "antitrust",
                "bank",
            ),
        ):
            return "BUSINESS"
        if any(marker in path for marker in ("/world/", "/middle-east/", "/europe/", "/asia/")) or cls._contains_any_term(
            text,
            (
                "china",
                "europe",
                "gaza",
                "iran",
                "israel",
                "japan",
                "nato",
                "russia",
                "ukraine",
            ),
        ):
            return "WORLD"
        if any(marker in path for marker in ("/health/", "/medicine/")) or cls._contains_any_term(
            text,
            ("cdc", "fda", "health", "hospital", "medicine", "virus", "vaccine"),
        ):
            return "HEALTH"
        if any(marker in path for marker in ("/science/", "/space/", "/climate/")) or cls._contains_any_term(
            text,
            ("climate", "meteor", "nasa", "research", "science", "space"),
        ):
            return "SCIENCE"
        if any(marker in path for marker in ("/culture/", "/entertainment/", "/style/")) or cls._contains_any_term(
            text,
            ("box office", "film", "movie", "movies", "music", "television", "youtubers"),
        ):
            return "ENTERTAINMENT"
        return normalized_topic

    @staticmethod
    def _dedupe(candidates: list[ArticleCandidate]) -> list[ArticleCandidate]:
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        result: list[ArticleCandidate] = []
        for candidate in candidates:
            url_key = candidate.url
            title_key = re.sub(r"\W+", " ", candidate.title.lower()).strip()
            title_key = " ".join(title_key.split()[:10])
            if url_key in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url_key)
            seen_titles.add(title_key)
            result.append(candidate)
        return result

    @staticmethod
    def _diversify_articles(
        articles: list[ArticleCandidate],
        *,
        limit: int,
    ) -> list[ArticleCandidate]:
        selected: list[ArticleCandidate] = []
        domain_counts: dict[str, int] = {}
        topic_counts: dict[str, int] = {}

        def can_take(article: ArticleCandidate, relaxed: bool = False) -> bool:
            domain = DailyBriefPipeline._domain_name(article.url)
            max_domain = MAX_ARTICLES_PER_DOMAIN + (2 if relaxed else 0)
            if domain_counts.get(domain, 0) >= max_domain:
                return False
            if not relaxed and topic_counts.get(article.topic, 0) >= 8:
                return False
            return True

        for article in articles:
            if len(selected) >= limit:
                break
            if not can_take(article):
                continue
            selected.append(article)
            domain = DailyBriefPipeline._domain_name(article.url)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            topic_counts[article.topic] = topic_counts.get(article.topic, 0) + 1

        if len(selected) < min(limit, len(articles)):
            selected_ids = {article.id for article in selected}
            for article in articles:
                if len(selected) >= limit:
                    break
                if article.id in selected_ids or not can_take(article, relaxed=True):
                    continue
                selected.append(article)
                selected_ids.add(article.id)
                domain = DailyBriefPipeline._domain_name(article.url)
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

        topic_minimums = (
            SOURCE_PACKET_TOPIC_MINIMUMS
            if limit >= 24
            else {"SPORTS": SOURCE_PACKET_TOPIC_MINIMUMS["SPORTS"]}
        )
        for topic, minimum in topic_minimums.items():
            selected = DailyBriefPipeline._ensure_minimum_topic_articles(
                selected,
                articles,
                topic=topic,
                minimum=minimum,
                limit=limit,
            )
        return selected

    @staticmethod
    def _ensure_minimum_topic_articles(
        selected: list[ArticleCandidate],
        articles: list[ArticleCandidate],
        *,
        topic: str,
        minimum: int,
        limit: int,
    ) -> list[ArticleCandidate]:
        selected_ids = {article.id for article in selected}
        normalized_topic = DailyBriefPipeline._normalize_topic(topic)
        existing_count = sum(
            1
            for article in selected
            if DailyBriefPipeline._normalize_topic(article.topic) == normalized_topic
        )
        if existing_count >= minimum:
            return selected

        for article in articles:
            if existing_count >= minimum:
                break
            if article.id in selected_ids or DailyBriefPipeline._normalize_topic(article.topic) != normalized_topic:
                continue
            if normalized_topic == "SPORTS" and not DailyBriefPipeline._is_high_signal_sports_candidate(
                title=article.title,
                source=article.source,
                url=article.url,
                description=article.description or article.content[:400],
            ):
                continue

            if len(selected) < limit:
                selected.append(article)
            else:
                replacement_index = DailyBriefPipeline._replacement_index_for_topic_minimum(
                    selected,
                    protected_topic=normalized_topic,
                )
                if replacement_index is None:
                    break
                selected_ids.discard(selected[replacement_index].id)
                selected[replacement_index] = article

            selected_ids.add(article.id)
            existing_count += 1

        return selected

    @staticmethod
    def _replacement_index_for_topic_minimum(
        selected: list[ArticleCandidate],
        *,
        protected_topic: str,
    ) -> int | None:
        for index in range(len(selected) - 1, -1, -1):
            topic = DailyBriefPipeline._normalize_topic(selected[index].topic)
            if topic not in {protected_topic, "TOP_NEWS"}:
                return index
        for index in range(len(selected) - 1, -1, -1):
            if DailyBriefPipeline._normalize_topic(selected[index].topic) != protected_topic:
                return index
        return None

    @staticmethod
    def _match_story(
        story: dict[str, Any],
        articles: list[ArticleCandidate],
    ) -> ArticleCandidate | None:
        url = story.get("url")
        if url:
            for article in articles:
                if article.url == url:
                    return article
        title = (story.get("title") or "").lower()
        for article in articles:
            if title and title[:40] in article.title.lower():
                return article
        return None

    @staticmethod
    def _topic_name(code: str) -> str:
        for topic in TOPICS:
            if topic.code == code:
                return topic.name
        return code.replace("_", " ").title()

    @staticmethod
    def _normalize_topic(value: Any) -> str:
        return re.sub(r"\s+", "_", str(value or "").strip()).upper()


def parse_args(argv: list[str] | None = None) -> PipelineOptions:
    parser = argparse.ArgumentParser(description="Generate the BriefSnap daily brief")
    parser.add_argument("--dry-run", action="store_true", help="Skip Gemini and Firestore")
    parser.add_argument("--skip-firestore", action="store_true", help="Do not publish to Firestore")
    parser.add_argument("--model", default=os.environ.get("BRIEFSNAP_GEMINI_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)
    return PipelineOptions(
        dry_run=args.dry_run,
        publish=not args.skip_firestore,
        model=args.model,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    DailyBriefPipeline(options).run()
    return 0
