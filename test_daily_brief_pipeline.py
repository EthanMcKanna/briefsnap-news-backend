"""Focused tests for the daily brief contract consumed by the iOS app."""

from datetime import datetime, timezone
from unittest.mock import patch

from newsaggregator.briefs.pipeline import ArticleCandidate, DailyBriefPipeline, PipelineOptions
from newsaggregator.fetchers.article_fetcher import ArticleFetcher


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


def test_quality_gate_rejects_unsupported_top_level_named_entities():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["summary"] = (
        "President Biden sued to block audio releases while the displayed story list "
        "covers only unrelated policy, markets, technology, world, and sports stories."
    )

    issues = pipeline._brief_quality_issues(brief)

    assert "top-level brief copy includes unsupported named entities" in issues


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
    assert score["expires_at"] == "2026-05-12T12:30:00+00:00"
    assert datetime.fromisoformat(score["expires_at"]) > datetime.fromisoformat(score["event_date"])


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


def test_image_url_filter_accepts_validated_cdn_image_shapes():
    assert ArticleFetcher._is_valid_image_url(
        "https://images.example.com/media/story/abc123?w=1200&format=webp"
    )
    assert ArticleFetcher._is_valid_image_url(
        "https://images.ctfassets.net/site/asset-id/briefsnap-news-image"
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


def test_sports_gate_accepts_athletic_paths_on_general_news_domains():
    assert DailyBriefPipeline._is_high_signal_sports_candidate(
        title="Inside the rivalry reshaping the league",
        source="The New York Times",
        url="https://www.nytimes.com/athletic/6500000/2026/05/28/example-story/",
        description="A reported feature from the conference finals.",
    )
