"""Unit tests for the revamped SportsFetcher parsing helpers."""

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
