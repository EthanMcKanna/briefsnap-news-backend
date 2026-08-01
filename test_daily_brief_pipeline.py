"""Tests for the V9 daily brief pipeline (curation + validation layers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from newsaggregator.briefs import rank
from newsaggregator.briefs.cluster import build_clusters, similarity, tokens
from newsaggregator.briefs.models import Candidate, Cluster
from newsaggregator.briefs.screen import canonical_url, clean_text, is_junk, screen
from newsaggregator.briefs.validate import validate_brief


def _candidate(
    title: str,
    url: str = "",
    topic: str = "TOP_NEWS",
    description: str = "",
    hours_old: float = 2.0,
    source: str = "",
) -> Candidate:
    return Candidate(
        url=url or f"https://example.com/{abs(hash(title))}",
        title=title,
        topic=topic,
        source=source,
        description=description,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_old),
    )


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------


def test_canonical_url_strips_tracking_params():
    url = "https://www.bbc.co.uk/news/articles/abc123?at_medium=RSS&at_campaign=rss&id=7"
    assert canonical_url(url) == "https://bbc.co.uk/news/articles/abc123?id=7"


def test_canonical_url_normalizes_mobile_hosts():
    assert canonical_url("http://m.example.com/story/") == "https://example.com/story"


def test_clean_text_strips_google_news_publisher_suffix():
    assert clean_text("Fed holds rates steady - Reuters") == "Fed holds rates steady"


def test_opinion_and_liveblog_urls_are_junk():
    opinion = _candidate("A completely reasonable article title here",
                         url="https://example.com/opinion/take")
    live = _candidate("Election results live updates and analysis today",
                      url="https://example.com/live/election")
    assert is_junk(opinion) is not None
    assert is_junk(live) is not None


def test_question_explainers_are_junk():
    explainer = _candidate("What's the catch with the Apple Upgrade program?")
    assert is_junk(explainer) == "explainer"


def test_affiliate_deals_content_is_junk():
    coupon = _candidate("Paramount+ coupon codes and August deals",
                        url="https://wired.com/story/paramount-plus-coupon-codes/")
    sale = _candidate("The best early Labor Day sales on laptops this weekend",
                      url="https://example.com/story/labor-day-sale-laptops")
    assert is_junk(coupon) is not None
    assert is_junk(sale) is not None


def test_stale_candidates_are_junk():
    stale = _candidate("A perfectly newsworthy title about important things", hours_old=50)
    assert is_junk(stale) == "stale"


def test_screen_dedupes_by_canonical_url():
    a = _candidate("Fed holds interest rates steady in July meeting",
                   url="https://example.com/fed?utm_source=rss")
    b = _candidate("Fed holds interest rates steady in July meeting",
                   url="https://www.example.com/fed/")
    kept, _ = screen([a, b])
    assert len(kept) == 1


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def test_same_story_across_outlets_clusters_together():
    a = _candidate(
        "China threatens retaliation as US moves to block robot imports",
        url="https://nytimes.com/robots",
        source="The New York Times",
    )
    b = _candidate(
        "US blocks Chinese robot imports, China threatens retaliation",
        url="https://bbc.com/robots",
        source="BBC News",
    )
    unrelated = _candidate(
        "NASA rover discovers honeycomb textures on Mars surface",
        url="https://nasa.gov/mars",
    )
    clusters = build_clusters([a, b, unrelated])
    sizes = sorted(len(c.members) for c in clusters)
    assert sizes == [1, 2]


def test_stemming_matches_plural_variants():
    assert similarity(tokens("robots imports banned"), tokens("robot import ban")) > 0.6


# ---------------------------------------------------------------------------
# Ranking / selection
# ---------------------------------------------------------------------------


def test_consensus_outranks_solo_story():
    consensus = Cluster(
        members=[
            _candidate("Major storm hits gulf coast tonight", url="https://apnews.com/storm"),
            _candidate("Gulf coast braces as major storm hits", url="https://reuters.com/storm"),
            _candidate("Major storm slams gulf coast region", url="https://bbc.com/storm"),
        ]
    )
    solo = Cluster(
        members=[_candidate("Small town opens a new library branch", url="https://example.com/lib")]
    )
    assert rank.score_cluster(consensus) > rank.score_cluster(solo)


def test_selection_drops_near_duplicate_titles():
    a = Cluster(members=[_candidate(
        "Mark Zuckerberg is planning a big push into personal AI agents",
        url="https://theverge.com/meta", topic="TECHNOLOGY",
        description="Meta earnings call remarks about assistants and agents for billions.",
    )])
    b = Cluster(members=[_candidate(
        "Mark Zuckerberg predicts billions will have personal AI agents",
        url="https://techcrunch.com/meta", topic="TECHNOLOGY",
        description="Meta CEO said AI agents will be for everyone at earnings.",
    )])
    picked = rank.select([a, b])
    assert len(picked) == 1


def test_selection_never_pads_topics_with_weak_clusters():
    strong = Cluster(members=[
        _candidate("Fed cuts rates in surprise emergency move", url="https://apnews.com/fed",
                   topic="BUSINESS"),
        _candidate("Federal Reserve announces surprise rate cut", url="https://reuters.com/fed",
                   topic="BUSINESS"),
    ])
    weak = Cluster(members=[_candidate(
        "Local bakery wins regional award for pastry", url="https://tinyblog.example/bakery",
        topic="ENTERTAINMENT", hours_old=34,
    )])
    picked = rank.select([strong, weak])
    topics = [c.topic for c in picked]
    assert "BUSINESS" in topics
    assert "ENTERTAINMENT" not in topics  # weak solo cluster must not ship


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------


def _packet() -> list[dict]:
    return [
        {"id": "aaa", "topic": "TOP_NEWS", "headline": "Fed cuts rates", "outlets": ["AP"],
         "outlet_count": 3, "published_at": None, "excerpt": "x" * 100},
        {"id": "bbb", "topic": "WORLD", "headline": "Quake hits Japan", "outlets": ["BBC News"],
         "outlet_count": 2, "published_at": None, "excerpt": "y" * 100},
    ]


def _valid_payload() -> dict:
    return {
        "headline": "Federal Reserve cuts interest rates in surprise emergency move",
        "dek": "A rare emergency rate cut and a deadly earthquake in Japan lead a fast-moving news day.",
        "summary": (
            "The Federal Reserve cut its benchmark rate by half a point in an unscheduled move, "
            "citing rapidly deteriorating credit conditions across regional banks. Meanwhile "
            "rescuers in southwestern Japan searched collapsed buildings after a magnitude 6.8 "
            "earthquake killed at least eighteen people and injured hundreds more overnight."
        ),
        "quick_hits": [
            "Federal Reserve cuts benchmark interest rate by half a point",
            "Japan earthquake death toll rises to eighteen after overnight rescues",
            "Regional bank credit conditions drove the emergency Fed decision",
            "Hundreds injured as aftershocks continue across southwestern Japan",
        ],
        "sections": [
            {"topic": "TOP_NEWS", "title": "Top stories", "summary": "The Fed made an emergency cut.",
             "why_it_matters": "Borrowing costs shape every household budget.", "story_ids": ["aaa"]},
            {"topic": "WORLD", "title": "World", "summary": "Japan digs out from a deadly quake.",
             "why_it_matters": "The toll is still rising.", "story_ids": ["bbb"]},
        ],
        "stories": [
            {"id": "aaa", "title": "Fed cuts rates in emergency move",
             "summary": "The Federal Reserve cut its benchmark rate by half a point in an unscheduled emergency decision.",
             "why_it_matters": "Cheaper borrowing arrives as credit conditions tighten.",
             "urgency": "high"},
            {"id": "bbb", "title": "Japan quake death toll reaches eighteen",
             "summary": "Rescuers searched collapsed buildings in southwestern Japan after a magnitude 6.8 earthquake killed eighteen people.",
             "why_it_matters": "Aftershocks threaten rescue crews and survivors.",
             "urgency": "high"},
        ],
    }


def test_valid_payload_passes():
    issues = validate_brief(_valid_payload(), _packet())
    assert issues == [], issues


def test_truncated_headline_is_rejected():
    payload = _valid_payload()
    payload["headline"] = "Graham Platner faces calls to leave Maine Senate race after"
    issues = validate_brief(payload, _packet())
    assert any("truncated" in issue for issue in issues)


def test_title_list_dek_is_rejected():
    payload = _valid_payload()
    payload["dek"] = "Lead stories: Fed cuts rates; Japan earthquake toll rises; Markets react to it"
    issues = validate_brief(payload, _packet())
    assert any("dek" in issue for issue in issues)


def test_missing_packet_story_is_rejected():
    payload = _valid_payload()
    payload["stories"] = payload["stories"][:1]
    payload["sections"] = payload["sections"][:1]
    issues = validate_brief(payload, _packet())
    assert any("missing" in issue for issue in issues)


def test_unknown_story_id_is_rejected():
    payload = _valid_payload()
    payload["stories"][0]["id"] = "zzz"
    issues = validate_brief(payload, _packet())
    assert any('"zzz"' in issue for issue in issues)


def test_fragment_quick_hit_is_rejected():
    payload = _valid_payload()
    payload["quick_hits"][0] = "Federal Reserve cuts benchmark interest rate for the"
    issues = validate_brief(payload, _packet())
    assert any("fragment" in issue or "connective" in issue for issue in issues)


def test_banned_phrases_are_rejected():
    payload = _valid_payload()
    payload["summary"] = payload["summary"][:-1] + ", though it remains to be seen."
    issues = validate_brief(payload, _packet())
    assert any("banned phrase" in issue for issue in issues)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
