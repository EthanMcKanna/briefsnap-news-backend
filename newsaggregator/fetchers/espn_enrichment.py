"""Advanced enrichment helpers for ESPN scoreboard events."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from newsaggregator.config.settings import SPORTS_ENRICHMENT

from .espn_client import ESPNHTTPClient

SUMMARY_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"
TEAM_BASE = "https://site.api.espn.com/apis/site/v2/sports"


class EspnEventEnricher:
    """Fetches summary, play-by-play, win probability, and team context."""

    def __init__(self, client: Optional[ESPNHTTPClient] = None) -> None:
        self.client = client or ESPNHTTPClient()
        self.config = SPORTS_ENRICHMENT
        self.team_cache: Dict[str, Dict] = {}

    def enrich_games(
        self,
        games_by_league: Dict[str, List[Dict]],
        league_lookup: Dict[str, Any],
    ) -> None:
        if not self.config.get('enabled'):
            return

        targets: List[Tuple[Any, Dict]] = []
        for league_code, games in games_by_league.items():
            descriptor = league_lookup.get(league_code)
            if not descriptor:
                continue
            for game in games:
                if self._should_enrich(game):
                    targets.append((descriptor, game))

        if not targets:
            return

        workers = min(max(self.config.get('max_workers', 2), 1), len(targets))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._enrich_single, descriptor, game): (
                    self._descriptor_attr(descriptor, 'code'),
                    game.get('id'),
                )
                for descriptor, game in targets
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:  # pragma: no cover - defensive logging upstream
                    league_code, game_id = futures[future]
                    print(f"Failed to enrich {league_code} event {game_id}: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _enrich_single(self, descriptor: Any, game: Dict) -> None:
        summary = self._fetch_summary(descriptor, game.get('id'))
        if summary:
            game['live_feed'] = self._build_live_feed(summary)
            game['odds_history'] = self._collect_odds(summary)

        self._attach_team_details(descriptor, game)

    def _should_enrich(self, game: Dict) -> bool:
        timestamp = self._extract_timestamp(game)
        if not timestamp:
            return False

        now = datetime.now(timezone.utc).timestamp()
        pre_window = self.config.get('pre_event_window_hours', 72) * 3600
        post_window = self.config.get('post_event_window_hours', 12) * 3600

        status_text = (game.get('status') or '').lower()
        if any(keyword in status_text for keyword in ['live', 'progress', 'quarter', 'period', 'half', 'inning']):
            return True

        if timestamp >= now and (timestamp - now) <= pre_window:
            return True

        if timestamp < now and (now - timestamp) <= post_window:
            return True

        return False

    def _extract_timestamp(self, game: Dict) -> Optional[float]:
        ts = game.get('timestamp')
        if ts:
            return float(ts)

        date_str = game.get('date')
        if not date_str:
            return None

        try:
            if date_str.endswith('Z'):
                date_str = date_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(date_str)
            return dt.timestamp()
        except ValueError:
            return None

    def _fetch_summary(self, descriptor: Any, event_id: Optional[str]) -> Optional[Dict]:
        if not event_id:
            return None

        url = f"{SUMMARY_BASE}/{self._descriptor_attr(descriptor, 'scoreboard_path')}/summary"
        try:
            return self.client.get_json(url, params={'event': event_id})
        except Exception:
            return None

    def _build_live_feed(self, summary: Dict) -> Dict:
        return {
            'win_probability': self._extract_win_probability(summary),
            'recent_drives': self._collect_recent_drives(summary),
            'recent_plays': self._collect_recent_plays(summary),
        }

    def _extract_win_probability(self, summary: Dict) -> Optional[Dict]:
        entries = summary.get('winprobability') or []
        if not entries:
            return None
        latest = entries[-1]
        return {
            'home': latest.get('homeWinPercentage'),
            'away': latest.get('awayWinPercentage'),
            'tie': latest.get('tiePercentage'),
            'playId': latest.get('playId'),
        }

    def _collect_recent_drives(self, summary: Dict) -> List[Dict]:
        drives = summary.get('drives', {})
        previous = drives.get('previous') or []
        recent = previous[-self.config.get('max_recent_drives', 2):]

        formatted = []
        for drive in recent:
            formatted.append({
                'team': (drive.get('team') or {}).get('displayName'),
                'result': drive.get('result'),
                'yards': drive.get('yards'),
                'plays': drive.get('playsCount'),
                'duration': drive.get('duration'),
            })
        return formatted

    def _collect_recent_plays(self, summary: Dict) -> List[Dict]:
        drives = summary.get('drives', {})
        plays: List[Dict] = []
        for bucket in ('current', 'previous'):
            for drive in drives.get(bucket) or []:
                for play in drive.get('plays') or []:
                    plays.append({
                        'text': play.get('text'),
                        'clock': (play.get('clock') or {}).get('displayValue'),
                        'type': (play.get('type') or {}).get('text'),
                        'team': (play.get('team') or {}).get('abbreviation'),
                        'sequence': play.get('sequenceNumber'),
                    })

        plays = sorted(plays, key=lambda item: item.get('sequence') or 0)
        max_items = self.config.get('max_recent_plays', 6)
        return plays[-max_items:]

    def _collect_odds(self, summary: Dict) -> List[Dict]:
        odds_entries = summary.get('pickcenter') or summary.get('odds') or []
        snapshots = odds_entries[: self.config.get('max_odds_snapshots', 3)]
        formatted = []
        for entry in snapshots:
            formatted.append({
                'provider': (entry.get('provider') or {}).get('name'),
                'spread': entry.get('spread'),
                'formatted_spread': entry.get('details'),
                'over_under': entry.get('overUnder'),
                'away_odds': (entry.get('awayTeamOdds') or {}).get('moneyLine'),
                'home_odds': (entry.get('homeTeamOdds') or {}).get('moneyLine'),
                'last_update': entry.get('lastUpdated'),
            })
        return formatted

    def _attach_team_details(self, descriptor: Any, game: Dict) -> None:
        for side in ('home_team', 'away_team'):
            team = game.get(side)
            if not team or not team.get('id'):
                continue
            detail = self._fetch_team_details(descriptor, team['id'])
            if detail:
                team['extended_context'] = detail

    def _fetch_team_details(self, descriptor: Any, team_id: str) -> Optional[Dict]:
        cache_key = f"{self._descriptor_attr(descriptor, 'scoreboard_path')}::{team_id}"
        if cache_key in self.team_cache:
            return self.team_cache[cache_key]

        params = {'enable': self.config.get('team_enable_params')}
        url = f"{TEAM_BASE}/{self._descriptor_attr(descriptor, 'scoreboard_path')}/teams/{team_id}"
        try:
            payload = self.client.get_json(url, params=params)
        except Exception:
            return None

        team_payload = payload.get('team') or {}
        detail = self._format_team_payload(team_payload)
        self.team_cache[cache_key] = detail
        return detail

    def _format_team_payload(self, team_payload: Dict) -> Dict:
        record_items = []
        for item in (team_payload.get('record') or {}).get('items') or []:
            record_items.append({
                'label': item.get('description'),
                'summary': item.get('summary'),
            })

        next_event = None
        if team_payload.get('nextEvent'):
            evt = team_payload['nextEvent'][0]
            competitions = evt.get('competitions') or [{}]
            venue = (competitions[0].get('venue') or {}).get('fullName') if competitions else None
            next_event = {
                'text': evt.get('text') or evt.get('shortName'),
                'date': evt.get('date'),
                'location': venue,
            }

        return {
            'record_splits': record_items[:3],
            'standing_summary': team_payload.get('standingSummary'),
            'next_event': next_event,
            'notable_players': self._extract_notable_players(team_payload),
        }

    def _extract_notable_players(self, team_payload: Dict) -> List[Dict]:
        athletes = team_payload.get('athletes') or []
        starters = [athlete for athlete in athletes if athlete.get('starter')]
        pool = starters or athletes

        notable = []
        for athlete in pool[:5]:
            injury = None
            injuries = athlete.get('injuries') or []
            if injuries:
                injury = injuries[0].get('shortStatus') or injuries[0].get('status')

            notable.append({
                'name': athlete.get('displayName') or athlete.get('fullName'),
                'position': (athlete.get('position') or {}).get('abbreviation'),
                'jersey': athlete.get('jersey'),
                'status': injury,
            })

        return notable

    def _descriptor_attr(self, descriptor: Any, attr: str) -> Any:
        if hasattr(descriptor, attr):
            return getattr(descriptor, attr)
        if isinstance(descriptor, dict):
            return descriptor.get(attr)
        return None
