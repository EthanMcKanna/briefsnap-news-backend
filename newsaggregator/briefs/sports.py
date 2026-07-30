"""ESPN sports score packet for the daily brief.

Ported from the V8 pipeline: this subsystem worked well and the iOS app's
sports desk depends on this exact card shape.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

SPORT_SCORE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("NFL", "football/nfl"),
    ("NCAAF", "football/college-football"),
    ("NBA", "basketball/nba"),
    ("WNBA", "basketball/wnba"),
    ("NCAAB", "basketball/mens-college-basketball"),
    ("MLB", "baseball/mlb"),
    ("NHL", "hockey/nhl"),
    ("MLS", "soccer/usa.1"),
)

SPORT_SCORE_LEAGUE_PRIORITY = {
    "NBA": 0,
    "NHL": 1,
    "WNBA": 2,
    "MLB": 3,
    "MLS": 4,
    "NFL": 5,
    "NCAAF": 6,
    "NCAAB": 7,
}

POSTGAME_SCORE_TTL = timedelta(hours=6)


def fetch_top_sports_scores(session: requests.Session) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc)
    verified_at = today.isoformat()
    dates = [
        (today - timedelta(days=1)).strftime("%Y%m%d"),
        today.strftime("%Y%m%d"),
    ]
    games: list[dict[str, Any]] = []

    for league, path in SPORT_SCORE_ENDPOINTS:
        for date in dates:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
            try:
                response = session.get(url, params={"dates": date, "limit": 80}, timeout=10)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                print(f"[WARN] ESPN scoreboard fetch failed for {league} {date}: {exc}")
                continue

            for event in payload.get("events", []) or []:
                parsed = parse_score_event(
                    league=league,
                    event=event,
                    source_url=str(response.url),
                    verified_at=verified_at,
                )
                if parsed and score_card_is_displayable(parsed, today):
                    games.append(parsed)

    deduped: dict[str, dict[str, Any]] = {}
    for game in games:
        deduped[game["id"]] = game

    sorted_games = sorted(deduped.values(), key=score_card_sort_key)
    selected: list[dict[str, Any]] = []
    league_counts: dict[str, int] = {}
    for game in sorted_games:
        league = str(game.get("league") or "")
        if league_counts.get(league, 0) >= 2:
            continue
        selected.append(game)
        league_counts[league] = league_counts.get(league, 0) + 1
        if len(selected) == 6:
            return selected

    seen_ids = {game.get("id") for game in selected}
    for game in sorted_games:
        if game.get("id") in seen_ids:
            continue
        selected.append(game)
        if len(selected) == 6:
            break
    return selected


def parse_score_event(
    league: str,
    event: dict[str, Any],
    source_url: str = "",
    verified_at: str = "",
) -> dict[str, Any] | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None

    status = (event.get("status") or {}).get("type") or {}
    state = status.get("state") or ""
    completed = bool(status.get("completed"))
    detail = status.get("shortDetail") or status.get("detail") or status.get("description") or "Scheduled"
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    venue_data = competition.get("venue") or {}
    broadcasts = competition.get("broadcasts") or []

    home = next((item for item in competitors if item.get("homeAway") == "home"), None)
    away = next((item for item in competitors if item.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    def team(item: dict[str, Any]) -> dict[str, Any]:
        team_data = item.get("team") or {}
        raw_score = item.get("score")
        score = int(raw_score) if state != "pre" and str(raw_score).isdigit() else None
        records = item.get("records") or []
        record = ""
        for record_item in records:
            record = record_item.get("summary") or record
            if record:
                break
        curated_rank = item.get("curatedRank") or {}
        rank = curated_rank.get("current") or item.get("rank")
        try:
            if rank and int(rank) > 99:
                rank = None
        except (TypeError, ValueError):
            rank = None
        return {
            "name": team_data.get("displayName") or team_data.get("name") or "",
            "abbreviation": team_data.get("abbreviation") or "",
            "short_name": team_data.get("shortDisplayName") or team_data.get("shortName") or "",
            "score": score,
            "winner": item.get("winner"),
            "record": record,
            "rank": rank,
            "logo": team_data.get("logo"),
        }

    home_team = team(home)
    away_team = team(away)
    has_score = home_team["score"] is not None and away_team["score"] is not None

    if has_score:
        display = (
            f"{away_team['abbreviation'] or away_team['name']} {away_team['score']} at "
            f"{home_team['abbreviation'] or home_team['name']} {home_team['score']}"
        )
    else:
        display = f"{away_team['name']} at {home_team['name']}"

    if detail:
        display = f"{display} ({detail})"

    winner = home_team if home_team["winner"] else away_team if away_team["winner"] else None
    if has_score and winner:
        loser = away_team if winner is home_team else home_team
        margin = abs(int(home_team["score"]) - int(away_team["score"]))
        result_note = f"{winner['abbreviation'] or winner['short_name'] or winner['name']} by {margin}"
        if margin == 0:
            result_note = "Tied"
        if completed or state == "post":
            context_line = (
                f"{winner['abbreviation'] or winner['short_name'] or winner['name']} beat "
                f"{loser['abbreviation'] or loser['short_name'] or loser['name']} by {margin}"
            )
        else:
            context_line = f"{winner['abbreviation'] or winner['short_name'] or winner['name']} leads by {margin}"
    elif has_score and home_team["score"] == away_team["score"]:
        result_note = "Tied"
        context_line = f"{away_team['abbreviation']} and {home_team['abbreviation']} tied"
    else:
        result_note = detail
        context_line = display

    venue = venue_data.get("fullName") or ""
    venue_city = (venue_data.get("address") or {}).get("city") or ""
    venue_state = (venue_data.get("address") or {}).get("state") or ""
    venue_location = ", ".join(part for part in (venue_city, venue_state) if part)
    broadcast = ""
    if broadcasts:
        names = [
            name
            for broadcast_item in broadcasts[:2]
            for name in ((broadcast_item.get("names") or [])[:1])
            if name
        ]
        broadcast = ", ".join(names)

    timestamp = None
    event_date = None
    if event.get("date"):
        try:
            event_date = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
            timestamp = event_date.timestamp()
        except ValueError:
            timestamp = None

    rank = 0 if state == "in" else 1 if state == "pre" else 2
    verified_dt = None
    if verified_at:
        try:
            verified_dt = datetime.fromisoformat(verified_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            verified_dt = None
    if state == "in" and verified_dt:
        expires_at = (verified_dt + timedelta(minutes=15)).isoformat()
    elif (completed or state == "post") and event_date:
        expires_at = (event_date + POSTGAME_SCORE_TTL).isoformat()
    elif event_date:
        expires_at = (event_date + timedelta(minutes=30)).isoformat()
    else:
        expires_at = None
    raw_event_id = event.get("id") or hashlib.sha1(
        f"{league}:{event.get('name')}:{event.get('date')}".encode("utf-8")
    ).hexdigest()[:12]

    return {
        "id": f"{league.lower()}-{raw_event_id}",
        "league": league,
        "source": "ESPN",
        "source_url": source_url,
        "verified_at": verified_at,
        "event_date": event_date.isoformat() if event_date else event.get("date"),
        "expires_at": expires_at,
        "event_id": str(raw_event_id),
        "name": event.get("name") or f"{away_team['name']} at {home_team['name']}",
        "status": detail,
        "state": state,
        "is_live": state == "in",
        "is_final": completed or state == "post",
        "home_team": home_team,
        "away_team": away_team,
        "display": display,
        "context_line": context_line,
        "result_note": result_note,
        "venue": venue,
        "venue_location": venue_location,
        "broadcast": broadcast,
        "timestamp": timestamp,
        "rank": rank,
    }


def score_card_is_displayable(score: dict[str, Any], now: datetime | None = None) -> bool:
    if not isinstance(score, dict):
        return False

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires_at = score.get("expires_at")
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            return expires_dt.astimezone(timezone.utc) > now
        except ValueError:
            return False

    return bool(score.get("is_live") or score.get("is_final"))


def score_card_sort_key(score: dict[str, Any]) -> tuple[int, int, float]:
    timestamp = score.get("timestamp") or 0
    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError):
        timestamp_value = 0

    league = str(score.get("league") or "").upper()
    league_priority = SPORT_SCORE_LEAGUE_PRIORITY.get(league, 99)
    state = str(score.get("state") or "").lower()
    if score.get("is_live") or state == "in":
        return (0, league_priority, -timestamp_value)
    if state == "pre":
        return (1, league_priority, timestamp_value)
    return (2, league_priority, -timestamp_value)


def sports_scores_metadata(score_cards: list[dict[str, Any]]) -> dict[str, Any]:
    if not score_cards:
        return {}

    verified_times: list[datetime] = []
    for score in score_cards:
        if not isinstance(score, dict):
            continue
        verified_at = str(score.get("verified_at") or "").strip()
        if not verified_at:
            continue
        try:
            verified_times.append(
                datetime.fromisoformat(verified_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            )
        except ValueError:
            continue

    refreshed_at = max(verified_times) if verified_times else datetime.now(timezone.utc)
    return {
        "sports_scores_refreshed_at": refreshed_at.isoformat(),
        "sports_scores_verified_at": refreshed_at.isoformat(),
        "sports_scores_source": "ESPN",
    }


def archive_stale_firestore_scores() -> int:
    try:
        from newsaggregator.storage.sports_storage import SportsStorage

        archived = SportsStorage.archive_stale_final_scores()
    except Exception as exc:
        print(f"[WARN] Stale final score cleanup skipped: {exc}")
        return 0

    if archived:
        print(f"Archived {archived} stale Firestore final score(s)")
    return archived
