# Sports Data Reference

Comprehensive guide to the revamped ESPN sports scraper so downstream jobs (Firebase, Gemini, mobile clients) can reason about the stored structures quickly.

## 1. Pipeline Overview

1. **Directory discovery** (`newsaggregator/fetchers/espn_discovery.py`)
   - Pulls `https://sports.core.api.espn.com/v2/sports` every 12h (configurable) and caches `data/sports_discovery/leagues.json`.
   - Discovers every league under the whitelisted sports (default: football, basketball, baseball, hockey, soccer).
   - Provides metadata (`sport_slug`, `league_slug`, `code`, `season_year`, scoreboard URL) that drives the scheduler.
2. **Scoreboard ingestion** (`SportsFetcher.fetch_all_sports`)
   - Iterates dates + leagues with worker pool (`MAX_SPORT_FETCH_WORKERS`).
   - Calls `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=YYYYMMDD&enable=linescores,leaders,...`.
   - Normalises every event into a single schema (see section 2).
3. **Event enrichment** (`EspnEventEnricher`)
   - Pulls `summary`, `plays`, `drives`, `winprobability`, `pickcenter` + team detail endpoints for games within ±72h.
   - Attaches `live_feed`, `odds_history`, and per-team `extended_context` payloads.
4. **League news ingestion**
   - Drops `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/news?limit=n` into the run summary under `news_feeds`.
5. **Storage layer** remains unchanged (Firestore collections `sports_games`, `sports_summaries`, etc.) but now receives richer documents plus the discovery/news snapshot embedded in each summary.

## 2. Game Document Schema (Firestore `sports_games`)

| Field | Type | Description |
| --- | --- | --- |
| `id` | str | ESPN event ID. Same as scoreboard/summary endpoints.
| `sport_code` | str | Stable lowercase code for the league (e.g., `nba`, `ncaaf`, `mls`).
| `sport` | str | Display name (e.g., `NBA`, `College Football`).
| `league` | object | `{code, name, sport_slug, league_slug, season_year}` from discovery.
| `name` / `short_name` | str | ESPN friendly labels ("MEM @ CLE").
| `date` | ISO str | Kick/first pitch in UTC.
| `formatted_date` / `formatted_time` | str | Pre-formatted helpers for UI.
| `timestamp` | float | Epoch seconds derived from `date`.
| `season` | object | Raw ESPN season payload (type + year).
| `week` | int | Week number when provided (NFL, CFB, etc.).
| `status` / `status_id` / `status_state` / `status_short` | str | ESPN status metadata.
| `is_live` / `is_final` | bool | Quick toggles derived from `status.type`.
| `time_remaining` | str | `displayClock` style representation.
| `venue` | object | `{id, name, city, state, indoor}`.
| `attendance` | int | Reported attendance (if available).
| `broadcasts` | list | Each entry: `{market, names[], type}`.
| `geo_broadcasts` | list | If ESPN exposes regional feeds.
| `links` | list | Canonical gamecast/boxscore/pbp links.
| `tickets` | list | Future ticket info if ESPN provides it.
| `notes` / `headlines` | list | Recap + preview blurbs.
| `odds` | list | Raw book snapshots from the scoreboard payload.
| `predictor` | object | ESPN predictor payload (probabilities, team IDs, etc.).
| `situation` | object | Live context (last play text, ball position, etc. when available).
| `home_team` / `away_team` | object | See below.
| `leaders` | dict | Keyed by stat label ("Points", "Passing Yards") with `{athlete, team, value, displayValue}` entries.
| `live_feed` | object | (Enriched) contains `win_probability`, `recent_drives`, `recent_plays`.
| `odds_history` | list | (Enriched) provider snapshots with spread, OU, and moneyline.

### Team Blocks (`home_team`, `away_team`)

```
{
  "id": "5",
  "name": "Cleveland Cavaliers",
  "location": "Cleveland",
  "abbreviation": "CLE",
  "logo": "https://.../cle.png",
  "homeAway": "home",
  "winner": true,
  "score": 110,
  "record": [ { "type": "total", "summary": "49-33" } ],
  "rank": 2,
  "linescores": [ { "period": 1, "value": 32, "display": "32" }, ... ],
  "extended_context": {
    "record_splits": [ { "label": "Overall Record", "summary": "8-4" }, ... ],
    "standing_summary": "2nd in East",
    "next_event": { "text": "vs. BOS", "date": "2025-01-04T00:00Z", "location": "Rocket Arena" },
    "notable_players": [ { "name": "Donovan Mitchell", "position": "G", "jersey": "45", "status": null }, ... ]
  }
}
```

## 3. Live Feed / Advanced Metrics

- **`live_feed.win_probability`**: `{home, away, tie, playId}` representing the latest entry from ESPN's `winprobability` array.
- **`live_feed.recent_drives`**: Up to `SPORTS_ENRICHMENT['max_recent_drives']` entries (default 2) summarising `{team, result, yards, plays, duration}`.
- **`live_feed.recent_plays`**: Chronological slice of the last N play-by-play lines across the current and previous drives, including clock text and team abbreviations.
- **`odds_history`**: Clean snapshot of `pickcenter` data (provider name, spread, formatted spread text, OU, both moneylines, last update).

These fields are only attached for games within ±`pre_event_window_hours` (default 72) or those currently live.

## 4. League News Data (stored in `sports_summaries[*].news_feeds`)

Structure:

```
"news_feeds": {
  "nba": [
     {
        "headline": "Stafford looks to continue ...",
        "description": "Preview blurb",
        "link": "https://www.espn.com/...",
        "published": "2025-11-13T14:00Z",
        "images": [... optional ESPN image payload ...],
        "source": "ESPN.com"
     }, ... up to limit ...
  ],
  "nfl": [...]
}
```

Use this when composing Gemini prompts or populating in-app ticker cards without issuing another ESPN request.

## 5. Discovery Snapshot (also embedded in `sports_summaries`)

```
"discovery": {
  "generated_at": "2025-11-13T20:12:01.234567",
  "league_count": 26,
  "leagues": [
    { "code": "nfl", "name": "National Football League", "sport": "football", "league": "nfl" },
    { "code": "ncaaf", "name": "College Football", "sport": "football", "league": "college-football" },
    ...
  ]
}
```

Combined with `data/sports_discovery/leagues.json`, this lets schedulers answer "what leagues are we covering right now?" without recomputing.

## 6. Query Recipes

- **Upcoming scoreboard ticker:** query `sports_games` where `sport_code == 'nba'` AND `timestamp > now` sorted by `timestamp`. Display `home_team`, `away_team`, `formatted_time`, `broadcasts[0].names`.
- **Live game rail:** fetch from Firestore where `is_live == true` (or use `SportsStorage.get_live_games`). Use `live_feed.recent_plays` for quick updates.
- **Team-centric view:** filter by `home_team.id`/`away_team.id` or use `SportsStorage.get_games_by_team`. Surface `extended_context.record_splits` and `notable_players` for pre-game modules.
- **League insights:** read the latest `sports_summaries` doc; `by_sport[*].count` tells you how many games were ingested per league, `next_24_hours` enumerates the hottest ones, and `news_feeds` contains ready-to-display headlines.

## 7. Configuration Knobs

| Setting | Location | Purpose |
| --- | --- | --- |
| `SPORTS_DISCOVERY_*` | `newsaggregator/config/settings.py` | Controls auto-discovery sports list, cache TTL, and blacklisted leagues. |
| `SPORTS_SCOREBOARD_ENABLES` | same | Comma-separated modules appended to every scoreboard call (leaders, linescores, etc.). |
| `SPORTS_ENRICHMENT_*` | same | Windows + limits for summary/plays/odds enrichment, plus team enable params.
| `SPORTS_LEAGUE_NEWS_*` | same | Toggles and per-league article limit.

Tune these if you want more leagues (e.g., rugby) or deeper enrichment windows.

## 8. Files to Know

- `data/sports_discovery/leagues.json` – cached tree of every discovered league.
- `newsaggregator/fetchers/espn_client.py` – centralised retrying HTTP client.
- `newsaggregator/fetchers/espn_discovery.py` – discovery + cache logic.
- `newsaggregator/fetchers/espn_enrichment.py` – play-by-play, win-probability, team detail enrichment.
- `newsaggregator/fetchers/sports_fetcher.py` – orchestrator consumed by `main_sports.py`.

With these pieces the scraper now auto-discovers new ESPN leagues, captures deeper live context, and ships league-specific news along with every run, so anything consuming Firestore has enough structure to pivot without additional API calls.
