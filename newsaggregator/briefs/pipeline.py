"""Daily brief pipeline focused on useful, lightweight output.

This module is intentionally independent from the older rotating article
manager. It gathers a compact, source-diverse packet of current articles,
asks Gemini for one structured daily brief, and publishes that contract for
the iOS app.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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

DEFAULT_MODEL = "gemini-3-flash-preview"
QUALITY_MODEL = "gemini-3.1-pro-preview"
FAST_MODEL = "gemini-3.1-flash-lite-preview"

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
            "url": self.url,
            "published_at": self.published_at,
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
        search_queries=("major sports news today", "NFL NBA MLB NHL news today"),
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
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.today_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def run(self) -> dict[str, Any]:
        start = time.time()
        BRIEF_DIR.mkdir(parents=True, exist_ok=True)
        print("====== BriefSnap Daily Brief Started ======")
        print(f"Model: {self.options.model}")

        articles = self.collect_articles()
        if not articles:
            raise RuntimeError("No article candidates survived discovery and extraction")

        if self.options.dry_run:
            brief = self._fallback_brief(articles, model_used="dry-run")
        else:
            brief = self.generate_brief(articles)

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
        enriched = self._enrich_articles(deduped[: self.options.max_total_articles])
        return sorted(enriched, key=lambda article: article.score, reverse=True)

    def _collect_topic(self, topic: TopicSource) -> list[ArticleCandidate]:
        raw: list[dict[str, Any]] = []
        for feed_url in topic.feeds:
            raw.extend(self._fetch_rss(feed_url, topic))
        for query in topic.search_queries:
            raw.extend(self._fetch_rss(self._google_news_search_url(query), topic))
        raw.extend(self._fetch_newsapi(topic))

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

    def _candidate_from_raw(self, item: dict[str, Any], topic: TopicSource) -> ArticleCandidate | None:
        title = (item.get("title") or "").strip()
        url = self._normalize_url(item.get("url"))
        if not title or len(title) < 12 or not url:
            return None
        if self._is_low_value_title(title, topic.code):
            return None

        stable = hashlib.sha1(f"{topic.code}:{url}".encode("utf-8")).hexdigest()[:16]
        return ArticleCandidate(
            id=stable,
            topic=topic.code,
            title=title,
            source=item.get("source") or self._domain_name(url),
            url=url,
            published_at=item.get("published_at"),
            description=(item.get("description") or "").strip(),
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
                if enriched_candidate.content or enriched_candidate.description:
                    enriched.append(enriched_candidate)

        return enriched

    def _scrape_candidate(self, candidate: ArticleCandidate) -> ArticleCandidate:
        if "news.google.com" in candidate.url:
            return candidate

        content, published = ArticleFetcher.scrape_article_content(candidate.url)
        if content:
            candidate.content = content
            candidate.score += min(len(content) / 1200, 8)
        if published and not candidate.published_at:
            candidate.published_at = published.isoformat()
        if not candidate.image_url:
            images = ArticleFetcher.find_article_images(candidate.url)
            if images:
                candidate.image_url = images[0]
        return candidate

    def generate_brief(self, articles: list[ArticleCandidate]) -> dict[str, Any]:
        if not self.gemini_key:
            raise RuntimeError("GEMINI_API_KEY is required for non-dry-run brief generation")

        prompt = self._brief_prompt(articles)
        client = genai.Client(
            api_key=self.gemini_key,
            http_options={
                "timeout": int(os.environ.get("BRIEFSNAP_GEMINI_TIMEOUT_MS", "75000"))
            },
        )
        models_to_try = []
        for model in (self.options.model, DEFAULT_MODEL, QUALITY_MODEL):
            if model not in models_to_try:
                models_to_try.append(model)

        last_error: Exception | None = None
        grounded_config = {
            "tools": [{"google_search": {}}],
            "response_mime_type": "application/json",
            "response_json_schema": ARTICLE_SCHEMA,
            "max_output_tokens": 8192,
            "temperature": 0.35,
        }
        for model in models_to_try:
            for attempt in range(1, 3):
                try:
                    print(f"Generating search-grounded structured brief with {model} (attempt {attempt})")
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=grounded_config,
                    )
                    payload = json.loads(response.text)
                    return self._normalize_brief(payload, articles, f"{model}-search-grounded")
                except Exception as exc:
                    print(f"[WARN] Gemini search-grounded model {model} failed: {exc}")
                    last_error = exc
                    if attempt >= 2 or not self._should_retry_generation(exc):
                        break
                    time.sleep(4 * attempt)

        for model in (DEFAULT_MODEL, FAST_MODEL):
            try:
                print(f"Generating structured source-packet brief with {model}")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": ARTICLE_SCHEMA,
                        "max_output_tokens": 8192,
                        "temperature": 0.35,
                    },
                )
                payload = json.loads(response.text)
                return self._normalize_brief(payload, articles, f"{model}-source-packet")
            except Exception as exc:
                print(f"[WARN] Gemini source-packet model {model} failed: {exc}")
                last_error = exc

        print(f"[WARN] Gemini unavailable; publishing source-ranked fallback brief: {last_error}")
        return self._fallback_brief(articles, model_used="source-ranked-fallback")

    def _brief_prompt(self, articles: list[ArticleCandidate]) -> str:
        records = [article.prompt_record() for article in articles]
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

Rules:
- Use the supplied source packet as the main evidence.
- Use Google Search to verify recency, importance, and any fast-moving claim.
- Do not invent URLs. Use article ids and URLs from the source packet when you
  select stories.
- Keep the prose crisp and useful. No hype, no generic caveats.
- Prefer US relevance for TOP_NEWS, but preserve important world context.
- The response must match the JSON schema exactly.
- Return at least five custom_widgets when the source packet supports them.

Generated at: {generated_at}

Source packet:
{json.dumps(records, ensure_ascii=False)}
""".strip()

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
            normalized_stories.append(
                {
                    "id": source_article.id,
                    "topic": story.get("topic") or source_article.topic,
                    "title": story.get("title") or source_article.title,
                    "source": story.get("source") or source_article.source,
                    "url": story.get("url") or source_article.url,
                    "summary": story.get("summary") or source_article.description,
                    "why_it_matters": story.get("why_it_matters") or "",
                    "urgency": story.get("urgency") or "medium",
                    "published_at": source_article.published_at,
                    "image_url": source_article.image_url,
                }
            )

        if len(normalized_stories) < 6:
            for article in articles:
                if article.id in story_ids:
                    continue
                story_ids.add(article.id)
                normalized_stories.append(
                    {
                        "id": article.id,
                        "topic": article.topic,
                        "title": article.title,
                        "source": article.source,
                        "url": article.url,
                        "summary": article.description or (article.content[:240] if article.content else ""),
                        "why_it_matters": "Selected as one of the strongest current stories in the source packet.",
                        "urgency": "medium",
                        "published_at": article.published_at,
                        "image_url": article.image_url,
                    }
                )
                if len(normalized_stories) >= 12:
                    break

        if len(normalized_stories) < 6:
            return self._fallback_brief(articles, model_used=model_used)

        now = datetime.now(timezone.utc)
        sections = self._normalize_sections(payload.get("sections", []), normalized_stories, articles)
        widgets = self._normalize_widgets(payload.get("custom_widgets", []), normalized_stories, articles)

        summary = str(payload.get("summary") or "").strip()
        quick_hits = [
            str(hit).strip()
            for hit in payload.get("quick_hits", [])
            if str(hit).strip()
        ]
        if not summary:
            summary = " ".join(story["title"] for story in normalized_stories[:4])
        if not quick_hits:
            quick_hits = [story["title"] for story in normalized_stories[:6]]

        brief = {
            "id": self.today_id,
            "generated_at": now.isoformat(),
            "model_used": model_used,
            "headline": payload.get("headline", "Today's Brief"),
            "dek": payload.get("dek", ""),
            "summary": summary,
            "quick_hits": quick_hits[:8],
            "sections": sections,
            "custom_widgets": widgets,
            "stories": normalized_stories[:18],
            "source_count": len(articles),
        }
        return brief

    def _fallback_brief(self, articles: list[ArticleCandidate], model_used: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        top = articles[:12]
        stories = [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "url": article.url,
                "summary": article.description or (article.content[:240] if article.content else ""),
                "why_it_matters": "Selected as one of the strongest current stories in the source packet.",
                "urgency": "medium",
                "published_at": article.published_at,
                "image_url": article.image_url,
            }
            for article in top
        ]
        return {
            "id": self.today_id,
            "generated_at": now.isoformat(),
            "model_used": model_used,
            "headline": "Today's Brief",
            "dek": "The most useful stories available from the current source packet.",
            "summary": " ".join(article.title for article in top[:4]),
            "quick_hits": [article.title for article in top[:6]],
            "sections": self._normalize_sections([], stories, articles),
            "custom_widgets": self._normalize_widgets([], stories, articles),
            "stories": stories,
            "source_count": len(articles),
        }

    def _normalize_sections(
        self,
        raw_sections: Any,
        stories: list[dict[str, Any]],
        articles: list[ArticleCandidate],
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        seen_topics: set[str] = set()

        if isinstance(raw_sections, list):
            for section in raw_sections:
                if not isinstance(section, dict):
                    continue
                topic = str(section.get("topic") or "").strip()
                title = str(section.get("title") or "").strip()
                summary = str(section.get("summary") or "").strip()
                why_it_matters = str(section.get("why_it_matters") or "").strip()
                story_ids = [
                    str(story_id)
                    for story_id in section.get("story_ids", [])
                    if str(story_id).strip()
                ]
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
                    return sections

        for topic, group in self._topic_article_groups(articles).items():
            if topic in seen_topics or not group:
                continue
            related_stories = [story for story in stories if story.get("topic") == topic]
            story_ids = [story["id"] for story in related_stories[:4] if story.get("id")]
            if not story_ids:
                story_ids = [article.id for article in group[:4]]
            sections.append(
                {
                    "topic": topic,
                    "title": self._topic_name(topic),
                    "summary": " • ".join(article.title for article in group[:3]),
                    "why_it_matters": "A compact view of current developments in this category.",
                    "story_ids": story_ids,
                }
            )
            seen_topics.add(topic)
            if len(sections) >= 7:
                break

        return sections

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
                topic = str(widget.get("topic") or "").strip()
                title = str(widget.get("title") or "").strip()
                summary = str(widget.get("summary") or "").strip()
                items = [
                    str(item).strip()
                    for item in widget.get("items", [])
                    if str(item).strip()
                ]
                if not topic or (not summary and not items):
                    continue
                if topic in seen_topics:
                    continue
                widgets.append(
                    {
                        "topic": topic,
                        "title": title or self._topic_name(topic),
                        "summary": summary,
                        "items": items[:5],
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
                    "summary": summary[:260],
                    "items": items[:5],
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

        doc_id = payload["id"]
        db.collection("daily_briefs").document(doc_id).set(payload)
        db.collection("daily_brief_history").document(doc_id).set(payload)
        self._publish_legacy_summary(db, payload)
        print(f"Published daily brief to Firestore document daily_briefs/{doc_id}")

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
        text = re.sub(r"<[^>]+>", " ", raw or "")
        return re.sub(r"\s+", " ", text).strip()

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
    def _score_candidate(candidate: ArticleCandidate) -> float:
        score = 10
        title_lower = candidate.title.lower()
        if any(term in title_lower for term in ("live updates", "what to know", "latest")):
            score += 1
        if candidate.description:
            score += 2
        if candidate.published_at:
            score += 2
        if candidate.image_url:
            score += 1
        trusted_domains = (
            "apnews.com",
            "reuters.com",
            "npr.org",
            "bbc.com",
            "wsj.com",
            "nytimes.com",
            "washingtonpost.com",
            "theverge.com",
            "techcrunch.com",
        )
        if any(domain in candidate.url for domain in trusted_domains):
            score += 4
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
        return score

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
