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

SPORT_SCORE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("NBA", "basketball/nba"),
    ("MLB", "baseball/mlb"),
    ("NHL", "hockey/nhl"),
    ("MLS", "soccer/usa.1"),
)

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

Rules:
- Use the supplied source packet as the main evidence.
- Use Google Search to verify recency, importance, and any fast-moving claim.
- Do not invent URLs. Use article ids and URLs from the source packet when you
  select stories.
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
            "sports_scores": self.sports_score_cards[:6],
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
            "sports_scores": self.sports_score_cards[:6],
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
        valid_story_ids = {str(story.get("id")) for story in stories if story.get("id")}

        if isinstance(raw_sections, list):
            for section in raw_sections:
                if not isinstance(section, dict):
                    continue
                topic = self._normalize_topic(section.get("topic"))
                title = str(section.get("title") or "").strip()
                summary = str(section.get("summary") or "").strip()
                why_it_matters = str(section.get("why_it_matters") or "").strip()
                story_ids = [
                    str(story_id)
                    for story_id in section.get("story_ids", [])
                    if str(story_id).strip() and str(story_id).strip() in valid_story_ids
                ]
                if not story_ids:
                    story_ids = self._story_ids_for_topic(topic, stories, limit=4)
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
            sports_story_ids = [
                story["id"]
                for story in stories
                if self._normalize_topic(story.get("topic")) == "SPORTS" and story.get("id")
            ][:4]
            sections.append(
                {
                    "topic": "SPORTS",
                    "title": "Sports",
                    "summary": " • ".join(score["display"] for score in self.sports_score_cards[:3]),
                    "why_it_matters": "Live and final scoreboard context from ESPN.",
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

        return sections[:8]

    def _fetch_top_sports_scores(self) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc)
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
                    parsed = self._parse_score_event(league, event)
                    if parsed:
                        games.append(parsed)

        deduped: dict[str, dict[str, Any]] = {}
        for game in games:
            deduped[game["id"]] = game

        return sorted(
            deduped.values(),
            key=lambda game: (game["rank"], -(game.get("timestamp") or 0)),
        )[:6]

    @staticmethod
    def _parse_score_event(league: str, event: dict[str, Any]) -> dict[str, Any] | None:
        competitions = event.get("competitions") or []
        if not competitions:
            return None

        status = (event.get("status") or {}).get("type") or {}
        state = status.get("state") or ""
        completed = bool(status.get("completed"))
        detail = status.get("shortDetail") or status.get("detail") or status.get("description") or "Scheduled"
        competition = competitions[0]
        competitors = competition.get("competitors") or []

        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if not home or not away:
            return None

        def team(item: dict[str, Any]) -> dict[str, Any]:
            team_data = item.get("team") or {}
            raw_score = item.get("score")
            score = int(raw_score) if str(raw_score).isdigit() else None
            return {
                "name": team_data.get("displayName") or team_data.get("name") or "",
                "abbreviation": team_data.get("abbreviation") or "",
                "score": score,
                "winner": item.get("winner"),
            }

        home_team = team(home)
        away_team = team(away)
        has_score = home_team["score"] is not None and away_team["score"] is not None
        if state == "pre" and not has_score:
            return None

        if has_score:
            display = (
                f"{away_team['abbreviation'] or away_team['name']} {away_team['score']} at "
                f"{home_team['abbreviation'] or home_team['name']} {home_team['score']}"
            )
        else:
            display = f"{away_team['name']} at {home_team['name']}"

        if detail:
            display = f"{display} ({detail})"

        timestamp = None
        if event.get("date"):
            try:
                timestamp = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).timestamp()
            except ValueError:
                timestamp = None

        rank = 0 if state == "in" else 1 if completed or state == "post" else 2
        raw_event_id = event.get("id") or hashlib.sha1(
            f"{league}:{event.get('name')}:{event.get('date')}".encode("utf-8")
        ).hexdigest()[:12]

        return {
            "id": f"{league.lower()}-{raw_event_id}",
            "league": league,
            "name": event.get("name") or f"{away_team['name']} at {home_team['name']}",
            "status": detail,
            "state": state,
            "is_live": state == "in",
            "is_final": completed or state == "post",
            "home_team": home_team,
            "away_team": away_team,
            "display": display,
            "timestamp": timestamp,
            "rank": rank,
        }

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
        thin_summaries = [
            story
            for story in stories[:8]
            if len(str(story.get("summary") or "").strip()) < 40
        ]
        if len(thin_summaries) > 2:
            issues.append("too many leading stories have thin summaries")

        headline = str(brief.get("headline") or "").strip().lower()
        if not headline or headline in {"today's brief", "today's news", "top news"}:
            issues.append("headline is generic")

        section_topics = [self._normalize_topic(section.get("topic")) for section in sections]
        if "TOP_NEWS" not in section_topics:
            issues.append("missing TOP_NEWS section")

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

        doc_id = payload["id"]
        db.collection("daily_briefs").document(doc_id).set(payload)
        db.collection("daily_brief_history").document(doc_id).set(payload)
        self._publish_legacy_summary(db, payload)
        self._refresh_custom_widget_requests(db, payload)
        print(f"Published daily brief to Firestore document daily_briefs/{doc_id}")

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
- Keep it concise and scannable for a phone widget.
- Include only facts that are relevant to the user's request.
- If the request is too broad, choose the most important current angle.
- Return JSON with title, summary, and 3 to 5 short items.
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
                    title = str(payload.get("title") or requested_title or prompt[:48]).strip()
                    summary = str(payload.get("summary") or "").strip()
                    items = [
                        str(item).strip()
                        for item in payload.get("items", [])
                        if str(item).strip()
                    ][:5]
                    if not summary and not items:
                        raise RuntimeError("Gemini returned an empty custom widget")
                    return {
                        "topic": "CUSTOM",
                        "title": title[:80],
                        "summary": summary[:400],
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
