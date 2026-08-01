"""Configuration for the BriefSnap daily brief pipeline (V9).

Everything tunable lives here: sources, topics, ranking weights,
selection budgets, and copy limits. Env overrides use BRIEFSNAP_*.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Publishers
# --------------------------------------------------------------------------

# Domain -> tier weight. Tier drives ranking; consensus across distinct
# trusted domains is the primary importance signal.
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
    "ft.com": 8,
    "economist.com": 8,
    "cnbc.com": 7,
    "axios.com": 7,
    "politico.com": 7,
    "aljazeera.com": 7,
    "theguardian.com": 7,
    "cnn.com": 6,
    "abcnews.go.com": 6,
    "cbsnews.com": 6,
    "nbcnews.com": 6,
    "usatoday.com": 5,
    "time.com": 5,
    "arstechnica.com": 7,
    "theverge.com": 7,
    "techcrunch.com": 7,
    "wired.com": 7,
    "nature.com": 8,
    "science.org": 8,
    "quantamagazine.org": 7,
    "nasa.gov": 7,
    "statnews.com": 7,
    "espn.com": 7,
    "theathletic.com": 7,
    "cbssports.com": 6,
    "nbcsports.com": 6,
    "variety.com": 6,
    "hollywoodreporter.com": 6,
    "dw.com": 6,
    "france24.com": 6,
    "marketwatch.com": 6,
}

BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "prnewswire.com",
        "globenewswire.com",
        "businesswire.com",
        "accesswire.com",
        "naturalnews.com",
        "einpresswire.com",
        "newsfilecorp.com",
    }
)

# --------------------------------------------------------------------------
# Topics & feeds
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicSource:
    code: str
    name: str
    feeds: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = ()


def _google_topic(section: str) -> str:
    return (
        "https://news.google.com/rss/headlines/section/topic/"
        f"{section}?hl=en-US&gl=US&ceid=US:en"
    )


TOPICS: tuple[TopicSource, ...] = (
    TopicSource(
        code="TOP_NEWS",
        name="Top News",
        feeds=(
            "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
            "https://feeds.npr.org/1001/rss.xml",
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        ),
        search_queries=("major US headlines today",),
    ),
    TopicSource(
        code="WORLD",
        name="World",
        feeds=(
            _google_topic("WORLD"),
            "https://feeds.npr.org/1004/rss.xml",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://www.theguardian.com/world/rss",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ),
        search_queries=("major international news today",),
    ),
    TopicSource(
        code="BUSINESS",
        name="Business",
        feeds=(
            _google_topic("BUSINESS"),
            "https://feeds.npr.org/1006/rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://www.theguardian.com/us/business/rss",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        ),
        search_queries=("markets economy business news today",),
    ),
    TopicSource(
        code="TECHNOLOGY",
        name="Technology",
        feeds=(
            _google_topic("TECHNOLOGY"),
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://www.theguardian.com/technology/rss",
            "https://feeds.arstechnica.com/arstechnica/technology-lab",
            "https://www.theverge.com/rss/index.xml",
            "https://techcrunch.com/feed/",
            "https://www.wired.com/feed/rss",
        ),
        search_queries=("technology AI news today",),
    ),
    TopicSource(
        code="SCIENCE",
        name="Science",
        feeds=(
            _google_topic("SCIENCE"),
            "https://feeds.npr.org/1007/rss.xml",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://www.theguardian.com/science/rss",
            "https://www.nasa.gov/news-release/feed/",
            "https://www.nature.com/nature.rss",
        ),
        search_queries=("science space climate research news today",),
    ),
    TopicSource(
        code="HEALTH",
        name="Health",
        feeds=(
            _google_topic("HEALTH"),
            "https://feeds.npr.org/1128/rss.xml",
            "https://feeds.bbci.co.uk/news/health/rss.xml",
            "https://www.statnews.com/category/health/feed/",
            "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",
        ),
        search_queries=("health medicine public health news today",),
    ),
    TopicSource(
        code="SPORTS",
        name="Sports",
        feeds=(_google_topic("SPORTS"),),
        search_queries=(
            "NFL NBA MLB NHL WNBA trade injury playoff news today",
        ),
    ),
    TopicSource(
        code="ENTERTAINMENT",
        name="Culture",
        feeds=(
            _google_topic("ENTERTAINMENT"),
            "https://variety.com/feed/",
            "https://www.hollywoodreporter.com/feed/",
        ),
        search_queries=("entertainment culture media news today",),
    ),
)

TOPIC_PRIORITY: tuple[str, ...] = (
    "TOP_NEWS",
    "WORLD",
    "BUSINESS",
    "TECHNOLOGY",
    "SCIENCE",
    "HEALTH",
    "SPORTS",
    "ENTERTAINMENT",
)

TOPIC_NAMES: dict[str, str] = {t.code: t.name for t in TOPICS}

# --------------------------------------------------------------------------
# Screening
# --------------------------------------------------------------------------

LOW_VALUE_URL_MARKERS: tuple[str, ...] = (
    "/press-release/",
    "/press-releases/",
    "/press_release/",
    "/live/",
    "/liveblog/",
    "/live-blog/",
    "/live-news/",
    "/op-ed/",
    "/opinion/",
    "/opinions/",
    "/editorial/",
    "/editorials/",
    "/commentisfree/",
    "/audio/",
    "/podcast/",
    "/podcasts/",
    "/video/",
    "/videos/",
    "/gallery/",
    "/slideshow/",
    "/horoscope",
    "/crossword",
    "/recipes/",
    "/shopping/",
    "/deals/",
    "/coupons/",
    "coupon",
    "promo-code",
    "best-deals",
    "-sale-",
    "gift-guide",
    "buying-guide",
    "/betting/",
    "/odds/",
)

LOW_VALUE_TITLE_MARKERS: tuple[str, ...] = (
    "opinion:",
    "opinion |",
    "op-ed:",
    "editorial:",
    "guest essay",
    "live updates",
    "live blog",
    "live:",
    "what to know",
    "what we know",
    "here's what",
    "everything you need to know",
    "things to know",
    "takeaways from",
    "in photos",
    "in pictures",
    "photo essay",
    "watch:",
    "listen:",
    "podcast:",
    "horoscope",
    "lottery",
    "powerball",
    "mega millions",
    "best deals",
    "prime day",
    "black friday",
    "cyber monday",
    "promo code",
    "coupon",
    "discount code",
    "% off",
    "deal of the day",
    "deals and sales",
    "sale of the",
    "january deals",
    "february deals",
    "march deals",
    "april deals",
    "may deals",
    "june deals",
    "july deals",
    "august deals",
    "september deals",
    "october deals",
    "november deals",
    "december deals",
    "betting odds",
    "best bets",
    "parlay",
    "how to watch",
    "where to watch",
    "how major us stock indexes fared",
    "latest news",
    "news and intel",
    "rumors and",
    "tracker:",
    "announces pricing of",
    "reports fiscal",
    "to host conference call",
    "class action",
    "investor alert",
    "quiz:",
    "crossword",
    "wordle",
)

LOW_VALUE_DESCRIPTION_MARKERS: tuple[str, ...] = (
    "guest essay",
    "editorial board",
    "opinion column",
    "the views expressed",
    "rolling coverage",
    "transcript of",
    "sponsored content",
    "affiliate link",
    "earn a commission",
    "affiliate commission",
    "coupon",
    "subscription deal",
)

TRACKING_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "cmpid",
        "cid",
        "ref",
        "src",
        "smid",
        "ncid",
        "partner",
        "taid",
        "sref",
        "rss",
        "ftag",
    }
)

# Any query key starting with one of these prefixes is tracking noise.
TRACKING_QUERY_PREFIXES: tuple[str, ...] = ("utm_", "at_", "mc_", "ito", "cmp")

# Domain -> clean publisher display name (feed titles are messy:
# "NYT > Top Stories", "US Top News and Analysis", ...).
PUBLISHER_NAMES: dict[str, str] = {
    "apnews.com": "AP",
    "reuters.com": "Reuters",
    "npr.org": "NPR",
    "bbc.com": "BBC News",
    "bbc.co.uk": "BBC News",
    "wsj.com": "The Wall Street Journal",
    "nytimes.com": "The New York Times",
    "washingtonpost.com": "The Washington Post",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "economist.com": "The Economist",
    "cnbc.com": "CNBC",
    "axios.com": "Axios",
    "politico.com": "Politico",
    "aljazeera.com": "Al Jazeera",
    "theguardian.com": "The Guardian",
    "cnn.com": "CNN",
    "abcnews.go.com": "ABC News",
    "cbsnews.com": "CBS News",
    "nbcnews.com": "NBC News",
    "usatoday.com": "USA Today",
    "time.com": "TIME",
    "arstechnica.com": "Ars Technica",
    "theverge.com": "The Verge",
    "techcrunch.com": "TechCrunch",
    "wired.com": "Wired",
    "nature.com": "Nature",
    "science.org": "Science",
    "quantamagazine.org": "Quanta Magazine",
    "nasa.gov": "NASA",
    "statnews.com": "STAT",
    "espn.com": "ESPN",
    "theathletic.com": "The Athletic",
    "cbssports.com": "CBS Sports",
    "nbcsports.com": "NBC Sports",
    "variety.com": "Variety",
    "hollywoodreporter.com": "The Hollywood Reporter",
    "dw.com": "DW",
    "france24.com": "France 24",
    "marketwatch.com": "MarketWatch",
}

# --------------------------------------------------------------------------
# Clustering / ranking / selection
# --------------------------------------------------------------------------

CLUSTER_WINDOW_HOURS = _env_int("BRIEFSNAP_CLUSTER_WINDOW_HOURS", 48)
CLUSTER_SIMILARITY = float(os.environ.get("BRIEFSNAP_CLUSTER_SIMILARITY", "0.5"))

MAX_CANDIDATE_AGE_HOURS = _env_int("BRIEFSNAP_MAX_CANDIDATE_AGE_HOURS", 36)
MAX_ENTRIES_PER_FEED = _env_int("BRIEFSNAP_MAX_ENTRIES_PER_FEED", 25)

STORY_BUDGET = _env_int("BRIEFSNAP_STORY_BUDGET", 20)
MIN_PUBLISHABLE_STORIES = _env_int("BRIEFSNAP_MIN_PUBLISHABLE_STORIES", 10)
MAX_STORIES_PER_DOMAIN = _env_int("BRIEFSNAP_MAX_STORIES_PER_DOMAIN", 3)
MAX_STORIES_PER_TOPIC = _env_int("BRIEFSNAP_MAX_STORIES_PER_TOPIC", 5)
MIN_CLUSTER_SCORE = float(os.environ.get("BRIEFSNAP_MIN_CLUSTER_SCORE", "3.0"))

# Per-topic selection targets. Topics that lack strong clusters simply get
# fewer stories: the budget is a target, never a quota to pad.
TOPIC_TARGETS: dict[str, int] = {
    "TOP_NEWS": 4,
    "WORLD": 3,
    "BUSINESS": 3,
    "TECHNOLOGY": 3,
    "SCIENCE": 2,
    "HEALTH": 2,
    "SPORTS": 2,
    "ENTERTAINMENT": 1,
}

FETCH_WORKERS = _env_int("BRIEFSNAP_FETCH_WORKERS", 8)
SCRAPE_WORKERS = _env_int("BRIEFSNAP_SCRAPE_WORKERS", 8)

# --------------------------------------------------------------------------
# Writing (OpenRouter)
# --------------------------------------------------------------------------

# All AI requests go through OpenRouter (see llm.py). Web grounding for
# widgets/local topics uses the ":online" variant of the same model.
PRIMARY_MODEL = os.environ.get("BRIEFSNAP_MODEL") or "openai/gpt-5.6-luna"
FALLBACK_MODEL = os.environ.get("BRIEFSNAP_FALLBACK_MODEL") or "openai/gpt-5.6-luna-pro"
WIDGET_MODEL = os.environ.get("BRIEFSNAP_WIDGET_MODEL") or PRIMARY_MODEL
LLM_TIMEOUT_MS = _env_int("BRIEFSNAP_LLM_TIMEOUT_MS", 120_000)

# Copy limits enforced by the validation gate.
HEADLINE_WORDS = (4, 14)
DEK_WORDS = (10, 30)
SUMMARY_WORDS = (40, 110)
QUICK_HIT_WORDS = (6, 20)
QUICK_HITS_COUNT = (4, 6)
STORY_SUMMARY_WORDS = (10, 35)
WHY_IT_MATTERS_WORDS = (5, 26)
STORY_TITLE_WORDS = (3, 18)
MIN_SECTIONS = _env_int("BRIEFSNAP_MIN_SECTIONS", 4)

# Words a complete headline/quick hit must never end with (truncation guard).
DANGLING_END_WORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "after", "to", "of", "in",
        "on", "for", "with", "at", "by", "from", "as", "is", "are", "was",
        "were", "that", "its", "their", "his", "her", "over", "amid",
        "into", "about", "against", "than", "will", "has", "have", "be",
    }
)

BANNED_PHRASES: tuple[str, ...] = (
    "remains to be seen",
    "continues to unfold",
    "in a significant development",
    "in a major development",
    "sent shockwaves",
    "sparked debate",
    "raised concerns",
    "only time will tell",
    "the situation is developing",
    "stay tuned",
)
