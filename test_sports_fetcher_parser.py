"""Unit tests for the revamped SportsFetcher parsing helpers."""

from datetime import datetime, timedelta, timezone

from newsaggregator.fetchers.sports_fetcher import SportsFetcher
from newsaggregator.fetchers.espn_discovery import LeagueDescriptor

SAMPLE_EVENT = {
    "id": "401585786",
    "uid": "s:40~l:46~e:401585786",
    "date": "2024-04-10T23:00Z",
    "name": "Team A at Team B",
    "shortName": "TA @ TB",
    "season": {"year": 2024, "type": 2},
    "week": {"number": 27},
    "status": {
        "displayClock": "0.0",
        "type": {
            "id": "3",
            "state": "post",
            "description": "Final",
            "detail": "Final",
            "shortDetail": "Final",
            "completed": True,
        },
    },
    "headlines": [{"description": "League recap"}],
    "competitions": [
        {
            "id": "401585786",
            "attendance": 19432,
            "venue": {
                "id": "3417",
                "fullName": "Rocket Arena",
                "address": {"city": "Cleveland", "state": "OH"},
            },
            "broadcasts": [{"market": "home", "names": ["ESPN"]}],
            "geoBroadcasts": [
                {
                    "type": {"shortName": "TV"},
                    "market": {"type": "Home"},
                    "media": {"shortName": "ESPN"},
                }
            ],
            "leaders": [
                {
                    "name": "Points",
                    "leaders": [
                        {
                            "athlete": {"displayName": "Player One"},
                            "team": {"abbreviation": "TB"},
                            "value": 29,
                            "displayValue": "29 pts",
                        }
                    ],
                }
            ],
            "competitors": [
                {
                    "id": "5",
                    "uid": "s:40~l:46~t:5",
                    "homeAway": "home",
                    "winner": True,
                    "score": "110",
                    "records": [{"summary": "49-33", "type": "total"}],
                    "curatedRank": {"current": 2},
                    "linescores": [{"period": 1, "value": 30.0, "displayValue": "30"}],
                    "team": {
                        "displayName": "Team B",
                        "location": "City B",
                        "abbreviation": "TB",
                        "logo": "https://example.com/tb.png",
                    },
                },
                {
                    "id": "1",
                    "uid": "s:40~l:46~t:1",
                    "homeAway": "away",
                    "winner": False,
                    "score": "98",
                    "records": [{"summary": "51-31", "type": "total"}],
                    "team": {
                        "displayName": "Team A",
                        "location": "City A",
                        "abbreviation": "TA",
                        "logo": "https://example.com/ta.png",
                    },
                },
            ],
        }
    ],
}


def test_parse_event_extracts_rich_metadata():
    """The parser should normalise key metadata for downstream storage."""

    fetcher = SportsFetcher.__new__(SportsFetcher)
    fetcher.scoreboard_enables = ''

    descriptor = LeagueDescriptor(
        sport_slug="basketball",
        league_slug="nba",
        display_name="NBA",
        abbreviation="NBA",
        code="nba",
        api_ref="",
        scoreboard_path="basketball/nba",
        scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    )

    game = fetcher._parse_event(descriptor, SAMPLE_EVENT)
    assert game['league']['code'] == 'nba'
    assert game['home_team']['abbreviation'] == 'TB'
    assert game['attendance'] == 19432
    assert game['leaders']['Points'][0]['value'] == 29
    assert game['status'] == 'Final'
    assert game['formatted_date'] == '2024-04-10'


def test_select_high_signal_news_articles_filters_stale_low_signal_items():
    now = datetime.now(timezone.utc)
    articles = [
        {
            "headline": "NBA betting odds and parlay picks for tonight",
            "description": "A betting rail with no confirmed basketball development.",
            "link": "https://espn.com/nba/betting",
            "published": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "headline": "Star guard signs four-year contract extension before Finals",
            "description": "The confirmed deal changes the team's roster outlook.",
            "link": "https://espn.com/nba/contract-extension",
            "published": (now - timedelta(hours=3)).isoformat(),
            "images": [{"url": "https://example.com/photo.jpg"}],
            "source": "ESPN",
        },
        {
            "headline": "Power rankings after the latest playoff games",
            "description": "A ranking roundup with limited new reporting.",
            "link": "https://espn.com/nba/power-rankings",
            "published": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "headline": "Veteran coach fired after playoff exit",
            "description": "The franchise confirmed the coaching change today.",
            "link": "https://espn.com/nba/coach-fired",
            "published": (now - timedelta(hours=4)).isoformat(),
            "source": "ESPN",
        },
        {
            "headline": "Coach fired after playoff exit reaction",
            "description": "A video clip covering the same coaching change.",
            "link": "https://www.espn.com/video/clip/_/id/99999999/coach-fired-reaction",
            "published": (now - timedelta(hours=1)).isoformat(),
            "source": "ESPN",
        },
        {
            "headline": "Old trade deadline tracker",
            "description": "This item is too old for a current sports rail.",
            "link": "https://espn.com/nba/old-tracker",
            "published": (now - timedelta(days=5)).isoformat(),
        },
    ]

    selected = SportsFetcher._select_high_signal_news_articles(articles, limit=2)
    selected_headlines = [article["headline"] for article in selected]

    assert selected_headlines == [
        "Star guard signs four-year contract extension before Finals",
        "Veteran coach fired after playoff exit",
    ]


def test_select_high_signal_news_articles_suppresses_near_duplicate_variants():
    now = datetime.now(timezone.utc)
    articles = [
        {
            "headline": "Browns' Monken says drafting Sorsby is a slippery slope",
            "description": "The coach addressed the quarterback's draft outlook.",
            "link": "https://espn.com/college-football/story/_/id/111/browns-monken-sorsby",
            "published": (now - timedelta(hours=2)).isoformat(),
            "source": "ESPN",
        },
        {
            "headline": "'Slippery slope' to draft embattled QB Sorsby, says Browns' Monken",
            "description": "The same quarterback story appears with a variant headline.",
            "link": "https://espn.com/college-football/story/_/id/222/slippery-slope-sorsby",
            "published": (now - timedelta(hours=1)).isoformat(),
            "source": "ESPN",
        },
        {
            "headline": "Texas A&M adds linebacker to top recruiting class",
            "description": "The commitment changes the program's 2027 defensive class.",
            "link": "https://espn.com/college-football/story/_/id/333/texas-am-recruiting",
            "published": (now - timedelta(hours=3)).isoformat(),
            "source": "ESPN",
        },
    ]

    selected = SportsFetcher._select_high_signal_news_articles(articles, limit=3)

    assert len(selected) == 2
    assert sum("Sorsby" in article["headline"] for article in selected) == 1
    assert selected[-1]["headline"] == "Texas A&M adds linebacker to top recruiting class"


def test_select_high_signal_news_articles_keeps_fresh_fallback_when_feed_is_generic():
    now = datetime.now(timezone.utc)
    articles = [
        {
            "headline": "MLS weekend schedule and viewing guide",
            "description": "A fresh schedule item from ESPN's league feed.",
            "link": "https://espn.com/mls/schedule-guide",
            "published": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "headline": "MLS weekend schedule and viewing guide",
            "description": "Duplicate item should be collapsed.",
            "link": "https://espn.com/mls/schedule-guide?duplicate=1",
            "published": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "headline": "MLS betting odds and picks for this weekend",
            "description": "Fresh betting filler should not be used as a fallback.",
            "link": "https://espn.com/mls/betting-odds",
            "published": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "headline": "Old MLS betting picks",
            "description": "Too old to fall back to.",
            "link": "https://espn.com/mls/old-picks",
            "published": (now - timedelta(days=5)).isoformat(),
        },
    ]

    selected = SportsFetcher._select_high_signal_news_articles(articles, limit=3)

    assert [article["headline"] for article in selected] == [
        "MLS weekend schedule and viewing guide"
    ]
