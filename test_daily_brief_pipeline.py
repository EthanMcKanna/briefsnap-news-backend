"""Focused tests for the daily brief contract consumed by the iOS app."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from newsaggregator.briefs.pipeline import ArticleCandidate, DailyBriefPipeline, PipelineOptions, TOPICS
from newsaggregator.fetchers.article_fetcher import ArticleFetcher
from verify_daily_brief_release import audit_daily_brief


SAMPLE_SCORE_EVENT = {
    "id": "401871329",
    "date": "2026-05-12T03:30:00Z",
    "name": "Oklahoma City Thunder at Los Angeles Lakers",
    "status": {
        "type": {
            "state": "in",
            "shortDetail": "10:55 - 3rd",
            "detail": "10:55 - 3rd",
            "completed": False,
        }
    },
    "competitions": [
        {
            "venue": {
                "fullName": "Crypto.com Arena",
                "address": {"city": "Los Angeles", "state": "CA"},
            },
            "broadcasts": [{"names": ["ESPN"]}],
            "competitors": [
                {
                    "homeAway": "away",
                    "score": "55",
                    "winner": False,
                    "curatedRank": {"current": 2},
                    "team": {
                        "displayName": "Oklahoma City Thunder",
                        "shortDisplayName": "Thunder",
                        "abbreviation": "OKC",
                        "logo": "https://example.com/okc.png",
                    },
                },
                {
                    "homeAway": "home",
                    "score": "47",
                    "winner": False,
                    "records": [{"summary": "32-18"}],
                    "team": {
                        "displayName": "Los Angeles Lakers",
                        "shortDisplayName": "Lakers",
                        "abbreviation": "LAL",
                        "logo": "https://example.com/lal.png",
                    },
                },
            ],
        }
    ],
}


def valid_quality_brief() -> dict:
    stories = [
        {
            "id": "story-1",
            "topic": "TOP_NEWS",
            "title": "First current story",
            "summary": "A meaningful summary explains the current update with enough concrete detail.",
            "why_it_matters": "Readers can understand the direct public impact.",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/us/story-1",
            "image_url": "https://static.reuters.com/images/story-1.jpg",
        },
        {
            "id": "story-2",
            "topic": "TOP_NEWS",
            "title": "Second current story",
            "summary": "A second verified story adds another useful angle for the daily brief.",
            "why_it_matters": "It changes what people should watch today.",
            "source": "AP News",
            "url": "https://apnews.com/article/story-2",
            "image_url": "https://dims.apnews.com/dims4/default/story-2.jpg",
        },
        {
            "id": "story-3",
            "topic": "BUSINESS",
            "title": "Third current story",
            "summary": "Business context stays specific enough for readers scanning quickly.",
            "why_it_matters": "Market decisions can affect household costs.",
            "source": "CNBC",
            "url": "https://www.cnbc.com/2026/05/12/story-3.html",
        },
        {
            "id": "story-4",
            "topic": "TECHNOLOGY",
            "title": "Fourth current story",
            "summary": "Technology coverage highlights the practical consequence of the announcement.",
            "why_it_matters": "Companies may shift product plans this quarter.",
            "source": "The Verge",
            "url": "https://www.theverge.com/2026/5/12/story-4",
        },
        {
            "id": "story-5",
            "topic": "WORLD",
            "title": "Fifth current story",
            "summary": "World coverage adds current international context without drifting broad.",
            "why_it_matters": "The decision affects regional diplomacy.",
            "source": "BBC",
            "url": "https://www.bbc.com/news/world-story-5",
        },
        {
            "id": "story-6",
            "topic": "SPORTS",
            "title": "Playoff matchup reshapes NBA finals race",
            "summary": "The NBA playoff picture changed after a late injury report.",
            "why_it_matters": "It changes rotations before the next game.",
            "source": "ESPN",
            "url": "https://www.espn.com/nba/story/_/id/story-6",
        },
    ]
    return {
        "model_used": "gemini-3-flash-preview-search-grounded",
        "headline": "First current story leads the day",
        "dek": "First current story leads alongside Second current story.",
        "summary": "A concise summary with enough substance for the daily brief quality gate.",
        "quick_hits": ["First current story"],
        "hero_image_url": "https://static.reuters.com/images/story-1.jpg",
        "stories": stories,
        "sections": [
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1", "story-2"],
            },
            {
                "topic": "SPORTS",
                "title": "Sports",
                "summary": "The current sports desk.",
                "why_it_matters": "Sports context stays relevant.",
                "story_ids": ["story-6"],
            },
        ],
        "sports_scores": [],
    }


def article_candidates_for_normalization() -> list[ArticleCandidate]:
    return [
        ArticleCandidate(
            id=f"story-{index}",
            topic=topic,
            title=title,
            source=source,
            url=url,
            description="A concise source-backed update with enough detail for the brief.",
            image_url=image_url,
        )
        for index, (topic, title, source, url, image_url) in enumerate(
            [
                (
                    "TOP_NEWS",
                    "Court ruling reshapes federal immigration enforcement",
                    "Reuters",
                    "https://www.reuters.com/world/us/story-1",
                    "https://static.reuters.com/images/story-1.jpg",
                ),
                (
                    "TOP_NEWS",
                    "Storm recovery costs rise across the Gulf Coast",
                    "AP News",
                    "https://apnews.com/article/story-2",
                    "https://dims.apnews.com/dims4/default/story-2.jpg",
                ),
                ("BUSINESS", "Markets fall after retail outlook weakens", "CNBC", "https://www.cnbc.com/story-3", None),
                ("TECHNOLOGY", "Chipmaker expands domestic AI server production", "The Verge", "https://www.theverge.com/story-4", None),
                ("WORLD", "European leaders agree on new defense financing", "BBC", "https://www.bbc.com/news/story-5", None),
                ("HEALTH", "Hospitals prepare for summer virus uptick", "STAT", "https://www.statnews.com/story-6", None),
            ],
            start=1,
        )
    ]


def test_parse_json_response_extracts_fenced_json_with_prose():
    payload = DailyBriefPipeline._parse_json_response(
        """
Here is the brief:

```json
{
  "headline": "A clear daily brief",
  "stories": [],
  "sections": []
}
```

Done.
""".strip()
    )

    assert payload["headline"] == "A clear daily brief"


def test_parse_json_response_repairs_missing_line_commas_and_trailing_commas():
    payload = DailyBriefPipeline._parse_json_response(
        """
{
  "headline": "A clear daily brief"
  "dek": "The missing comma is repaired",
  "stories": [],
  "sections": [],
}
""".strip()
    )

    assert payload["dek"] == "The missing comma is repaired"
    assert payload["stories"] == []


def test_parse_json_response_tolerates_unescaped_newlines_in_strings():
    payload = DailyBriefPipeline._parse_json_response(
        '{"headline": "A clear daily brief", "summary": "Line one\nLine two", "stories": []}'
    )

    assert payload["summary"] == "Line one\nLine two"


def test_parse_score_event_keeps_verification_metadata():
    score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=SAMPLE_SCORE_EVENT,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260511&limit=80",
        verified_at="2026-05-12T04:09:07+00:00",
    )

    assert score is not None
    assert score["id"] == "nba-401871329"
    assert score["source"] == "ESPN"
    assert score["source_url"].endswith("limit=80")
    assert score["verified_at"] == "2026-05-12T04:09:07+00:00"
    assert score["event_date"] == "2026-05-12T03:30:00+00:00"
    assert score["expires_at"] == "2026-05-12T04:24:07+00:00"
    assert score["event_id"] == "401871329"
    assert score["is_live"] is True
    assert score["home_team"]["score"] == 47
    assert score["away_team"]["score"] == 55
    assert score["broadcast"] == "ESPN"
    assert score["venue_location"] == "Los Angeles, CA"


def test_sports_score_metadata_uses_latest_card_verification():
    metadata = DailyBriefPipeline._sports_scores_metadata(
        [
            {"verified_at": "2026-05-12T04:09:07+00:00"},
            {"verified_at": "2026-05-12T04:10:12+00:00"},
        ]
    )

    assert metadata == {
        "sports_scores_refreshed_at": "2026-05-12T04:10:12+00:00",
        "sports_scores_verified_at": "2026-05-12T04:10:12+00:00",
        "sports_scores_source": "ESPN",
    }


def test_release_gate_can_audit_against_already_refreshed_score_ids():
    now = datetime(2026, 5, 12, 4, 30, tzinfo=timezone.utc)
    score = {
        "id": "nba-401871329",
        "league": "NBA",
        "display": "Oklahoma City Thunder at Los Angeles Lakers (10:55 - 3rd)",
        "source": "ESPN",
        "source_url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "verified_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
    }
    brief = valid_quality_brief()
    brief.update(
        {
            "generated_at": now.isoformat(),
            "sports_scores": [score],
            **DailyBriefPipeline._sports_scores_metadata([score]),
        }
    )

    with patch("verify_daily_brief_release.stale_active_final_score_ids", return_value=[]), patch(
        "verify_daily_brief_release.DailyBriefPipeline._fetch_top_sports_scores"
    ) as fetch_scores:
        issues, summary = audit_daily_brief(
            brief,
            now=now,
            max_age=timedelta(hours=30),
            max_sports_age=timedelta(minutes=20),
            max_final_score_age=timedelta(hours=6),
            check_current_espn=True,
            current_score_ids=["nba-401871329"],
        )

    fetch_scores.assert_not_called()
    assert summary["current_espn_score_ids"] == ["nba-401871329"]
    assert not any("sports scores do not match fresh ESPN selector" in issue for issue in issues)


def test_quality_gate_rejects_sports_scores_without_source_metadata():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    pipeline.sports_score_cards = [{"id": "nba-401871329", "league": "NBA"}]

    brief = {
        "model_used": "gemini-3-flash-preview-search-grounded",
        "headline": "First current story leads the day",
        "dek": "First current story leads alongside Second current story.",
        "summary": "A concise summary with enough substance for the daily brief quality gate.",
        "quick_hits": ["First current story"],
        "stories": [
            {
                "id": "story-1",
                "topic": "TOP_NEWS",
                "title": "First current story",
                "summary": "A meaningful summary for the first current story.",
                "why_it_matters": "Clear impact.",
                "source": "Reuters",
                "url": "https://example.com/1",
            },
            {
                "id": "story-2",
                "topic": "TOP_NEWS",
                "title": "Second current story",
                "summary": "A meaningful summary for the second current story.",
                "why_it_matters": "Clear impact.",
                "source": "AP",
                "url": "https://example.com/2",
            },
            {
                "id": "story-3",
                "topic": "BUSINESS",
                "title": "Third current story",
                "summary": "A meaningful summary for the third current story.",
                "why_it_matters": "Clear impact.",
                "source": "CNBC",
                "url": "https://example.com/3",
            },
            {
                "id": "story-4",
                "topic": "TECHNOLOGY",
                "title": "Fourth current story",
                "summary": "A meaningful summary for the fourth current story.",
                "why_it_matters": "Clear impact.",
                "source": "The Verge",
                "url": "https://example.com/4",
            },
            {
                "id": "story-5",
                "topic": "WORLD",
                "title": "Fifth current story",
                "summary": "A meaningful summary for the fifth current story.",
                "why_it_matters": "Clear impact.",
                "source": "BBC",
                "url": "https://example.com/5",
            },
            {
                "id": "story-6",
                "topic": "HEALTH",
                "title": "Sixth current story",
                "summary": "A meaningful summary for the sixth current story.",
                "why_it_matters": "Clear impact.",
                "source": "STAT",
                "url": "https://example.com/6",
            },
        ],
        "sections": [
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1", "story-2"],
            }
        ],
        "sports_scores": [
            {
                "id": "nba-401871329",
                "league": "NBA",
                "display": "OKC 55 at LAL 47",
                "home_team": {"abbreviation": "LAL", "score": 47},
                "away_team": {"abbreviation": "OKC", "score": 55},
            }
        ],
    }

    issues = pipeline._brief_quality_issues(brief)

    assert "sports scores missing top-level ESPN source metadata" in issues
    assert "sports scores missing top-level refreshed_at timestamp" in issues
    assert "sports scores missing top-level verified_at timestamp" in issues
    assert "sports score nba-401871329 missing ESPN source metadata" in issues
    assert "sports score nba-401871329 missing verified_at" in issues


def test_quality_gate_accepts_direct_sources_with_multimedia_and_sports_relevance():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(valid_quality_brief())

    assert issues == []


def test_normalize_brief_backfills_sports_news_when_model_omits_it():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=SAMPLE_SCORE_EVENT,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260511&limit=80",
        verified_at="2026-05-12T04:09:07+00:00",
    )
    assert score is not None
    pipeline.sports_score_cards = [score]
    articles = article_candidates_for_normalization() + [
        ArticleCandidate(
            id="sports-1",
            topic="SPORTS",
            title="NBA playoff injury report reshapes the finals race",
            source="ESPN",
            url="https://www.espn.com/nba/story/_/id/sports-1/nba-playoff-injury-report",
            description="A late NBA injury update changed rotations and betting expectations before tonight's playoff game.",
            image_url="https://a.espncdn.com/photo/2026/0512/nba-playoffs.jpg",
            score=22,
        ),
        ArticleCandidate(
            id="sports-2",
            topic="SPORTS",
            title="MLB players push salary overhaul before labor talks",
            source="The Athletic",
            url="https://www.nytimes.com/athletic/7312470/2026/05/27/mlb-labor-negotiations/",
            description="MLB players are pressing for changes to the salary system before the next bargaining round.",
            score=21,
        ),
    ]
    payload = {
        "headline": "Court ruling and markets lead the day",
        "summary": "A concise current summary.",
        "quick_hits": ["Court ruling reshapes federal immigration enforcement"],
        "stories": [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "summary": article.description,
                "why_it_matters": "Readers get a concrete current consequence.",
            }
            for article in articles[:6]
        ],
        "sections": [
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1", "story-2"],
            }
        ],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    sports_stories = [
        story for story in brief["stories"]
        if pipeline._normalize_topic(story.get("topic")) == "SPORTS"
    ]
    sports_sections = [
        section for section in brief["sections"]
        if pipeline._normalize_topic(section.get("topic")) == "SPORTS"
    ]

    assert [story["id"] for story in sports_stories] == ["sports-1", "sports-2"]
    assert sports_sections
    assert set(sports_sections[0]["story_ids"]) == {"sports-1", "sports-2"}
    assert "sports desk needs at least one sports news story" not in pipeline._brief_quality_issues(brief)


def test_normalize_brief_keeps_canonical_sports_topic_when_model_mislabels_story():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = article_candidates_for_normalization() + [
        ArticleCandidate(
            id="sports-1",
            topic="SPORTS",
            title="NBA playoff injury report reshapes the finals race",
            source="ESPN",
            url="https://www.espn.com/nba/story/_/id/sports-1/nba-playoff-injury-report",
            description="A late NBA injury update changed rotations before tonight's playoff game.",
            score=22,
        ),
        ArticleCandidate(
            id="sports-2",
            topic="SPORTS",
            title="MLB players push salary overhaul before labor talks",
            source="The Athletic",
            url="https://www.nytimes.com/athletic/7312470/2026/05/27/mlb-labor-negotiations/",
            description="MLB players are pressing for changes to the salary system before the next bargaining round.",
            score=21,
        ),
    ]
    payload = {
        "headline": "Court ruling and markets lead the day",
        "summary": "A concise current summary.",
        "quick_hits": ["Court ruling reshapes federal immigration enforcement"],
        "stories": [
            *[
                {
                    "id": article.id,
                    "topic": article.topic,
                    "title": article.title,
                    "source": article.source,
                    "summary": article.description,
                    "why_it_matters": "Readers get a concrete current consequence.",
                }
                for article in articles[:6]
            ],
            {
                "id": "sports-1",
                "topic": "BUSINESS",
                "title": "NBA playoff injury report reshapes the finals race",
                "source": "ESPN",
                "summary": "A late NBA injury update changed rotations before tonight's playoff game.",
                "why_it_matters": "It changes how fans read the next matchup.",
            },
        ],
        "sections": [],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    sports_story_ids = [
        story["id"] for story in brief["stories"]
        if pipeline._normalize_topic(story.get("topic")) == "SPORTS"
    ]

    assert sports_story_ids == ["sports-1", "sports-2"]


def test_normalize_brief_keeps_backfilled_sports_inside_visible_story_window():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id=f"story-{index}",
            topic="BUSINESS" if index % 2 else "TECHNOLOGY",
            title=f"Non sports story {index} with enough detail",
            source="CNBC" if index % 2 else "The Verge",
            url=f"https://example.com/story-{index}",
            description=f"Non sports source packet summary {index} with enough detail for readers.",
            score=40 - index,
        )
        for index in range(1, 19)
    ] + [
        ArticleCandidate(
            id="sports-1",
            topic="SPORTS",
            title="NBA playoff injury report reshapes the finals race",
            source="ESPN",
            url="https://www.espn.com/nba/story/_/id/sports-1/nba-playoff-injury-report",
            description="A late NBA injury update changed rotations before tonight's playoff game.",
            score=5,
        ),
        ArticleCandidate(
            id="sports-2",
            topic="SPORTS",
            title="MLB players demand salary overhaul before labor talks",
            source="The Washington Post",
            url="https://www.washingtonpost.com/business/2026/05/27/mlb-labor-negotiations/example",
            description="MLB players are pressing for salary-system changes before the next labor negotiation window.",
            score=4,
        ),
    ]
    payload = {
        "headline": "Non sports story 1 leads the day",
        "summary": "A concise current summary.",
        "quick_hits": ["Non sports story 1 with enough detail"],
        "stories": [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "summary": article.description,
                "why_it_matters": "Readers get a concrete current consequence.",
            }
            for article in articles[:18]
        ],
        "sections": [],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    visible_story_ids = {story["id"] for story in brief["stories"]}

    assert {"sports-1", "sports-2"}.issubset(visible_story_ids)


def test_normalize_brief_backfills_supported_topic_breadth_when_model_omits_it():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    topics = [
        ("TOP_NEWS", "Reuters", "https://www.reuters.com/world/us"),
        ("BUSINESS", "CNBC", "https://www.cnbc.com/business"),
        ("TECHNOLOGY", "The Verge", "https://www.theverge.com/tech"),
        ("WORLD", "BBC", "https://www.bbc.com/news/world"),
        ("HEALTH", "STAT", "https://www.statnews.com/health"),
        ("SCIENCE", "AP News", "https://apnews.com/science"),
    ]
    articles: list[ArticleCandidate] = []
    for topic, source, base_url in topics:
        for index in range(1, 4):
            articles.append(
                ArticleCandidate(
                    id=f"{topic.lower()}-{index}",
                    topic=topic,
                    title=f"{topic.title()} story {index} carries verified public impact",
                    source=source,
                    url=f"{base_url}/story-{index}",
                    description=f"{topic} source packet summary {index} with enough detail for readers.",
                    score=50 - len(articles),
                )
            )

    payload = {
        "headline": "Top news and business lead the day",
        "summary": "A concise current summary.",
        "quick_hits": ["Top news and business lead the day"],
        "stories": [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "summary": article.description,
                "why_it_matters": "Readers get a concrete current consequence.",
            }
            for article in articles[:6]
        ],
        "sections": [],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    visible_topics = {
        pipeline._normalize_topic(story.get("topic"))
        for story in brief["stories"][:12]
        if story.get("topic")
    }

    assert len(brief["stories"]) >= 10
    assert len(visible_topics) >= 5
    assert {"TECHNOLOGY", "WORLD", "HEALTH"}.issubset(visible_topics)
    assert "visible stories need broader topic coverage" not in pipeline._brief_quality_issues(brief)


def test_collect_articles_reserves_late_sports_topic_before_enrichment():
    pipeline = DailyBriefPipeline(
        PipelineOptions(
            dry_run=True,
            publish=False,
            max_articles_per_topic=1,
            max_total_articles=6,
        )
    )

    def fake_collect_topic(topic):
        if topic.code == "SPORTS":
            return [
                ArticleCandidate(
                    id="sports-1",
                    topic="SPORTS",
                    title="NBA playoff injury report reshapes the finals race",
                    source="ESPN",
                    url="https://www.espn.com/nba/story/_/id/sports-1/nba-playoff-injury-report",
                    description="A late NBA injury update changed rotations before tonight's playoff game.",
                    score=1,
                )
            ]
        return [
            ArticleCandidate(
                id=f"{topic.code.lower()}-1",
                topic=topic.code,
                title=f"{topic.code.title()} story carries verified public impact",
                source="Associated Press",
                url=f"https://apnews.com/article/{topic.code.lower()}-1",
                description="A current source-backed update with enough detail.",
                score=100,
            )
        ]

    with patch.object(pipeline, "_collect_topic", side_effect=fake_collect_topic):
        with patch.object(pipeline, "_enrich_articles", side_effect=lambda candidates: candidates):
            articles = pipeline.collect_articles()

    assert len(articles) == 6
    assert "SPORTS" in {pipeline._normalize_topic(article.topic) for article in articles}


def test_quality_gate_rejects_scores_without_sports_news_story():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=SAMPLE_SCORE_EVENT,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260511&limit=80",
        verified_at="2026-05-12T04:09:07+00:00",
    )
    assert score is not None
    brief = valid_quality_brief()
    brief["stories"][-1].update(
        {
            "topic": "HEALTH",
            "title": "Hospitals prepare for summer virus uptick",
            "summary": "Hospitals are preparing capacity plans as summer respiratory virus cases begin to rise.",
            "why_it_matters": "Planning can reduce delays for patients.",
            "source": "STAT",
            "url": "https://www.statnews.com/story-6",
        }
    )
    brief["sports_scores"] = [score]
    brief.update(DailyBriefPipeline._sports_scores_metadata([score]))

    issues = pipeline._brief_quality_issues(brief)

    assert "sports desk needs at least one sports news story" in issues


def test_normalize_brief_repairs_unsupported_top_level_copy():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = article_candidates_for_normalization()
    payload = {
        "headline": "Biden audio lawsuit leads the day",
        "dek": "President Biden audio releases overshadow several unrelated stories.",
        "summary": (
            "President Biden sued to block audio releases while unrelated policy fights "
            "moved through Washington. The selected stories below do not actually cover "
            "that claim, so the brief should ground itself in the normalized story list."
        ),
        "quick_hits": [
            "President Biden sues to block audio releases",
            "Court ruling reshapes federal immigration enforcement",
        ],
        "stories": [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "summary": article.description,
                "why_it_matters": "Readers get a concrete current consequence.",
            }
            for article in articles
        ],
        "sections": [
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1", "story-2"],
            }
        ],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    top_level_copy = " ".join(
        [
            brief["headline"],
            brief["dek"],
            brief["summary"],
            " ".join(brief["quick_hits"]),
        ]
    ).lower()

    assert "biden" not in top_level_copy
    assert "audio releases" not in top_level_copy
    assert brief["headline"] == "Court ruling reshapes federal immigration enforcement"
    assert brief["quick_hits"][0] == "Court ruling reshapes federal immigration enforcement"


def test_normalize_brief_repairs_clipped_visible_copy():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id="kuwait",
            topic="WORLD",
            title="Kuwait says it faced a missile and drone attack, another challenge to Iran war's shaky ceasefire",
            source="Reuters",
            url="https://www.reuters.com/world/middle-east/kuwait-missile-drone-attack",
            description="Kuwait's military announced a missile and drone attack on its territory Thursday, further destabilizing a shaky ceasefire in the region...",
            image_url="https://static.reuters.com/images/kuwait-1200.jpg",
        ),
        ArticleCandidate(
            id="temu",
            topic="TOP_NEWS",
            title="Chinese online retailer Temu hit with $232 million fine over illegal products",
            source="AP News",
            url="https://apnews.com/article/temu-eu-fine",
            description="European regulators fined Temu after finding illegal products and consumer-safety failures across the platform.",
            image_url="https://dims.apnews.com/dims4/default/temu-1200.jpg",
        ),
        ArticleCandidate(
            id="cvs",
            topic="HEALTH",
            title="CVS to restore coverage of Zepbound and add Lilly obesity pill to drug plans",
            source="CNBC",
            url="https://www.cnbc.com/cvs-zepbound-coverage",
            description="CVS will restore coverage for Zepbound and add a new obesity pill to standard drug plans.",
        ),
        ArticleCandidate(
            id="trump-accounts",
            topic="BUSINESS",
            title="Financial app for managing Trump Accounts set to launch Thursday",
            source="The Wall Street Journal",
            url="https://www.wsj.com/business/trump-accounts-app",
            description="A financial app is set to launch for families managing the new children savings accounts.",
        ),
        ArticleCandidate(
            id="aws",
            topic="BUSINESS",
            title="Snowflake signs six billion dollar AWS deal for AI infrastructure",
            source="CNBC",
            url="https://www.cnbc.com/snowflake-aws-ai-deal",
            description="Snowflake committed to a multiyear AWS agreement focused on AI infrastructure capacity.",
        ),
        ArticleCandidate(
            id="sports",
            topic="SPORTS",
            title="NBA playoffs 2026 will decide Thunder-Spurs Game 6",
            source="ESPN",
            url="https://www.espn.com/nba/story/_/id/48891194/thunder-spurs-game-6",
            description="The Thunder face the Spurs in Game 6 with a Finals berth still in reach.",
        ),
    ]
    payload = {
        "headline": "Kuwait says it faced a missile and drone attack, another",
        "dek": (
            "Kuwait says it faced a missile and drone attack, another challenge to Iran war's shaky "
            "ceasefire leads alongside Chinese online retailer Temu..."
        ),
        "summary": (
            "Kuwait's military announced a missile and drone attack on its territory Thursday, further "
            "destabilizing a shaky ceasefire.... Chinese e-commerce giant Temu has been fined by the "
            "European Union after investigators found the retailer failed..."
        ),
        "quick_hits": [
            "Kuwait says it faced a missile and drone attack, another challenge to Iran war's",
            "Chinese online retailer Temu hit with $232 million fine over illegal products",
        ],
        "stories": [
            {
                "id": article.id,
                "topic": article.topic,
                "title": article.title,
                "source": article.source,
                "summary": article.description,
                "why_it_matters": "Readers get a concrete current consequence.",
            }
            for article in articles
        ],
        "sections": [],
        "custom_widgets": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "gemini-3-flash-preview-search-grounded")
    visible_copy = " ".join(
        [
            brief["headline"],
            brief["dek"],
            brief["summary"],
            " ".join(brief["quick_hits"]),
            " ".join(story["summary"] for story in brief["stories"]),
        ]
    )

    assert brief["headline"] == "Kuwait says it faced a missile and drone attack"
    assert "..." not in visible_copy
    assert "…" not in visible_copy
    assert not any(
        DailyBriefPipeline._is_unpolished_copy(item)
        for item in [brief["headline"], brief["dek"], brief["summary"], *brief["quick_hits"]]
    )
    assert "visible truncation" not in " ".join(pipeline._brief_quality_issues(brief))


def test_story_normalization_drops_scraped_source_boilerplate():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="ap-boilerplate",
        topic="WORLD",
        title="Malaysia enforces ban on social media accounts for children younger than 16",
        source="AP News",
        url="https://apnews.com/article/malaysia-social-media-ban-16",
        description="Add AP News as your preferred source to see more of our stories on Google.",
        content="Add AP News as your preferred source to see more of our stories on Google.",
    )

    story = pipeline._normalized_story_from_article(article)

    assert story["summary"].startswith("This world update from AP News focuses on Malaysia enforces")
    assert story["summary"] != article.title
    assert not DailyBriefPipeline._is_unpolished_copy(story["summary"])
    assert DailyBriefPipeline._clean_description(
        "Trump floats MAGA rally instead of concert toggle caption Alex Brandon/AP",
        title="Trump floats MAGA rally instead of concert",
        source="NPR",
    ) == ""


def test_story_normalization_replaces_junk_model_summary_and_keeps_source_topic():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="openai-cnbc",
        topic="TECHNOLOGY",
        title="OpenAI chief outlines infrastructure plans in new interview",
        source="CNBC",
        url="https://www.cnbc.com/2026/06/02/openai-altman-interview.html",
        description=(
            "OpenAI's chief executive discussed infrastructure spending, safety work, "
            "and near-term product priorities."
        ),
    )

    story = pipeline._normalized_story_from_article(
        article,
        story={
            "topic": "WORLD",
            "title": "OpenAI CEO Gives CNBC Transcript",
            "source": "CNBC",
            "summary": "com",
            "why_it_matters": "It affects AI infrastructure and platform planning.",
        },
    )

    assert story["topic"] == "TECHNOLOGY"
    assert story["title"] == "OpenAI chief outlines infrastructure plans in new interview"
    assert story["summary"].startswith("OpenAI's chief executive discussed infrastructure")
    assert story["summary"] != "com"


def test_story_normalization_replaces_cross_article_model_copy():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="remote-work-grads",
        topic="BUSINESS",
        title="Remote work -- not AI -- has sidelined recent college graduates, research finds",
        source="NPR Topics: Business",
        url="https://www.npr.org/2026/06/01/nx-s1-5843076/remote-work-college-graduates-unemployment-ai",
        description=(
            "Research finds remote work has reduced entry-level training and left "
            "recent college graduates with fewer paths into the labor market."
        ),
    )

    story = pipeline._normalized_story_from_article(
        article,
        story={
            "summary": "NASA is testing a mobile wastewater treatment facility at the University of North Dakota",
            "why_it_matters": "Advances critical life support technology for deep space exploration.",
        },
    )

    assert story["summary"].startswith("Research finds remote work")
    assert "NASA" not in story["summary"]
    assert story["why_it_matters"] == "It can affect markets, companies, or household costs"


def test_story_normalization_rejects_dangling_and_unrelated_model_copy():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="rams-garrett",
        topic="SPORTS",
        title="McVay talks Rams' pursuit of Garrett, possible Donald return",
        source="ESPN",
        url="https://www.espn.com/nfl/story/_/id/48951573/mcvay-rams-aggressive-shot-land-star-garrett",
        description=(
            "Sean McVay discussed the Rams' aggressive pursuit of Myles Garrett "
            "and whether Aaron Donald could return."
        ),
    )

    story = pipeline._normalized_story_from_article(
        article,
        story={
            "summary": (
                "The film 'Dreams of Violets,' premiering at the Tribeca Film Festival, "
                "was created almost entirely using artificial intelligence"
            ),
            "why_it_matters": "Explores the disruptive potential of AI in the creative industries.",
        },
    )

    assert story["summary"].startswith("Sean McVay discussed")
    assert "Dreams of Violets" not in story["summary"]
    assert story["why_it_matters"] == "It gives fans verified context beyond the scoreboard"

    assert DailyBriefPipeline._is_unpolished_copy(
        "A Sydney academic used artificial intelligence to write an opinion piece. The university has"
    )
    assert DailyBriefPipeline._is_unpolished_copy(
        "Sydney academic used AI to write SMH opinion piece urging students to avoid using"
    )
    assert DailyBriefPipeline._is_unpolished_copy(
        "'s Divergent Deployable Wastewater Treatment Facility, built at Kennedy Space Center"
    )
    assert DailyBriefPipeline._is_unpolished_copy(
        "is opening access to its Fly Foundational Robots mission"
    )
    assert not DailyBriefPipeline._is_unpolished_copy(
        "Is bovine colostrum really 'liquid gold' for gut health?"
    )
    assert DailyBriefPipeline._is_unpolished_copy(
        "The U.S. military said that Iran fired missiles at Kuwait and Bahrain that failed or were shot down, and that the U.S."
    )
    assert DailyBriefPipeline._is_unpolished_copy("A federal jury in California has convicted")
    assert DailyBriefPipeline._is_unpolished_copy(
        "A strong start in the Stanley Cup Final gives the Golden Knights momentum in their quest"
    )
    assert DailyBriefPipeline._is_unpolished_copy("‘The CGI would have cost millions.")


def test_story_normalization_strips_terminal_fragment_sentence():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="iowa-primary",
        topic="TOP_NEWS",
        title="Iowa voters pick their nominees for competitive general elections",
        source="AP News",
        url="https://apnews.com/article/iowa-primary-election",
        description=(
            "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
            "Ashley Hinson in the Senate race."
        ),
    )

    story = pipeline._normalized_story_from_article(
        article,
        story={
            "summary": (
                "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
                "Ashley Hinson in the Senate race. For governor"
            ),
            "why_it_matters": "The races will shape Iowa's statewide ballot in November.",
        },
    )

    assert story["summary"] == (
        "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
        "Ashley Hinson in the Senate race"
    )
    assert "For governor" not in story["summary"]
    assert not DailyBriefPipeline._is_unpolished_copy(story["summary"])


def test_story_normalization_rejects_scraped_noun_phrase_summary():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="nasa-wastewater",
        topic="SCIENCE",
        title="NASA Testing Wastewater Treatment Facility for Future Moon Base",
        source="NASA",
        url="https://www.nasa.gov/kennedy/wastewater-treatment-moon-base",
        description=(
            "A mobile wastewater treatment system built at NASA’s Kennedy Space Center "
            "in Florida that can help prepare for long-duration missions on the Moon and Mars"
        ),
    )

    story = pipeline._normalized_story_from_article(article)

    assert story["summary"].startswith(
        "This science update from NASA focuses on NASA Testing Wastewater"
    )
    assert story["summary"] != "NASA Testing Wastewater Treatment Facility for Future Moon Base"
    assert "that can help prepare" not in story["summary"]

    possessive_article = ArticleCandidate(
        id="nasa-possessive",
        topic="SCIENCE",
        title="NASA tests wastewater system for future Moon base",
        source="NASA",
        url="https://www.nasa.gov/kennedy/wastewater-treatment-moon-base",
        description=(
            "NASA's Divergent Deployable Wastewater Treatment Facility, built at Kennedy "
            "Space Center, is undergoing testing at the University of North Dakota."
        ),
    )

    possessive_story = pipeline._normalized_story_from_article(possessive_article)

    assert possessive_story["summary"].startswith("NASA's Divergent Deployable")
    assert not possessive_story["summary"].startswith("'s")


def test_repairs_missing_apostrophe_in_its_after_reporting_verb():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    article = ArticleCandidate(
        id="science-funding-rule",
        topic="SCIENCE",
        title="Administration moves science funding under tighter political control",
        source="NPR",
        url="https://www.npr.org/2026/06/03/science-funding-rule",
        description=(
            "A new rule could shift how science funding works in the U.S. "
            "The administration says its an effort to deter waste."
        ),
    )

    story = pipeline._normalized_story_from_article(article)

    assert "says it's an effort" in story["summary"]


def test_quality_gate_rejects_unsupported_top_level_named_entities():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["summary"] = (
        "President Biden sued to block audio releases while the displayed story list "
        "covers only unrelated policy, markets, technology, world, and sports stories."
    )

    issues = pipeline._brief_quality_issues(brief)

    assert "top-level brief copy includes unsupported named entities" in issues


def test_quality_gate_rejects_clipped_visible_copy():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["headline"] = "Kuwait says it faced a missile and drone attack, another"
    brief["summary"] = "A concise summary starts well but trails off..."
    brief["quick_hits"].append(
        "Sydney academic used AI to write SMH opinion piece urging students to avoid using"
    )
    brief["sections"][0]["summary"] = (
        "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
        "Ashley Hinson in the Senate race. For governor"
    )
    brief["custom_widgets"] = [
        {
            "topic": "TOP_NEWS",
            "title": "Top News",
            "summary": (
                "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
                "Ashley Hinson in the Senate race. For governor"
            ),
            "items": ["Iowa voters pick their nominees"],
        },
        {
            "topic": "HEALTH",
            "title": "Health",
            "summary": (
                "For months ahead of the World Cup, states and cities have been preparing "
                "for potential threats including foodborne"
            ),
            "items": ["Heat, bugs, germs: U.S. public health prepares for the World Cup"],
        },
    ]
    brief["stories"][0]["summary"] = "A story summary starts with useful detail before it trails off..."
    brief["stories"][1]["summary"] = (
        "\"If you're 22 years old in San Francisco and building something in AI, "
        "there may be a seed term sheet in your inbox, but if you're 19"
    )
    brief["stories"][2]["summary"] = (
        "San Diego may have water to sell to states that are seeing their supplies"
    )
    brief["stories"][3]["summary"] = (
        "Democratic state Rep. Josh Turek will face Republican U.S. Rep. "
        "Ashley Hinson in the Senate race. For governor"
    )

    issues = pipeline._brief_quality_issues(brief)

    assert "top-level brief copy contains visible truncation" in issues
    assert "top-level brief copy has clipped phrasing" in issues
    assert "story story-1 contains visible truncation" in issues
    assert "story story-1 has clipped copy" in issues
    assert "story story-2 contains visible truncation" in issues
    assert "story story-3 contains visible truncation" in issues
    assert "story story-4 contains visible truncation" in issues
    assert "TOP_NEWS section contains visible truncation" in issues
    assert "TOP_NEWS widget contains visible truncation" in issues
    assert "HEALTH widget contains visible truncation" in issues


def test_generated_candidate_quality_failure_raises_for_retry():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["stories"][0]["summary"] = "A generated story starts with useful detail before trailing off..."

    with pytest.raises(ValueError, match="generated candidate quality gate failed"):
        pipeline._raise_for_generated_candidate_quality(brief)


def test_section_sanitizer_rebuilds_summary_from_visible_story_ids():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    stories = valid_quality_brief()["stories"]
    sections = [
        {
            "topic": "TECHNOLOGY",
            "title": "Technology",
            "summary": "Florida sues OpenAI and Sam Altman over alleged safety lapses • The CGI would have cost millions.",
            "why_it_matters": "Enough current signal to merit a dedicated scan.",
            "story_ids": ["story-4"],
        }
    ]

    sanitized = pipeline._sanitize_sections(sections, stories)

    assert sanitized[0]["story_ids"] == ["story-4"]
    assert sanitized[0]["summary"] == "Fourth current story"
    assert "Florida sues OpenAI" not in sanitized[0]["summary"]


def test_normalize_widgets_summarizes_only_visible_items():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    hidden_title = "‘The CGI would have cost millions. I spent $2,000.’ Is Dreams of Violets AI slop"
    visible_title = "Trump signs AI safety order seeking voluntary review of new models"
    stories = [
        {
            "id": "hidden-ai-film",
            "topic": "TECHNOLOGY",
            "title": hidden_title,
            "summary": "A festival drama uses generative video tools to recreate political violence.",
        },
        {
            "id": "visible-ai-order",
            "topic": "TECHNOLOGY",
            "title": visible_title,
            "summary": "President Trump signed an order asking AI companies to submit new models for testing.",
        },
        {
            "id": "visible-ai-lawsuit",
            "topic": "TECHNOLOGY",
            "title": "Florida sues OpenAI and Sam Altman over alleged safety lapses",
            "summary": "Florida alleges the company failed to warn users about chatbot safety risks.",
        },
    ]
    articles = [
        ArticleCandidate(
            id=story["id"],
            topic=story["topic"],
            title=story["title"],
            source="The Verge",
            url=f"https://www.theverge.com/{story['id']}",
            description=story["summary"],
        )
        for story in stories
    ]

    widgets = pipeline._normalize_widgets([], stories, articles)
    technology_widget = next(widget for widget in widgets if widget["topic"] == "TECHNOLOGY")

    assert hidden_title not in technology_widget["items"]
    assert technology_widget["items"][0] == visible_title
    assert technology_widget["summary"] == stories[1]["summary"].rstrip(".")
    assert "generative video tools" not in technology_widget["summary"]


def test_normalize_widgets_strips_dangling_to_be_item_endings():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    title = "California's primary for governor is undecided as candidates vie to be in the top two"
    stories = [
        {
            "id": "california-primary",
            "topic": "TOP_NEWS",
            "title": title,
            "summary": "Candidates are competing to reach the general election ballot.",
        }
    ]
    articles = [
        ArticleCandidate(
            id="california-primary",
            topic="TOP_NEWS",
            title=title,
            source="AP News",
            url="https://apnews.com/article/california-primary",
            description=stories[0]["summary"],
        )
    ]

    widgets = pipeline._normalize_widgets([], stories, articles)
    top_news_widget = next(widget for widget in widgets if widget["topic"] == "TOP_NEWS")

    assert top_news_widget["items"][0] == "California's primary for governor is undecided as candidates vie"
    assert not top_news_widget["items"][0].endswith("to be")


def test_grounded_top_level_copy_refreshes_old_fallback_dek():
    payload = {
        "headline": "Court ruling reshapes federal immigration enforcement",
        "dek": "Court ruling reshapes federal immigration enforcement leads alongside Storm recovery costs rise across the Gulf Coast.",
        "summary": "A concise source-backed update with enough detail for the brief.",
        "quick_hits": ["Court ruling reshapes federal immigration enforcement"],
    }

    _, dek, _, _ = DailyBriefPipeline._grounded_top_level_copy(
        payload=payload,
        stories=valid_quality_brief()["stories"],
    )

    assert "leads alongside" not in dek
    assert "lead today's brief" in dek
    assert "First current story" in dek
    assert "Second current story" in dek


def test_feed_cleanup_removes_google_news_cluster_artifacts():
    raw_description = (
        "France moves to repeal Code Noir, the slavery law it never abolished "
        "&nbsp;&nbsp; AP News Opinion | The Brutal History That France..."
    )

    assert (
        DailyBriefPipeline._clean_title(
            "The golden age of handheld gaming is already over - The Verge",
            source="The Verge",
        )
        == "The golden age of handheld gaming is already over"
    )
    assert (
        DailyBriefPipeline._clean_description(
            raw_description,
            title="France moves to repeal Code Noir, the slavery law it never abolished",
            source="AP News",
        )
        == ""
    )
    assert (
        DailyBriefPipeline._clean_description(
            "Sydney crowd told to target National MPs before a vote. Follow our Australia news live blog.",
            title="Barnaby Joyce rallies anti-abortion activists ahead of tight NSW vote",
            source="The Guardian",
        )
        == "Sydney crowd told to target National MPs before a vote."
    )
    assert (
        DailyBriefPipeline._clean_description(
            (
                "Three studies add to evidence that jabs could be part of cancer-fighting "
                "toolkit to cut risk of developing or dying from disease Weight-loss drugs "
                "can cut the risk by up to 30%."
            ),
            title="Weight-loss drugs can cut breast cancer risk by up to 30%, studies suggest",
            source="The Guardian",
        )
        == (
            "Three studies add to evidence that jabs could be part of cancer-fighting "
            "toolkit to cut risk of developing or dying from disease"
        )
    )


def test_quality_gate_rejects_visible_html_artifacts():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["stories"][0]["summary"] = "First current story &nbsp;&nbsp; Reuters"

    issues = pipeline._brief_quality_issues(brief)

    assert "story story-1 contains HTML entities" in issues


def test_quality_gate_rejects_google_wrappers_and_sparse_multimedia():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["hero_image_url"] = None
    for story in brief["stories"]:
        story.pop("image_url", None)
    brief["stories"][0]["url"] = "https://news.google.com/articles/CBMiBad"

    issues = pipeline._brief_quality_issues(brief)

    assert "story story-1 still uses Google News wrapper URL" in issues
    assert "leading stories need at least two image_url values" in issues


def test_quality_gate_rejects_hero_art_from_non_lead_story():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["hero_image_url"] = brief["stories"][1]["image_url"]

    issues = pipeline._brief_quality_issues(brief)

    assert "hero_image_url must come from the lead story" in issues


def test_quality_gate_rejects_badge_and_tiny_thumbnail_images():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["hero_image_url"] = (
        "https://assets.apnews.com/9f/14/e730153245ddbefdf1f69031adea/"
        "download-on-the-app-store-badge-us-uk-rgb-blk-01.png"
    )
    brief["stories"][0]["image_url"] = brief["hero_image_url"]
    brief["stories"][1]["image_url"] = (
        "https://media.npr.org/assets/img/2024/04/19/"
        "tile-wild-card-with-rachel-martin_sq-37e6eb53-s100-c100.jpg"
    )
    brief["stories"][2]["image_url"] = "https://images.cnbc.com/uploads/story-3-1366x768.jpg"

    issues = pipeline._brief_quality_issues(brief)

    assert "hero_image_url is not suitable for story art" in issues
    assert "story story-1 image_url is not suitable for story art" in issues
    assert "story story-2 image_url is not suitable for story art" in issues


def test_normalize_brief_strips_bad_story_art_before_quality_gate():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id="story-1",
            topic="TOP_NEWS",
            title="Top story with a badge image",
            source="AP News",
            url="https://apnews.com/article/story-1",
            description="A meaningful summary explains the current update with enough concrete detail.",
            image_url=(
                "https://assets.apnews.com/9f/14/e730153245ddbefdf1f69031adea/"
                "download-on-the-app-store-badge-us-uk-rgb-blk-01.png"
            ),
        ),
        ArticleCandidate(
            id="story-2",
            topic="TOP_NEWS",
            title="Second story with real art",
            source="Axios",
            url="https://www.axios.com/2026/05/28/story-2",
            description="Another useful update for the day.",
            image_url="https://images.axios.com/example/1366x768/2026/05/27/story.jpeg",
        ),
        ArticleCandidate(
            id="story-3",
            topic="BUSINESS",
            title="Third story with real art",
            source="CNBC",
            url="https://www.cnbc.com/2026/05/28/story-3.html",
            description="A market update with direct public impact.",
            image_url="https://images.cnbc.com/uploads/story-3-1366x768.jpg",
        ),
        ArticleCandidate(id="story-4", topic="WORLD", title="Fourth story", source="BBC", url="https://www.bbc.com/news/story-4", description="World context."),
        ArticleCandidate(id="story-5", topic="TECHNOLOGY", title="Fifth story", source="TechCrunch", url="https://techcrunch.com/story-5", description="Technology context."),
        ArticleCandidate(id="story-6", topic="HEALTH", title="Sixth story", source="STAT", url="https://www.statnews.com/story-6", description="Health context."),
    ]
    payload = {
        "headline": "Today's Brief",
        "summary": "A concise current summary.",
        "quick_hits": ["One", "Two"],
        "stories": [{"id": article.id} for article in articles],
        "sections": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "test-model")
    issues = pipeline._brief_quality_issues(brief)

    assert brief["stories"][0]["image_url"] is None
    assert brief["hero_image_url"] is None
    assert not any("image_url is not suitable" in issue for issue in issues)


def test_normalize_brief_replaces_generic_headline_with_specific_story_title():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = article_candidates_for_normalization()
    payload = {
        "headline": "Today's Brief",
        "summary": "A concise current summary.",
        "quick_hits": ["One", "Two"],
        "stories": [{"id": article.id} for article in articles],
        "sections": [],
    }

    brief = pipeline._normalize_brief(payload, articles, "test-model")

    assert brief["headline"] == "Court ruling reshapes federal immigration enforcement"
    assert "headline is generic" not in pipeline._brief_quality_issues(brief)


def test_normalize_sections_drops_invalid_non_sports_sections():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    stories = [
        {
            "id": "story-1",
            "topic": "TOP_NEWS",
            "title": "Court ruling reshapes federal immigration enforcement",
            "summary": "A concise source-backed update with enough detail for the brief.",
            "why_it_matters": "It changes enforcement priorities.",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/us/story-1",
        },
        {
            "id": "story-2",
            "topic": "TOP_NEWS",
            "title": "Storm recovery costs rise across the Gulf Coast",
            "summary": "A second source-backed update with enough detail for the brief.",
            "why_it_matters": "Budgets may need emergency support.",
            "source": "AP News",
            "url": "https://apnews.com/article/story-2",
        },
    ]
    sections = pipeline._sanitize_sections(
        [
            {
                "topic": "HEALTH",
                "title": "Health",
                "summary": "No matching health story exists.",
                "why_it_matters": "The section should not survive.",
                "story_ids": ["missing-story"],
            },
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1", "story-2"],
            },
        ],
        stories,
    )

    assert [section["topic"] for section in sections] == ["TOP_NEWS"]
    assert sections[0]["story_ids"] == ["story-1", "story-2"]


def test_sanitize_sections_augments_thin_top_news_references():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    stories = valid_quality_brief()["stories"]

    sections = pipeline._sanitize_sections(
        [
            {
                "topic": "TOP_NEWS",
                "title": "Top News",
                "summary": "The top items.",
                "why_it_matters": "They matter.",
                "story_ids": ["story-1"],
            }
        ],
        stories,
    )

    assert sections[0]["story_ids"][:2] == ["story-1", "story-2"]
    brief = valid_quality_brief()
    brief["sections"] = sections
    assert "TOP_NEWS section needs at least two real story references" not in pipeline._brief_quality_issues(brief)


def test_quality_gate_rejects_sports_story_drift():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    sports_story = brief["stories"][-1]
    sports_story.update(
        {
            "title": "Construction of cage-fighting arena transforms White House grounds",
            "summary": "The White House South Lawn is being converted into a UFC arena.",
            "why_it_matters": "The event changes public access around the grounds.",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/us/example",
        }
    )

    issues = pipeline._brief_quality_issues(brief)

    assert "sports story story-6 failed sports relevance gate" in issues


def test_coverage_report_counts_sources_topics_and_images():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = article_candidates_for_normalization()
    stories = [
        pipeline._normalized_story_from_article(article)
        for article in articles
    ]
    sections = pipeline._normalize_sections([], stories, articles)

    report = pipeline._coverage_report(
        stories=stories,
        articles=articles,
        sections=sections,
        candidate_topic_counts={"TOP_NEWS": 5, "WORLD": 4},
        now=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )

    assert report["source_packet_count"] == 6
    assert report["source_packet_domains"] == 6
    assert report["leading_trusted_story_count"] >= 5
    assert report["story_image_count"] == 2
    assert report["story_topic_counts"]["TOP_NEWS"] == 2
    assert report["candidate_topic_counts"] == {"TOP_NEWS": 5, "WORLD": 4}
    assert "TOP_NEWS" in report["section_topics"]


def test_quality_gate_rejects_single_source_overconcentration():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    for index, story in enumerate(brief["stories"][:3], start=1):
        story["source"] = "Reuters"
        story["url"] = f"https://www.reuters.com/world/us/repeated-{index}"

    issues = pipeline._brief_quality_issues(brief)

    assert "leading stories overrepresent a single source domain: reuters.com" in issues


def test_quality_gate_rejects_stale_leading_story_cluster():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    for story in brief["stories"][:4]:
        story["published_at"] = old_timestamp

    issues = pipeline._brief_quality_issues(brief)

    assert "too many leading stories are stale" in issues


def test_normalized_story_default_why_it_matters_is_not_generic_filler():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    story = pipeline._normalized_story_from_article(
        ArticleCandidate(
            id="tech-1",
            topic="TECHNOLOGY",
            title="Chipmaker expands domestic AI server production",
            source="The Verge",
            url="https://www.theverge.com/story-4",
            description="The company said it will build new production lines in Texas.",
        )
    )

    assert story["why_it_matters"] == "It can shift products, policy, or platform decisions"
    assert "High source weight" not in story["why_it_matters"]


def test_final_score_cards_expire_after_postgame_window():
    final_event = {
        **SAMPLE_SCORE_EVENT,
        "date": "2026-05-12T00:30:00Z",
        "status": {
            "type": {
                "state": "post",
                "shortDetail": "Final",
                "detail": "Final",
                "completed": True,
            }
        },
    }

    score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=final_event,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        verified_at="2026-05-12T04:09:07+00:00",
    )

    assert score is not None
    assert score["is_live"] is False
    assert score["is_final"] is True
    assert score["expires_at"] == "2026-05-12T06:30:00+00:00"
    assert datetime.fromisoformat(score["expires_at"]) > datetime.fromisoformat(score["event_date"])


def test_final_score_cards_do_not_survive_into_morning_brief():
    final_event = {
        **SAMPLE_SCORE_EVENT,
        "date": "2026-05-12T02:00:00Z",
        "status": {
            "type": {
                "state": "post",
                "shortDetail": "Final",
                "detail": "Final",
                "completed": True,
            }
        },
    }

    score = DailyBriefPipeline._parse_score_event(
        league="WNBA",
        event=final_event,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        verified_at="2026-05-12T12:00:00+00:00",
    )

    assert score is not None
    assert score["expires_at"] == "2026-05-12T08:00:00+00:00"
    assert not DailyBriefPipeline._score_card_is_displayable(
        score,
        datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
    )


def test_scheduled_score_cards_are_allowed_and_sorted_before_finals():
    scheduled_event = {
        **SAMPLE_SCORE_EVENT,
        "date": "2026-05-12T23:30:00Z",
        "status": {
            "type": {
                "state": "pre",
                "shortDetail": "7:30 PM EDT",
                "detail": "7:30 PM EDT",
                "completed": False,
            }
        },
        "competitions": [
            {
                **SAMPLE_SCORE_EVENT["competitions"][0],
                "competitors": [
                    {**competitor, "score": None}
                    for competitor in SAMPLE_SCORE_EVENT["competitions"][0]["competitors"]
                ],
            }
        ],
    }
    final_score = {
        "state": "post",
        "is_final": True,
        "timestamp": datetime(2026, 5, 12, 22, tzinfo=timezone.utc).timestamp(),
    }

    scheduled_score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=scheduled_event,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        verified_at="2026-05-12T04:09:07+00:00",
    )

    assert scheduled_score is not None
    assert scheduled_score["is_live"] is False
    assert scheduled_score["is_final"] is False
    assert scheduled_score["state"] == "pre"
    assert scheduled_score["home_team"]["score"] is None
    assert scheduled_score["expires_at"] == "2026-05-13T00:00:00+00:00"
    assert DailyBriefPipeline._score_card_sort_key(scheduled_score) < DailyBriefPipeline._score_card_sort_key(final_score)


def test_scheduled_score_cards_ignore_espn_zero_placeholders():
    scheduled_event = {
        **SAMPLE_SCORE_EVENT,
        "date": "2026-05-12T23:30:00Z",
        "status": {
            "type": {
                "state": "pre",
                "shortDetail": "7:30 PM EDT",
                "detail": "7:30 PM EDT",
                "completed": False,
            }
        },
        "competitions": [
            {
                **SAMPLE_SCORE_EVENT["competitions"][0],
                "competitors": [
                    {**competitor, "score": "0"}
                    for competitor in SAMPLE_SCORE_EVENT["competitions"][0]["competitors"]
                ],
            }
        ],
    }

    score = DailyBriefPipeline._parse_score_event(
        league="NBA",
        event=scheduled_event,
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        verified_at="2026-05-12T04:09:07+00:00",
    )

    assert score is not None
    assert score["state"] == "pre"
    assert score["home_team"]["score"] is None
    assert score["away_team"]["score"] is None
    assert " 0 " not in score["display"]


def test_score_cards_do_not_display_after_expiration():
    now = datetime(2026, 5, 12, 13, 0, tzinfo=timezone.utc)

    assert not DailyBriefPipeline._score_card_is_displayable(
        {"expires_at": "2026-05-12T12:30:00+00:00", "is_final": True},
        now,
    )
    assert DailyBriefPipeline._score_card_is_displayable(
        {"expires_at": "2026-05-12T13:30:00+00:00", "is_final": True},
        now,
    )


def test_archive_stale_firestore_scores_uses_sports_storage_cleanup():
    with patch(
        "newsaggregator.storage.sports_storage.SportsStorage.archive_stale_final_scores",
        return_value=3,
    ) as archive:
        assert DailyBriefPipeline._archive_stale_firestore_scores() == 3

    archive.assert_called_once_with()


def test_press_release_candidates_are_rejected_before_story_selection():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    candidate = pipeline._candidate_from_raw(
        {
            "title": "Legal Tech Startup Automates 70% of Contract Review Workload",
            "url": (
                "https://apnews.com/press-release/ein-presswire-newsmatics/"
                "legal-tech-startup-automates-contract-review"
            ),
            "source": "Associated Press",
            "description": "EIN Presswire press release distributed through AP.",
        },
        next(topic for topic in TOPICS if topic.code == "TECHNOLOGY"),
    )

    assert candidate is None


def test_low_density_filler_candidates_are_rejected_before_story_selection():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    topic_by_code = {topic.code: topic for topic in TOPICS}

    cases = [
        (
            {
                "title": "This is the Microsoft Surface Laptop Ultra with Nvidia RTX Spark",
                "url": "https://www.theverge.com/tech/940584/microsoft-surface-laptop-ultra-pictures",
                "source": "The Verge",
                "description": "A first-look photo post about a device shell.",
            },
            "TOP_NEWS",
        ),
        (
            {
                "title": "NBA brings back trophy image, script logo for Finals courts",
                "url": "https://www.espn.com/nba/story/_/id/48935292/nba-finals-courts",
                "source": "ESPN",
                "description": "A visual-branding note about the court design.",
            },
            "SPORTS",
        ),
        (
            {
                "title": "Golden Knights-Hurricanes Game 1 takeaways, grades, questions",
                "url": "https://www.espn.com/nhl/story/_/id/48960000/golden-knights-hurricanes-game-1",
                "source": "ESPN",
                "description": "A hub-style recap with generic grades and questions.",
            },
            "SPORTS",
        ),
        (
            {
                "title": "Canada formally requests 16-year renewal of North American free trade pact",
                "url": "https://www.bbc.com/news/articles/canada-usmca-renewal",
                "source": "BBC News",
                "description": "A trade minister asked North American counterparts to renew the USMCA trade pact.",
            },
            "SPORTS",
        ),
        (
            {
                "title": "United Airlines flight to Spain pulls U-turn, apparently over Bluetooth device name",
                "url": "https://www.npr.org/2026/05/31/nx-s1-5841913/united-airlines-flight-diversion-bluetooth",
                "source": "NPR",
                "description": "A strange-flight item without durable business importance.",
            },
            "BUSINESS",
        ),
        (
            {
                "title": "Family of Four Killed in Virginia Bus Crash",
                "url": "https://apnews.com/article/virginia-bus-crash-family-deaths",
                "source": "Associated Press",
                "description": "A localized tragedy involving a family traveling to a wedding.",
            },
            "TOP_NEWS",
        ),
        (
            {
                "title": "Exercise Aids Healthy Aging",
                "url": "https://www.naturalnews.com/2026-05-31-exercise-healthy-aging.html",
                "source": "Naturalnews.com",
                "description": "A health item from a source that should not enter a factual brief.",
            },
            "HEALTH",
        ),
        (
            {
                "title": "Opinion | The president's health is the people's business",
                "url": "https://www.washingtonpost.com/opinions/2026/05/31/president-health-public/",
                "source": "The Washington Post",
                "description": "An opinion column about politics and public disclosure.",
            },
            "HEALTH",
        ),
        (
            {
                "title": "The biggest permanent desert lake threatens with rising waters and hungry crocs",
                "url": "https://www.npr.org/2026/05/31/desert-lake-crocodiles",
                "source": "NPR Topics: Health",
                "description": "A climate and wildlife feature about flooding and crocodiles.",
            },
            "HEALTH",
        ),
        (
            {
                "title": "The hummingbird-red flower connection, with Harvard's Patrick McKenzie",
                "url": "https://awaytogarden.com/hummingbird-red-flower-connection/",
                "source": "A Way To Garden",
                "description": "A gardening interview that should not stand in for daily science news.",
            },
            "SCIENCE",
        ),
        (
            {
                "title": "Fire's Footprint on Santa Rosa Island",
                "url": "https://science.nasa.gov/earth/earth-observatory/fires-footprint-on-santa-rosa-island/",
                "source": "NASA",
                "description": (
                    "A satellite-image explainer about a wildland fire footprint, "
                    "not a current science or policy development."
                ),
            },
            "SCIENCE",
        ),
        (
            {
                "title": "007 First Light is already discounted for the PS5 and Steam",
                "url": "https://www.theverge.com/deals/2026/05/31/007-first-light-discount",
                "source": "The Verge",
                "description": "A shopping deal post rather than consequential technology news.",
            },
            "TECHNOLOGY",
        ),
        (
            {
                "title": "Platner's wife told campaign about sexually explicit texts he sent other women",
                "url": "https://www.cbsnews.com/news/platner-wife-campaign-texts/",
                "source": "CBS News",
                "description": "A domestic campaign-scandal item surfaced in the wrong section.",
            },
            "WORLD",
        ),
        (
            {
                "title": "Australia politics live: Chalmers says Wilson faces questions",
                "url": "https://www.theguardian.com/australia-news/live/2026/jun/02/australia-politics-live",
                "source": "World news | The Guardian",
                "description": "A rolling local politics ticker, not a concise global-impact story.",
            },
            "WORLD",
        ),
        (
            {
                "title": "CNBC Exclusive: Transcript: OpenAI CEO Sam Altman Speaks with CNBC's David Faber",
                "url": "https://www.cnbc.com/2026/06/02/transcript-openai-ceo-sam-altman.html",
                "source": "CNBC",
                "description": "Transcript of a television interview, not a clean reported story.",
            },
            "TECHNOLOGY",
        ),
        (
            {
                "title": "Alphabet shares drop after announcing $80bn share sale - business live",
                "url": "https://www.theguardian.com/business/live/2026/jun/02/markets-business-live",
                "source": "The Guardian",
                "description": "Rolling coverage of the latest economic and financial news.",
            },
            "BUSINESS",
        ),
    ]

    for raw_item, topic_code in cases:
        assert pipeline._candidate_from_raw(raw_item, topic_by_code[topic_code]) is None


def test_title_only_trusted_reporting_stays_in_source_packet():
    candidate = ArticleCandidate(
        id="reuters-title-only",
        topic="WORLD",
        title="European leaders agree on new defense financing",
        source="Reuters",
        url="https://www.reuters.com/world/europe/defense-financing-2026-05-31/",
    )
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    assert pipeline._should_keep_thin_candidate(candidate)


def test_top_news_candidates_are_reclassified_into_real_editorial_lanes():
    top_news = next(topic for topic in TOPICS if topic.code == "TOP_NEWS")
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    technology = pipeline._candidate_from_raw(
        {
            "title": "First Windows PC powered by Nvidia chips to debut next week",
            "url": "https://www.reuters.com/business/first-windows-pc-powered-by-nvidia-chips-2026-05-30/",
            "source": "Reuters",
            "description": "Nvidia chips are moving into a new Windows PC line.",
        },
        top_news,
    )
    world = pipeline._candidate_from_raw(
        {
            "title": "Japan seeks candid dialog, defense minister says",
            "url": "https://www.cnbc.com/2026/05/31/japan-defense-minister.html",
            "source": "CNBC",
            "description": "Japan's defense minister addressed regional security concerns.",
        },
        top_news,
    )
    business = pipeline._candidate_from_raw(
        {
            "title": "UAW to strike at key General Motors truck supplier plant",
            "url": "https://www.wsj.com/business/autos/uaw-general-motors-truck-supplier-strike",
            "source": "The Wall Street Journal",
            "description": "The labor action could disrupt General Motors truck production.",
        },
        top_news,
    )

    assert technology is not None
    assert technology.topic == "TECHNOLOGY"
    assert world is not None
    assert world.topic == "WORLD"
    assert business is not None
    assert business.topic == "BUSINESS"


def test_topic_selection_diversifies_domains_before_source_packet():
    articles = [
        ArticleCandidate(
            id=f"{domain}-{index}",
            topic="WORLD",
            title=f"World story {domain} {index}",
            source=domain,
            url=f"https://{domain}/story-{index}",
            score=100 - index,
        )
        for index, domain in enumerate(
            ["npr.org"] * 6 + ["bbc.com"] * 4 + ["theguardian.com"] * 4,
            start=1,
        )
    ]

    selected = DailyBriefPipeline._diversify_articles(articles, limit=8)
    domain_counts = Counter(DailyBriefPipeline._domain_name(article.url) for article in selected)

    assert domain_counts["npr.org"] <= 3
    assert len(domain_counts) >= 3


def test_source_packet_repairs_domain_breadth_without_breaking_topic_floors():
    domains = [
        "npr.org",
        "bbc.com",
        "reuters.com",
        "cnbc.com",
        "theverge.com",
        "statnews.com",
        "espn.com",
    ]
    topic_counts = [
        ("TOP_NEWS", 8),
        ("WORLD", 4),
        ("BUSINESS", 4),
        ("TECHNOLOGY", 4),
        ("HEALTH", 2),
        ("SCIENCE", 2),
        ("SPORTS", 3),
        ("ENTERTAINMENT", 1),
    ]
    articles: list[ArticleCandidate] = []
    score = 100
    for topic, count in topic_counts:
        for index in range(count):
            domain = "espn.com" if topic == "SPORTS" else domains[len(articles) % len(domains)]
            title = (
                f"NBA playoff injury report changes rotation {index}"
                if topic == "SPORTS"
                else f"{topic} source-backed story {index}"
            )
            articles.append(
                ArticleCandidate(
                    id=f"{topic.lower()}-{index}",
                    topic=topic,
                    title=title,
                    source="ESPN" if topic == "SPORTS" else domain,
                    url=(
                        f"https://www.espn.com/nba/story/{index}"
                        if topic == "SPORTS"
                        else f"https://{domain}/{topic.lower()}/story-{index}"
                    ),
                    description="A current source-backed item with enough detail for the daily brief.",
                    score=score,
                )
            )
            score -= 1
    local_candidate = ArticleCandidate(
        id="local-rare-domain",
        topic="LOCAL",
        title="Local board approves new transit funding",
        source="City Desk",
        url="https://citydesk.example/local/transit-funding",
        description="A rare-domain item from a topic that cannot replace a required source-packet floor.",
        score=score,
    )
    ap_candidate = ArticleCandidate(
        id="ap-world-rare-domain",
        topic="WORLD",
        title="World leaders agree on new security financing",
        source="AP News",
        url="https://apnews.com/article/world-security-financing-rare-domain",
        description="A current world story from a domain missing from the selected packet.",
        score=1,
    )

    selected = DailyBriefPipeline._ensure_minimum_source_domains(
        articles.copy(),
        [*articles, local_candidate, ap_candidate],
        minimum=8,
        limit=len(articles),
    )
    selected_domains = Counter(DailyBriefPipeline._domain_name(article.url) for article in selected)
    selected_topics = Counter(DailyBriefPipeline._normalize_topic(article.topic) for article in selected)

    assert len(selected) == len(articles)
    assert len(selected_domains) >= 8
    assert "apnews.com" in selected_domains
    assert "citydesk.example" not in selected_domains
    assert selected_topics["WORLD"] >= 4
    assert selected_topics["TOP_NEWS"] >= 8


def test_topic_floor_repair_replaces_overrepresented_topics_before_floor_topics():
    selected: list[ArticleCandidate] = []
    for topic, count in [
        ("TOP_NEWS", 12),
        ("WORLD", 4),
        ("BUSINESS", 4),
        ("TECHNOLOGY", 4),
        ("HEALTH", 2),
        ("SCIENCE", 2),
    ]:
        for index in range(count):
            selected.append(
                ArticleCandidate(
                    id=f"{topic.lower()}-{index}",
                    topic=topic,
                    title=f"{topic} source-backed story {index}",
                    source="Associated Press",
                    url=f"https://source-{topic.lower()}-{index}.example.com/story",
                    description="A current source-backed item with enough detail for the daily brief.",
                    score=100 - len(selected),
                )
            )

    sports_articles = [
        ArticleCandidate(
            id=f"sports-{index}",
            topic="SPORTS",
            title=f"NBA playoff rotation report changes matchup {index}",
            source="ESPN",
            url=f"https://www.espn.com/nba/story/_/id/sports-{index}/playoff-rotation",
            description="A current NBA playoff report with enough detail for the daily brief.",
            score=20 - index,
        )
        for index in range(3)
    ]

    repaired = DailyBriefPipeline._ensure_minimum_topic_articles(
        selected.copy(),
        [*selected, *sports_articles],
        topic="SPORTS",
        minimum=3,
        limit=len(selected),
    )
    selected_topics = Counter(DailyBriefPipeline._normalize_topic(article.topic) for article in repaired)

    assert selected_topics["SPORTS"] == 3
    assert selected_topics["TOP_NEWS"] == 9
    assert selected_topics["WORLD"] >= 4
    assert selected_topics["BUSINESS"] >= 4
    assert selected_topics["TECHNOLOGY"] >= 4
    assert selected_topics["HEALTH"] >= 2
    assert selected_topics["SCIENCE"] >= 2


def test_source_packet_floor_repair_backfills_enrichment_dropouts():
    source_packet: list[ArticleCandidate] = []
    for topic, count in [
        ("TOP_NEWS", 8),
        ("WORLD", 4),
        ("BUSINESS", 4),
        ("TECHNOLOGY", 4),
        ("HEALTH", 2),
        ("SCIENCE", 2),
        ("SPORTS", 3),
        ("ENTERTAINMENT", 1),
    ]:
        for index in range(count):
            title = (
                f"NBA playoff rotation report changes matchup {index}"
                if topic == "SPORTS"
                else f"{topic} source-backed story {index}"
            )
            source_packet.append(
                ArticleCandidate(
                    id=f"{topic.lower()}-{index}",
                    topic=topic,
                    title=title,
                    source="ESPN" if topic == "SPORTS" else "Associated Press",
                    url=(
                        f"https://www.espn.com/nba/story/_/id/{index}/playoff-rotation"
                        if topic == "SPORTS"
                        else f"https://source-{topic.lower()}-{index}.example.com/story"
                    ),
                    description="A current source-backed item with enough detail for the daily brief.",
                    score=100 - len(source_packet),
                )
            )

    enriched = [
        article
        for article in source_packet
        if not (DailyBriefPipeline._normalize_topic(article.topic) == "TOP_NEWS" and article.id.endswith(("-6", "-7")))
    ]

    repaired = DailyBriefPipeline._ensure_source_packet_topic_floors(
        enriched,
        source_packet,
        limit=len(source_packet),
    )
    selected_topics = Counter(DailyBriefPipeline._normalize_topic(article.topic) for article in repaired)

    assert len(repaired) == len(source_packet)
    assert selected_topics["TOP_NEWS"] == 8
    assert selected_topics["WORLD"] >= 4
    assert selected_topics["BUSINESS"] >= 4
    assert selected_topics["TECHNOLOGY"] >= 4
    assert selected_topics["HEALTH"] >= 2
    assert selected_topics["SCIENCE"] >= 2
    assert selected_topics["SPORTS"] >= 3


def test_candidate_dedupe_removes_paraphrased_same_story_before_source_packet():
    articles = [
        ArticleCandidate(
            id="local-kennedy",
            topic="TOP_NEWS",
            title="Judge orders president's name off Kennedy Center",
            source="Local Arts Wire",
            url="https://local.example.com/kennedy-center-name-order",
            description="A judge ruled on the Kennedy Center naming dispute.",
            score=12,
        ),
        ArticleCandidate(
            id="trusted-kennedy",
            topic="TOP_NEWS",
            title="Trump's Kennedy Center plans were blocked by a judge",
            source="Washington Post",
            url="https://www.washingtonpost.com/style/kennedy-center-ruling",
            description="The ruling blocks a disputed Kennedy Center naming plan.",
            score=24,
        ),
        ArticleCandidate(
            id="world-security",
            topic="WORLD",
            title="European leaders agree on new defense financing",
            source="Reuters",
            url="https://www.reuters.com/world/europe/defense-financing",
            description="The agreement changes near-term NATO budgeting.",
            score=20,
        ),
    ]

    deduped = DailyBriefPipeline._dedupe(articles)
    ids = {article.id for article in deduped}

    assert "trusted-kennedy" in ids
    assert "local-kennedy" not in ids
    assert "world-security" in ids


def test_candidate_dedupe_keeps_distinct_same_entity_stories():
    articles = [
        ArticleCandidate(
            id="kennedy",
            topic="TOP_NEWS",
            title="Trump's Kennedy Center plans were blocked by a judge",
            source="Washington Post",
            url="https://www.washingtonpost.com/style/kennedy-center-ruling",
            score=24,
        ),
        ArticleCandidate(
            id="tariffs",
            topic="BUSINESS",
            title="Trump tariff pause shifts automaker supply plans",
            source="Reuters",
            url="https://www.reuters.com/business/autos/tariff-pause",
            score=23,
        ),
    ]

    deduped = DailyBriefPipeline._dedupe(articles)

    assert [article.id for article in deduped] == ["kennedy", "tariffs"]


def test_source_packet_order_does_not_frontload_sports():
    articles = [
        ArticleCandidate(
            id=f"sports-{index}",
            topic="SPORTS",
            title=f"NBA playoff game {index}",
            source="ESPN",
            url=f"https://www.espn.com/nba/story/{index}",
            score=100 - index,
        )
        for index in range(1, 7)
    ] + [
        ArticleCandidate(
            id=topic.lower(),
            topic=topic,
            title=f"{topic} major story",
            source=source,
            url=url,
            score=50 - index,
        )
        for index, (topic, source, url) in enumerate(
            [
                ("TOP_NEWS", "Reuters", "https://www.reuters.com/world/us/major-story"),
                ("WORLD", "BBC", "https://www.bbc.com/news/world-major-story"),
                ("BUSINESS", "CNBC", "https://www.cnbc.com/business-major-story"),
                ("TECHNOLOGY", "The Verge", "https://www.theverge.com/tech/major-story"),
                ("HEALTH", "STAT", "https://www.statnews.com/health/major-story"),
                ("SCIENCE", "NASA", "https://www.nasa.gov/news-release/major-story"),
            ],
            start=1,
        )
    ]

    ordered = DailyBriefPipeline._rebalance_article_order(articles)
    leading_topics = Counter(article.topic for article in ordered[:8])

    assert ordered[0].topic == "TOP_NEWS"
    assert leading_topics["SPORTS"] <= 2
    assert len({DailyBriefPipeline._domain_name(article.url) for article in ordered[:8]}) >= 4


def test_publish_story_filter_removes_editorial_failures_before_quality_gate():
    stories = [
        {
            "id": "good-world",
            "topic": "WORLD",
            "title": "European leaders agree on new defense financing",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/europe/defense-financing",
            "summary": "The agreement changes near-term defense planning.",
            "why_it_matters": "It affects security budgets and NATO planning.",
        },
        {
            "id": "bad-health",
            "topic": "HEALTH",
            "title": "Opinion | The president's health is the people's business",
            "source": "The Washington Post",
            "url": "https://www.washingtonpost.com/opinions/president-health",
            "summary": "Opinion column about political disclosure.",
            "why_it_matters": "It is commentary rather than factual health coverage.",
        },
        {
            "id": "bad-sports",
            "topic": "SPORTS",
            "title": "A celebrity watches from courtside",
            "source": "NPR",
            "url": "https://www.npr.org/2026/05/31/courtside-celebrity",
            "summary": "A culture item about a celebrity appearance.",
            "why_it_matters": "It is entertainment context rather than team coverage.",
        },
        {
            "id": "bad-transcript",
            "topic": "TECHNOLOGY",
            "title": "CNBC Exclusive: Transcript: OpenAI CEO Sam Altman Speaks with CNBC's David Faber",
            "source": "CNBC",
            "url": "https://www.cnbc.com/2026/06/02/transcript-openai-ceo-sam-altman.html",
            "summary": "com",
            "why_it_matters": "It affects AI infrastructure and platform planning.",
        },
        {
            "id": "bad-liveblog",
            "topic": "BUSINESS",
            "title": "Alphabet shares drop after announcing $80bn share sale - business live",
            "source": "The Guardian",
            "url": "https://www.theguardian.com/business/live/2026/jun/02/markets-business-live",
            "summary": "Rolling coverage of the latest economic and financial news.",
            "why_it_matters": "It affects market and technology company coverage.",
        },
    ]

    filtered = DailyBriefPipeline._filter_story_list_for_publish(stories)

    assert [story["id"] for story in filtered] == ["good-world"]


def test_quality_gate_rejects_single_word_story_summary():
    brief = valid_quality_brief()
    brief["stories"][0]["summary"] = "com"
    brief["stories"][1]["summary"] = brief["stories"][1]["title"]
    brief["stories"][2]["summary"] = "Please enable JS and disable any ad blocker."
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert "story story-1 has an unusable summary" in issues
    assert "story story-2 has an unusable summary" in issues
    assert "story story-3 has an unusable summary" in issues


def test_quality_gate_requires_supported_topic_breadth():
    brief = valid_quality_brief()
    brief["coverage_report"] = {
        "source_packet_count": 36,
        "source_packet_domains": 14,
        "topic_counts": {
            "TOP_NEWS": 8,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert any("visible stories miss source-supported coverage lanes" in issue for issue in issues)


def test_quality_gate_rejects_source_packet_topic_floor_gaps():
    brief = valid_quality_brief()
    brief["coverage_report"] = {
        "source_packet_count": 36,
        "source_packet_domains": 14,
        "topic_counts": {
            "TOP_NEWS": 6,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 1,
            "SCIENCE": 2,
            "SPORTS": 2,
            "ENTERTAINMENT": 1,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert (
        "source packet misses V8 topic floors: TOP_NEWS 6/8, HEALTH 1/2, SPORTS 2/3"
        in issues
    )


def test_quality_gate_allows_topic_floor_limited_by_available_candidates():
    brief = valid_quality_brief()
    brief["coverage_report"] = {
        "source_packet_count": 35,
        "source_packet_domains": 14,
        "candidate_topic_counts": {
            "TOP_NEWS": 7,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
            "ENTERTAINMENT": 1,
        },
        "topic_counts": {
            "TOP_NEWS": 7,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
            "ENTERTAINMENT": 1,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert not any("source packet misses V8 topic floors" in issue for issue in issues)


def test_quality_gate_rejects_source_packet_below_available_topic_pool():
    brief = valid_quality_brief()
    brief["coverage_report"] = {
        "source_packet_count": 35,
        "source_packet_domains": 14,
        "candidate_topic_counts": {
            "TOP_NEWS": 7,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
            "ENTERTAINMENT": 1,
        },
        "topic_counts": {
            "TOP_NEWS": 6,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
            "ENTERTAINMENT": 1,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert (
        "source packet misses V8 topic floors: TOP_NEWS 6/7 available (floor 8)"
        in issues
    )


def test_quality_gate_requires_science_when_source_supported():
    brief = valid_quality_brief()
    brief["stories"].append(
        {
            "id": "story-7",
            "topic": "HEALTH",
            "title": "Hospitals prepare for summer virus uptick",
            "summary": "Health systems are preparing staffing plans as seasonal indicators rise.",
            "why_it_matters": "The preparations can affect local care access.",
            "source": "STAT",
            "url": "https://www.statnews.com/2026/05/31/summer-virus-hospitals",
        }
    )
    brief["coverage_report"] = {
        "source_packet_count": 30,
        "source_packet_domains": 14,
        "topic_counts": {
            "TOP_NEWS": 8,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert any("science item when source-supported" in issue for issue in issues)


def test_quality_gate_does_not_force_entertainment_lane():
    brief = valid_quality_brief()
    brief["stories"].extend(
        [
            {
                "id": "story-7",
                "topic": "HEALTH",
                "title": "Hospitals prepare for summer virus uptick",
                "summary": "Health systems are preparing staffing plans as seasonal indicators rise.",
                "why_it_matters": "The preparations can affect local care access.",
                "source": "STAT",
                "url": "https://www.statnews.com/2026/05/31/summer-virus-hospitals",
            },
            {
                "id": "story-8",
                "topic": "SCIENCE",
                "title": "Meteor blast data updates NASA risk models",
                "summary": "Researchers are updating regional blast models after a meteor exploded in the atmosphere.",
                "why_it_matters": "The data can improve public warning systems.",
                "source": "ScienceAlert",
                "url": "https://www.sciencealert.com/meteor-blast-data",
            },
        ]
    )
    brief["coverage_report"] = {
        "source_packet_count": 30,
        "source_packet_domains": 14,
        "topic_counts": {
            "TOP_NEWS": 8,
            "WORLD": 4,
            "BUSINESS": 4,
            "TECHNOLOGY": 4,
            "HEALTH": 2,
            "SCIENCE": 2,
            "SPORTS": 3,
            "ENTERTAINMENT": 8,
        },
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert not any("ENTERTAINMENT" in issue for issue in issues)


def test_quality_gate_rejects_press_release_story_values():
    brief = valid_quality_brief()
    brief["stories"][2] = {
        **brief["stories"][2],
        "title": "UiPath Reports First Quarter Fiscal 2027 Financial Results",
        "source": "AP News",
        "url": "https://apnews.com/press-release/business-wire/uipath-reports-results",
    }
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(brief)

    assert any("failed editorial value gate" in issue for issue in issues)


def test_story_rebalancing_prevents_sports_from_crowding_the_lead():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id=f"story-{index}",
            topic=topic,
            title=f"{topic} story {index}",
            source=source,
            url=url,
            score=score,
        )
        for index, (topic, source, url, score) in enumerate(
            [
                ("SPORTS", "ESPN", "https://www.espn.com/nba/story/1", 30),
                ("SPORTS", "ESPN", "https://www.espn.com/nba/story/2", 29),
                ("SPORTS", "ESPN", "https://www.espn.com/nba/story/3", 28),
                ("TOP_NEWS", "Reuters", "https://www.reuters.com/world/us/story", 18),
                ("WORLD", "BBC", "https://www.bbc.com/news/world", 17),
                ("BUSINESS", "CNBC", "https://www.cnbc.com/business", 16),
                ("TECHNOLOGY", "The Verge", "https://www.theverge.com/tech", 15),
                ("HEALTH", "STAT", "https://www.statnews.com/health", 14),
                ("ENTERTAINMENT", "Variety", "https://variety.com/culture", 13),
            ],
            start=1,
        )
    ]
    stories = [pipeline._normalized_story_from_article(article) for article in articles]

    rebalanced = pipeline._rebalance_story_order(stories, articles)

    assert rebalanced[0]["topic"] == "TOP_NEWS"
    assert sum(1 for story in rebalanced[:8] if story["topic"] == "SPORTS") <= 2


def test_leading_domain_diversity_repairs_model_overfocus_on_one_source():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    npr_articles = [
        ArticleCandidate(
            id=f"npr-{index}",
            topic=topic,
            title=title,
            source="NPR",
            url=f"https://www.npr.org/2026/06/02/story-{index}",
            description="A current source-backed update with enough detail.",
            score=30 - index,
        )
        for index, (topic, title) in enumerate(
            [
                ("TOP_NEWS", "Federal court blocks disputed enforcement rule"),
                ("WORLD", "Ceasefire talks resume after cross-border attacks"),
                ("BUSINESS", "Labor regulators revise workplace complaint process"),
                ("TECHNOLOGY", "AI security breach forces new account safeguards"),
                ("HEALTH", "Hospitals adjust cancer screening guidance"),
                ("SCIENCE", "Researchers publish new climate risk model"),
                ("SPORTS", "NBA playoff injury report changes rotation"),
                ("ENTERTAINMENT", "Studios delay summer film release slate"),
            ],
            start=1,
        )
    ]
    replacement_articles = [
        ArticleCandidate(
            id="reuters-business",
            topic="BUSINESS",
            title="Automakers brace for new supplier strike deadline",
            source="Reuters",
            url="https://www.reuters.com/business/autos/supplier-strike",
            description="A strike deadline could disrupt truck production.",
            image_url="https://static.reuters.com/images/autos-1200.jpg",
            score=24,
        ),
        ArticleCandidate(
            id="bbc-world",
            topic="WORLD",
            title="European leaders reach security financing agreement",
            source="BBC",
            url="https://www.bbc.com/news/world-europe-security-financing",
            description="The deal affects regional defense planning.",
            image_url="https://ichef.bbci.co.uk/news/480/security.jpg.webp",
            score=23,
        ),
        ArticleCandidate(
            id="cnbc-tech",
            topic="TECHNOLOGY",
            title="Chipmaker export rules change AI server plans",
            source="CNBC",
            url="https://www.cnbc.com/2026/06/02/chipmaker-export-rules.html",
            description="The policy change affects AI infrastructure spending.",
            image_url="https://images.cnbc.com/uploads/chips-1200.jpg",
            score=22,
        ),
        ArticleCandidate(
            id="ap-health",
            topic="HEALTH",
            title="FDA approves new hospital infection guidance",
            source="AP News",
            url="https://apnews.com/article/fda-hospital-infection-guidance",
            description="The guidance changes hospital infection-control planning.",
            image_url="https://dims.apnews.com/dims4/default/health/resize/1200x800.jpg",
            score=21,
        ),
        ArticleCandidate(
            id="stat-science",
            topic="SCIENCE",
            title="Researchers map new cancer vaccine response",
            source="STAT",
            url="https://www.statnews.com/2026/06/02/cancer-vaccine-response",
            description="The study gives researchers new vaccine-response evidence.",
            image_url="https://www.statnews.com/wp-content/uploads/2026/06/vaccine-1200.jpg",
            score=20,
        ),
        ArticleCandidate(
            id="guardian-culture",
            topic="ENTERTAINMENT",
            title="Studios revise release plans after theater slowdown",
            source="The Guardian",
            url="https://www.theguardian.com/film/2026/jun/02/studios-release-plans",
            description="The shift affects the summer box-office calendar.",
            image_url="https://i.guim.co.uk/img/media/releases.jpg?width=1200&format=jpg",
            score=19,
        ),
    ]
    articles = npr_articles + replacement_articles
    stories = [pipeline._normalized_story_from_article(article) for article in npr_articles]

    repaired = pipeline._ensure_leading_domain_diversity(stories, articles)
    leading_domains = [
        DailyBriefPipeline._domain_name(str(story.get("url") or ""))
        for story in repaired[:8]
    ]

    assert Counter(leading_domains)["npr.org"] <= 2
    assert len(set(leading_domains)) >= 4
    assert {"reuters-business", "bbc-world", "cnbc-tech", "ap-health"}.issubset(
        {str(story.get("id")) for story in repaired[:8]}
    )


def test_visible_source_supported_topic_repair_promotes_science_into_first_twelve():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id=f"top-{index}",
            topic="TOP_NEWS",
            title=f"Federal policy update changes agency deadline {index}",
            source="Reuters" if index == 1 else "AP News",
            url=f"https://www.reuters.com/world/us/policy-deadline-{index}",
            description="A current public-impact update with concrete details.",
            score=30 - index,
        )
        for index in range(1, 4)
    ]
    articles.extend(
        [
            ArticleCandidate(
                id="world-1",
                topic="WORLD",
                title="European leaders agree new security financing plan",
                source="BBC",
                url="https://www.bbc.com/news/world-europe-security-financing",
                description="The agreement changes regional defense planning.",
                score=25,
            ),
            ArticleCandidate(
                id="world-2",
                topic="WORLD",
                title="Ukraine aid talks restart before summit",
                source="AP News",
                url="https://apnews.com/article/ukraine-aid-talks",
                description="The talks affect diplomatic planning before the summit.",
                score=24,
            ),
            ArticleCandidate(
                id="business-1",
                topic="BUSINESS",
                title="Automaker supplier strike deadline nears",
                source="Reuters",
                url="https://www.reuters.com/business/autos/supplier-strike-deadline",
                description="The deadline could disrupt truck production.",
                score=23,
            ),
            ArticleCandidate(
                id="business-2",
                topic="BUSINESS",
                title="Bond market warning changes inflation outlook",
                source="CNBC",
                url="https://www.cnbc.com/2026/06/02/bond-market-warning.html",
                description="The shift affects borrowing costs and investor expectations.",
                score=22,
            ),
            ArticleCandidate(
                id="tech-1",
                topic="TECHNOLOGY",
                title="Chip export rules change AI server plans",
                source="The Verge",
                url="https://www.theverge.com/2026/6/2/chip-export-rules-ai-servers",
                description="The rules affect AI infrastructure buildouts.",
                score=21,
            ),
            ArticleCandidate(
                id="tech-2",
                topic="TECHNOLOGY",
                title="Cybersecurity flaw forces cloud account resets",
                source="TechCrunch",
                url="https://techcrunch.com/2026/06/02/cloud-account-resets",
                description="The flaw changes account-security plans for enterprise teams.",
                score=20,
            ),
            ArticleCandidate(
                id="health-1",
                topic="HEALTH",
                title="Hospitals prepare for summer virus uptick",
                source="STAT",
                url="https://www.statnews.com/2026/06/02/summer-virus-hospitals",
                description="Hospitals are adjusting staffing plans as seasonal indicators rise.",
                score=19,
            ),
            ArticleCandidate(
                id="sports-1",
                topic="SPORTS",
                title="Thunder injury changes NBA Finals rotation",
                source="ESPN",
                url="https://www.espn.com/nba/story/_/id/thunder-finals-rotation",
                description="The injury report changes rotations before the next game.",
                score=18,
            ),
            ArticleCandidate(
                id="sports-2",
                topic="SPORTS",
                title="Mariners winning streak shifts MLB playoff race",
                source="ESPN",
                url="https://www.espn.com/mlb/story/_/id/mariners-winning-streak",
                description="The streak changes the division race and wild-card picture.",
                score=17,
            ),
            ArticleCandidate(
                id="science-1",
                topic="SCIENCE",
                title="Researchers publish new ocean heat risk model",
                source="ScienceAlert",
                url="https://www.sciencealert.com/ocean-heat-risk-model",
                description="The model gives researchers new evidence for coastal risk planning.",
                score=16,
            ),
            ArticleCandidate(
                id="science-2",
                topic="SCIENCE",
                title="NASA climate data updates flood projections",
                source="NASA",
                url="https://www.nasa.gov/science/climate-data-flood-projections",
                description="The data changes flood projections used by planners.",
                score=15,
            ),
        ]
    )
    model_stories = [
        pipeline._normalized_story_from_article(article)
        for article in articles
        if article.topic != "SCIENCE"
    ][:12]

    repaired = pipeline._ensure_visible_source_supported_topics(model_stories, articles)
    visible_topics = {
        DailyBriefPipeline._normalize_topic(story.get("topic"))
        for story in repaired[:12]
    }

    assert "SCIENCE" in visible_topics
    assert {"science-1", "science-2"} & {str(story.get("id")) for story in repaired[:12]}


def test_story_rebalancing_removes_near_duplicate_story_slots():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    articles = [
        ArticleCandidate(
            id="kennedy-1",
            topic="TOP_NEWS",
            title="Trump's Kennedy Center plans were blocked by a judge",
            source="Washington Post",
            url="https://www.washingtonpost.com/style/kennedy-center",
            score=20,
        ),
        ArticleCandidate(
            id="kennedy-2",
            topic="TOP_NEWS",
            title="Judge orders president's name off Kennedy Center",
            source="The New York Times",
            url="https://www.nytimes.com/live/trump-news",
            score=19,
        ),
        ArticleCandidate(
            id="world-1",
            topic="WORLD",
            title="Japan defense minister urges candid regional dialogue",
            source="CNBC",
            url="https://www.cnbc.com/japan-defense",
            score=18,
        ),
    ]
    stories = [pipeline._normalized_story_from_article(article) for article in articles]

    rebalanced = pipeline._rebalance_story_order(stories, articles)

    titles = [story["title"] for story in rebalanced]
    assert "Trump's Kennedy Center plans were blocked by a judge" in titles
    assert "Judge orders president's name off Kennedy Center" not in titles


def test_story_image_coverage_replaces_image_less_tail_stories():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    image_url = "https://images.example.com/media/story/abc123?w=1200&format=webp"
    articles = [
        ArticleCandidate(
            id="top",
            topic="TOP_NEWS",
            title="Federal court blocks disputed enforcement rule",
            source="Reuters",
            url="https://www.reuters.com/world/us/top",
            image_url=image_url,
            score=20,
        ),
        ArticleCandidate(
            id="world",
            topic="WORLD",
            title="European leaders reach security financing deal",
            source="BBC",
            url="https://www.bbc.com/news/world",
            image_url=image_url,
            score=19,
        ),
        ArticleCandidate(
            id="business-missing",
            topic="BUSINESS",
            title="Automaker supplier labor talks stall before deadline",
            source="WSJ",
            url="https://www.wsj.com/business/autos/labor",
            score=18,
        ),
        ArticleCandidate(
            id="sports-missing",
            topic="SPORTS",
            title="Mariners winning streak shifts playoff race",
            source="ESPN",
            url="https://www.espn.com/mlb/story/mariners-winning-streak",
            score=17,
        ),
        ArticleCandidate(
            id="business-image",
            topic="BUSINESS",
            title="Bond market warning changes inflation outlook",
            source="AP News",
            url="https://apnews.com/article/bond-market-warning",
            description="A bond-market signal is changing inflation expectations for investors and policymakers.",
            image_url=image_url,
            score=16,
        ),
    ]
    stories = [pipeline._normalized_story_from_article(article) for article in articles[:4]]

    repaired = pipeline._ensure_story_image_coverage(stories, articles)

    assert len(repaired) == 4
    assert sum(DailyBriefPipeline._story_has_valid_image(story) for story in repaired) >= 3
    assert "business-image" in {story["id"] for story in repaired}


def test_story_image_coverage_preserves_image_less_lead_story():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    image_url = "https://images.example.com/media/story/abc123?w=1200&format=webp"
    articles = [
        ArticleCandidate(
            id="lead",
            topic="TOP_NEWS",
            title="US says it struck Iranian military sites",
            source="Reuters",
            url="https://www.reuters.com/world/middle-east/iran-strikes",
            score=30,
        ),
        ArticleCandidate(
            id="world",
            topic="WORLD",
            title="Malaysia enforces youth social media ban",
            source="AP News",
            url="https://apnews.com/article/malaysia-social-media-ban",
            image_url=image_url,
            score=20,
        ),
        ArticleCandidate(
            id="business",
            topic="BUSINESS",
            title="Bond market warning changes inflation outlook",
            source="AP News",
            url="https://apnews.com/article/bond-market-warning",
            image_url=image_url,
            score=19,
        ),
        ArticleCandidate(
            id="sports-missing",
            topic="SPORTS",
            title="Mariners winning streak shifts playoff race",
            source="ESPN",
            url="https://www.espn.com/mlb/story/mariners-winning-streak",
            score=18,
        ),
        ArticleCandidate(
            id="sports-image",
            topic="SPORTS",
            title="Thunder injury changes Finals rotation",
            source="ESPN",
            url="https://www.espn.com/nba/story/thunder-finals-rotation",
            description="A Thunder injury update changes the rotation before the next Finals matchup.",
            image_url=image_url,
            score=17,
        ),
    ]
    stories = [pipeline._normalized_story_from_article(article) for article in articles[:4]]

    repaired = pipeline._ensure_story_image_coverage(stories, articles)

    assert repaired[0]["id"] == "lead"
    assert not DailyBriefPipeline._story_has_valid_image(repaired[0])
    assert "sports-image" in {story["id"] for story in repaired}
    assert sum(DailyBriefPipeline._story_has_valid_image(story) for story in repaired) >= 3


def test_story_image_coverage_trims_image_less_tail_when_no_replacement_exists():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    image_url = "https://images.example.com/media/story/abc123?w=1200&format=webp"
    articles = [
        ArticleCandidate(
            id=f"story-{index}",
            topic="TOP_NEWS" if index == 1 else "BUSINESS",
            title=f"Distinct current story {index}",
            source="Reuters" if index <= 3 else "WSJ",
            url=f"https://example.com/story-{index}",
            image_url=image_url if index <= 8 else None,
            score=20 - index,
        )
        for index in range(1, 12)
    ]
    stories = [pipeline._normalized_story_from_article(article) for article in articles]

    repaired = pipeline._ensure_story_image_coverage(stories, articles)

    assert len(repaired) == 10
    assert sum(DailyBriefPipeline._story_has_valid_image(story) for story in repaired) == 8


def test_image_url_filter_accepts_validated_cdn_image_shapes():
    assert ArticleFetcher._is_valid_image_url(
        "https://images.example.com/media/story/abc123?w=1200&format=webp"
    )
    assert ArticleFetcher._is_valid_image_url(
        "https://images.ctfassets.net/site/asset-id/briefsnap-news-image"
    )
    assert ArticleFetcher._is_valid_image_url(
        "https://dims.apnews.com/dims4/default/ab25a62/2147483647/strip/true/"
        "crop/1189x792+6+0/resize/980x653!/quality/90/?url=https%3A%2F%2Fassets.apnews.com"
        "%2F0d%2Ff2%2Fff2f23bdb777c03a9debb384aee8%2F3f54babfbdf04c7f803715488dd5228e"
    )
    assert not ArticleFetcher._is_valid_image_url(
        "https://example.com/assets/logo.svg"
    )
    assert not ArticleFetcher._is_valid_image_url(
        "https://assets.apnews.com/9f/14/download-on-the-app-store-badge-us-uk-rgb-blk-01.png"
    )
    assert not ArticleFetcher._is_valid_image_url(
        "https://media.npr.org/assets/img/tile-wild-card_sq-37e6eb53-s100-c100.jpg"
    )
    assert not ArticleFetcher._is_valid_image_url(
        "https://www.washingtonpost.com/dr/resources/images/generic-newsletter-signup.png"
    )
    assert not ArticleFetcher._is_valid_image_url(
        "https://media.npr.org/include/images/facebook-default-wide-s1400-c85.jpg"
    )


def test_scrape_candidate_resolves_google_news_before_image_enrichment():
    calls = []

    def fake_extract(url):
        calls.append(("extract", url))
        return "https://apnews.com/article/current-story?utm_source=news"

    def fake_scrape(url):
        calls.append(("scrape", url))
        return "Reported article text with enough detail to improve the source packet.", None

    def fake_find_images(url):
        calls.append(("images", url))
        return ["https://assets.apnews.com/media/current-story/photo-1200.jpg"]

    def fake_select_best_image(image_urls, fallback_urls=None, max_fallback_articles=3):
        calls.append(("select", tuple(image_urls), tuple(fallback_urls or []), max_fallback_articles))
        return image_urls[0]

    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    candidate = ArticleCandidate(
        id="story-1",
        topic="TOP_NEWS",
        title="A current sourced story clears the quality bar",
        source="Associated Press",
        url="https://news.google.com/articles/CBMiExample",
        description="A concise feed description.",
        score=12,
    )

    with patch.object(ArticleFetcher, "extract_real_url_from_google", fake_extract), patch.object(
        ArticleFetcher,
        "scrape_article_content",
        fake_scrape,
    ), patch.object(ArticleFetcher, "find_article_images", fake_find_images), patch.object(
        ArticleFetcher,
        "select_best_image",
        fake_select_best_image,
    ):
        enriched = pipeline._scrape_candidate(candidate)

    assert enriched.url == "https://apnews.com/article/current-story"
    assert enriched.content.startswith("Reported article text")
    assert enriched.image_url == "https://assets.apnews.com/media/current-story/photo-1200.jpg"
    assert ("scrape", "https://apnews.com/article/current-story") in calls
    assert ("images", "https://apnews.com/article/current-story") in calls
    assert any(call[0] == "select" and call[2] == () for call in calls)
    assert enriched.score > 20


def test_scrape_candidate_keeps_google_news_candidate_when_decode_fails():
    def fail_decode(url):
        return None

    def fail_if_called(*args, **kwargs):
        raise AssertionError("scraping should not run without a direct publisher URL")

    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    candidate = ArticleCandidate(
        id="story-2",
        topic="TOP_NEWS",
        title="Another current story remains available from the feed",
        source="Reuters",
        url="https://news.google.com/articles/CBMiBroken",
        description="A concise feed description.",
        score=12,
    )

    with patch.object(ArticleFetcher, "extract_real_url_from_google", fail_decode), patch.object(
        ArticleFetcher,
        "scrape_article_content",
        fail_if_called,
    ), patch.object(ArticleFetcher, "find_article_images", fail_if_called):
        enriched = pipeline._scrape_candidate(candidate)

    assert enriched is candidate
    assert enriched.url == "https://news.google.com/articles/CBMiBroken"
    assert not enriched.content
    assert enriched.image_url is None


def test_enrichment_keeps_thin_high_signal_sports_candidates():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False, fetch_workers=1))
    sports_candidate = ArticleCandidate(
        id="sports-thin",
        topic="SPORTS",
        title="MLB players demand salary overhaul before labor talks",
        source="The Washington Post",
        url="https://www.washingtonpost.com/business/2026/05/27/mlb-labor-negotiations/example",
        description="",
    )
    thin_non_sports = ArticleCandidate(
        id="business-thin",
        topic="BUSINESS",
        title="Company shares move before the closing bell",
        source="MarketWatch",
        url="https://www.marketwatch.com/story/example",
        description="",
    )

    with patch.object(DailyBriefPipeline, "_scrape_candidate", lambda _self, candidate: candidate):
        enriched = pipeline._enrich_articles([sports_candidate, thin_non_sports])

    assert [candidate.id for candidate in enriched] == ["sports-thin"]


def test_fetch_espn_sports_news_normalizes_articles():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    class Response:
        def __init__(self, url: str):
            self.url = url

        def raise_for_status(self):
            return None

        def json(self):
            league_slug = self.url.rstrip("/").split("/")[-2]
            return {
                "articles": [
                    {
                        "headline": f"{league_slug.upper()} playoff race tightens before weekend games",
                        "description": "ESPN reports new roster and standings context for the league's playoff race.",
                        "published": "2026-05-28T10:30:00Z",
                        "links": {
                            "web": {
                                "href": f"https://www.espn.com/{league_slug}/story/_/id/12345/playoff-race"
                            }
                        },
                        "images": [{"url": "https://a.espncdn.com/photo/2026/0528/sports.jpg"}],
                        "source": {"name": "ESPN"},
                    }
                ]
            }

    def fake_get(url, params=None, timeout=None):
        assert params == {"limit": 5}
        assert timeout == 10
        return Response(url)

    with patch.object(pipeline.session, "get", fake_get):
        articles = pipeline._fetch_espn_sports_news()

    assert len(articles) >= 6
    assert all(article["source"] == "ESPN" for article in articles)
    assert all(article["url"].startswith("https://www.espn.com/") for article in articles)
    assert all(article["image_url"].startswith("https://a.espncdn.com/") for article in articles)


def test_diversification_keeps_high_signal_sports_in_source_packet():
    articles = [
        ArticleCandidate(
            id=f"top-{index}",
            topic="TOP_NEWS",
            title=f"Major national story {index}",
            source="Associated Press",
            url=f"https://apnews.com/article/top-{index}",
            description="A current top story with strong source support.",
            score=100 - index,
        )
        for index in range(4)
    ] + [
        ArticleCandidate(
            id=f"business-{index}",
            topic="BUSINESS",
            title=f"Market story {index}",
            source="CNBC",
            url=f"https://www.cnbc.com/story-{index}",
            description="A current market story with strong source support.",
            score=90 - index,
        )
        for index in range(4)
    ] + [
        ArticleCandidate(
            id="sports-1",
            topic="SPORTS",
            title="NBA playoff injury report reshapes the finals race",
            source="ESPN",
            url="https://www.espn.com/nba/story/_/id/sports-1/nba-playoff-injury-report",
            description="A late NBA injury update changed rotations before tonight's playoff game.",
            score=5,
        ),
        ArticleCandidate(
            id="sports-2",
            topic="SPORTS",
            title="MLB players demand salary overhaul before labor talks",
            source="The Washington Post",
            url="https://www.washingtonpost.com/business/2026/05/27/mlb-labor-negotiations/example",
            description="",
            score=4,
        ),
    ]

    selected = DailyBriefPipeline._diversify_articles(articles, limit=6)

    assert {"sports-1", "sports-2"}.issubset({article.id for article in selected})
    assert sum(1 for article in selected if article.topic == "TOP_NEWS") >= 2


def test_diversification_reserves_room_for_core_coverage_topics():
    articles: list[ArticleCandidate] = []
    for topic, count, base_score in [
        ("TOP_NEWS", 18, 100),
        ("BUSINESS", 3, 55),
        ("TECHNOLOGY", 3, 50),
        ("WORLD", 3, 45),
        ("HEALTH", 2, 40),
        ("SCIENCE", 2, 35),
        ("SPORTS", 2, 30),
    ]:
        for index in range(count):
            title = f"{topic.title()} coverage story {index}"
            if topic == "SPORTS":
                title = f"NBA playoff coverage story {index}"
            articles.append(
                ArticleCandidate(
                    id=f"{topic.lower()}-{index}",
                    topic=topic,
                    title=title,
                    source="Associated Press" if topic != "SPORTS" else "ESPN",
                    url=f"https://source-{topic.lower()}-{index}.example.com/story",
                    description="A current source-backed update with enough detail for the brief.",
                    score=base_score - index,
                )
            )

    selected = DailyBriefPipeline._diversify_articles(articles, limit=24)
    counts = {
        topic: sum(1 for article in selected if article.topic == topic)
        for topic in {article.topic for article in selected}
    }

    assert counts["TOP_NEWS"] >= 6
    assert counts["BUSINESS"] >= 3
    assert counts["TECHNOLOGY"] >= 3
    assert counts["WORLD"] >= 3
    assert counts["HEALTH"] >= 2
    assert counts["SCIENCE"] >= 2
    assert counts["SPORTS"] >= 2


def test_sports_story_filter_rejects_political_drift_without_word_substring_false_positive():
    assert not DailyBriefPipeline._is_high_signal_sports_candidate(
        title="Construction of cage-fighting arena transforms White House grounds",
        source="Reuters",
        url="https://www.reuters.com/world/us/example",
        description="The White House South Lawn is being converted into a UFC arena.",
    )

    assert DailyBriefPipeline._is_high_signal_sports_candidate(
        title="Sens. Cruz, Cantwell look to break college sports logjam with bipartisan bill",
        source="AP News",
        url="https://apnews.com/article/example",
        description="The bill proposes a national college sports framework for NIL and transfers.",
    )

    assert not DailyBriefPipeline._contains_any_term("white house", ("win",))
    assert not DailyBriefPipeline._is_high_signal_sports_candidate(
        title="Canada formally requests 16-year renewal of North American free trade pact",
        source="BBC News",
        url="https://www.bbc.com/news/articles/canada-usmca-renewal",
        description="A trade minister asked counterparts to renew the USMCA trade pact.",
    )


def test_sports_gate_accepts_athletic_paths_on_general_news_domains():
    assert DailyBriefPipeline._is_high_signal_sports_candidate(
        title="Inside the rivalry reshaping the league",
        source="The New York Times",
        url="https://www.nytimes.com/athletic/6500000/2026/05/28/example-story/",
        description="A reported feature from the conference finals.",
    )
