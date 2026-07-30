"""Feed gathering: RSS, Google News search, ESPN league news."""

from __future__ import annotations

import concurrent.futures
import email.utils
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import requests

from .config import FETCH_WORKERS, MAX_ENTRIES_PER_FEED, TOPICS
from .models import Candidate

_ESPN_NEWS_LEAGUES: tuple[tuple[str, str], ...] = (
    ("NFL", "football/nfl"),
    ("NBA", "basketball/nba"),
    ("MLB", "baseball/mlb"),
    ("NHL", "hockey/nhl"),
    ("WNBA", "basketball/wnba"),
    ("MLS", "soccer/usa.1"),
)


def _google_search_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
    )


def _parse_date(entry: dict) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    for key in ("published_parsed", "updated_parsed"):
        parsed_struct = entry.get(key)
        if parsed_struct:
            try:
                return datetime(*parsed_struct[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _entry_image(entry: dict) -> str:
    """Pull the largest media image from an RSS entry, skipping obvious thumbs."""
    best_url, best_width = "", 0
    for media in entry.get("media_content", []) or []:
        url = media.get("url") or ""
        if not url.startswith("http"):
            continue
        try:
            width = int(media.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        if width > best_width:
            best_url, best_width = url, width
    if best_width >= 400:
        return best_url
    for thumb in entry.get("media_thumbnail", []) or []:
        url = thumb.get("url") or ""
        if url.startswith("http"):
            return ""  # thumbnails are unreliable (author headshots); ignore
    return best_url if best_width >= 400 else ""


def _fetch_feed(session: requests.Session, feed_url: str, topic: str) -> list[Candidate]:
    try:
        response = session.get(feed_url, timeout=15)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        print(f"[WARN] Feed failed {feed_url}: {exc}")
        return []

    feed_title = (parsed.feed or {}).get("title", "") if parsed else ""
    candidates: list[Candidate] = []
    for entry in (parsed.entries or [])[:MAX_ENTRIES_PER_FEED]:
        url = entry.get("link") or ""
        title = entry.get("title") or ""
        if not url.startswith("http") or not title:
            continue
        source = ""
        source_info = entry.get("source")
        if isinstance(source_info, dict):
            source = source_info.get("title") or ""
        if not source:
            source = feed_title.split(" - ")[0].strip()
        summary = entry.get("summary") or entry.get("description") or ""
        # Google News wraps descriptions in HTML link lists; drop those.
        if "<a href" in summary:
            summary = ""
        candidates.append(
            Candidate(
                url=url,
                title=title,
                topic=topic,
                source=source,
                description=summary[:600],
                published_at=_parse_date(entry),
                image_url=_entry_image(entry),
                feed_url=feed_url,
            )
        )
    return candidates


def _fetch_espn_news(session: requests.Session) -> list[Candidate]:
    candidates: list[Candidate] = []
    for league, path in _ESPN_NEWS_LEAGUES:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/news"
        try:
            response = session.get(url, params={"limit": 5}, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"[WARN] ESPN news failed for {league}: {exc}")
            continue
        for article in payload.get("articles", []) or []:
            link = ((article.get("links") or {}).get("web") or {}).get("href") or ""
            title = article.get("headline") or ""
            if not link.startswith("http") or not title:
                continue
            published = None
            raw_date = article.get("published") or article.get("lastModified")
            if raw_date:
                try:
                    published = datetime.fromisoformat(
                        str(raw_date).replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    published = None
            images = article.get("images") or []
            image_url = images[0].get("url", "") if images else ""
            candidates.append(
                Candidate(
                    url=link,
                    title=title,
                    topic="SPORTS",
                    source="ESPN",
                    description=(article.get("description") or "")[:600],
                    published_at=published,
                    image_url=image_url,
                    feed_url=url,
                )
            )
    return candidates


def gather(session: requests.Session) -> list[Candidate]:
    """Fetch every configured feed in parallel. Feed failures are non-fatal."""
    jobs: list[tuple[str, str]] = []
    for topic in TOPICS:
        for feed in topic.feeds:
            jobs.append((feed, topic.code))
        for query in topic.search_queries:
            jobs.append((_google_search_url(query), topic.code))

    candidates: list[Candidate] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_feed, session, feed_url, topic_code): feed_url
            for feed_url, topic_code in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            candidates.extend(future.result())

    candidates.extend(_fetch_espn_news(session))
    print(f"Gathered {len(candidates)} raw candidates from {len(jobs) + 1} sources")
    return candidates
