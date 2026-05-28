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
        "headline": "Useful daily brief",
        "dek": "Short useful context.",
        "summary": "A concise summary with enough substance for the daily brief quality gate.",
        "quick_hits": ["One current signal"],
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


def test_quality_gate_rejects_sports_scores_without_source_metadata():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    pipeline.sports_score_cards = [{"id": "nba-401871329", "league": "NBA"}]

    brief = {
        "model_used": "gemini-3-flash-preview-search-grounded",
        "headline": "Useful daily brief",
        "dek": "Short useful context.",
        "summary": "A concise summary with enough substance for the daily brief quality gate.",
        "quick_hits": ["One current signal"],
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

    assert "sports score nba-401871329 missing ESPN source metadata" in issues
    assert "sports score nba-401871329 missing verified_at" in issues


def test_quality_gate_accepts_direct_sources_with_multimedia_and_sports_relevance():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))

    issues = pipeline._brief_quality_issues(valid_quality_brief())

    assert issues == []


def test_quality_gate_rejects_google_wrappers_and_sparse_multimedia():
    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    brief = valid_quality_brief()
    brief["hero_image_url"] = None
    for story in brief["stories"]:
        story.pop("image_url", None)
    brief["stories"][0]["url"] = "https://news.google.com/articles/CBMiBad"

    issues = pipeline._brief_quality_issues(brief)

    assert "story story-1 still uses Google News wrapper URL" in issues
    assert "missing hero_image_url" in issues
    assert "leading stories need at least two image_url values" in issues


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
