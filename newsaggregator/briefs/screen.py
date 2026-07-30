"""Screening: URL canonicalization, junk filtering, topic classification."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .config import (
    BLOCKED_DOMAINS,
    LOW_VALUE_DESCRIPTION_MARKERS,
    LOW_VALUE_TITLE_MARKERS,
    LOW_VALUE_URL_MARKERS,
    MAX_CANDIDATE_AGE_HOURS,
    PUBLISHER_NAMES,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
)
from .models import Candidate

_WHITESPACE = re.compile(r"\s+")

# Question-headline explainers ("What's the catch with...?") are evergreen
# content marketing, not the day's news.
_INTERROGATIVE_STARTS = (
    "what", "why", "how", "should", "is ", "are ", "can ", "could ", "do ",
    "does ", "will ", "would ", "who ", "when ", "where ",
)

# Signal terms used to reclassify a candidate that arrived via a generic
# feed (e.g. Google News top stories) into a more specific topic.
_TOPIC_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "SPORTS",
        (
            "nfl", "nba", "mlb", "nhl", "wnba", "mls", "ncaa", "playoff",
            "touchdown", "home run", "hat trick", "grand slam", "super bowl",
            "world series", "stanley cup", "quarterback", "coach fired",
        ),
    ),
    (
        "BUSINESS",
        (
            "stocks", "s&p 500", "nasdaq", "dow jones", "federal reserve",
            "interest rate", "inflation", "earnings", "ipo", "merger",
            "acquisition", "layoffs", "bankruptcy", "tariff", "gdp",
            "profits", "oil prices", "shareholders", "quarterly",
        ),
    ),
    (
        "TECHNOLOGY",
        (
            "openai", "anthropic", "google deepmind", "chatgpt", " ai model",
            "artificial intelligence", "iphone", "android", "chip", "semiconductor",
            "software", "cybersecurity", "data breach", "startup", "app store",
        ),
    ),
    (
        "HEALTH",
        (
            "fda", "cdc", "vaccine", "outbreak", "cancer", "clinical trial",
            "public health", "medicare", "medicaid", "hospital", "drug approval",
        ),
    ),
    (
        "SCIENCE",
        (
            "nasa", "spacex launch", "telescope", "climate", "asteroid",
            "fossil", "quantum", "physicists", "researchers found", "study finds",
            "species", "archaeolog",
        ),
    ),
    (
        "ENTERTAINMENT",
        (
            "box office", "album", "grammy", "oscar", "emmy", "netflix series",
            "movie review", "premiere", "celebrity", "billboard",
        ),
    ),
)


def canonical_url(url: str) -> str:
    """Normalize a URL for dedup: strip tracking params, fragments, mobile hosts."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url
    if parsed.scheme not in ("http", "https"):
        return url
    host = parsed.netloc.lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in TRACKING_QUERY_KEYS
        and not k.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", host, path, "", urlencode(query), ""))


def clean_text(value: str) -> str:
    """Collapse whitespace and strip common feed suffixes from titles."""
    text = _WHITESPACE.sub(" ", value or "").strip()
    # "Headline - Publisher" suffixes from Google News
    if " - " in text:
        head, _, tail = text.rpartition(" - ")
        if head and len(tail.split()) <= 5 and not tail[:1].islower():
            text = head.strip()
    return text


def is_junk(candidate: Candidate) -> str | None:
    """Return a rejection reason, or None if the candidate is acceptable."""
    url = candidate.url.lower()
    title = candidate.title.lower()
    description = candidate.description.lower()

    if not candidate.title or len(candidate.title) < 20:
        return "short-title"
    if len(candidate.title.split()) < 4:
        return "thin-title"
    if candidate.domain in BLOCKED_DOMAINS:
        return "blocked-domain"
    for marker in LOW_VALUE_URL_MARKERS:
        if marker in url:
            return f"url:{marker}"
    for marker in LOW_VALUE_TITLE_MARKERS:
        if marker in title:
            return f"title:{marker}"
    for marker in LOW_VALUE_DESCRIPTION_MARKERS:
        if marker in description:
            return f"description:{marker}"
    age = candidate.age_hours
    if age is not None and age > MAX_CANDIDATE_AGE_HOURS:
        return "stale"
    if title.count("?") >= 2:
        return "clickbait"
    if title.rstrip().endswith("?") and title.startswith(_INTERROGATIVE_STARTS):
        return "explainer"
    return None


def classify_topic(candidate: Candidate) -> str:
    """Reclassify generic-feed candidates using content signals."""
    haystack = f"{candidate.title} {candidate.description} {candidate.url}".lower()
    for topic, signals in _TOPIC_SIGNALS:
        hits = sum(1 for signal in signals if signal in haystack)
        if hits >= 2 or (hits == 1 and candidate.topic == "TOP_NEWS" and topic == "SPORTS"):
            # Sports drift out of top-news is the most common misfile.
            if candidate.topic in ("TOP_NEWS", topic):
                return topic
    return candidate.topic


def screen(candidates: list[Candidate]) -> tuple[list[Candidate], dict[str, int]]:
    """Filter junk and finalize topics. Returns (kept, rejection_counts)."""
    kept: list[Candidate] = []
    rejections: dict[str, int] = {}
    seen_urls: set[str] = set()

    for candidate in candidates:
        candidate.url = canonical_url(candidate.url)
        candidate.title = clean_text(candidate.title)
        candidate.description = clean_text(candidate.description)

        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)

        reason = is_junk(candidate)
        if reason:
            key = reason.split(":", 1)[0]
            rejections[key] = rejections.get(key, 0) + 1
            continue

        candidate.topic = classify_topic(candidate)
        candidate.source = publisher_name(candidate)
        kept.append(candidate)

    return kept, rejections


def publisher_name(candidate: Candidate) -> str:
    """Clean display name: domain map first, then a tidied feed title."""
    mapped = PUBLISHER_NAMES.get(candidate.domain)
    if mapped:
        return mapped
    name = candidate.source or candidate.domain
    for separator in (" – ", " — ", " > ", " | ", ": "):
        if separator in name:
            name = name.split(separator)[0]
    return name.strip()[:40]
