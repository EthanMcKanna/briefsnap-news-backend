"""Revamped ESPN sports fetcher with auto-discovery and enrichment."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from newsaggregator.config.settings import (
    MAX_SPORT_FETCH_WORKERS,
    SPORTS_NEWS_SETTINGS,
    SPORTS_SCOREBOARD_ENABLES,
)

from .espn_client import ESPNHTTPClient
from .espn_discovery import EspnLeagueDiscovery, LeagueDescriptor
from .espn_enrichment import EspnEventEnricher

FALLBACK_LEAGUES = {
    'nfl': ('football', 'nfl', 'National Football League', 'NFL'),
    'nba': ('basketball', 'nba', 'National Basketball Association', 'NBA'),
    'mlb': ('baseball', 'mlb', 'Major League Baseball', 'MLB'),
    'nhl': ('hockey', 'nhl', 'National Hockey League', 'NHL'),
    'ncaaf': ('football', 'college-football', 'College Football', 'NCAAF'),
    'ncaab': ('basketball', 'mens-college-basketball', "Men's College Basketball", 'NCAAB'),
    'mls': ('soccer', 'usa.1', 'Major League Soccer', 'MLS'),
}
APP_NEWS_LEAGUE_CODES = ('nfl', 'nba', 'mlb', 'nhl', 'ncaaf', 'ncaab', 'mls')

SCOREBOARD_TEMPLATE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
NEWS_TEMPLATE = "https://site.api.espn.com/apis/site/v2/sports/{path}/news"


class SportsFetcher:
    """High-level orchestrator for ESPN scoreboard scraping."""

    def __init__(self, client: Optional[ESPNHTTPClient] = None) -> None:
        self.client = client or ESPNHTTPClient()
        self.discovery = EspnLeagueDiscovery(self.client)
        self.leagues: List[LeagueDescriptor] = []
        self.league_lookup: Dict[str, LeagueDescriptor] = {}
        self.enricher = EspnEventEnricher(self.client)
        self.scoreboard_enables = ','.join(filter(None, SPORTS_SCOREBOARD_ENABLES))
        self.latest_league_news: Dict[str, List[Dict]] = {}
        self.discovery_snapshot: Optional[str] = None
        self.refresh_leagues()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def refresh_leagues(self, force_refresh: bool = False) -> None:
        """Refresh the discovery cache with optional force."""
        leagues = self.discovery.get_leagues(force_refresh=force_refresh)
        if not leagues:
            leagues = self._fallback_leagues()
        self.leagues = leagues
        self.league_lookup = {league.code: league for league in self.leagues}
        self.discovery_snapshot = datetime.utcnow().isoformat()

    def fetch_all_sports(
        self,
        *,
        days_ahead: int = 7,
        league_codes: Optional[Sequence[str]] = None,
    ) -> Dict[str, List[Dict]]:
        """Fetch scoreboard data for every discovered league."""
        leagues = self._select_leagues(league_codes)
        if not leagues:
            return {}

        dates = self._build_date_list(days_ahead)
        jobs = [(league, date) for league in leagues for date in dates]
        worker_count = min(max(MAX_SPORT_FETCH_WORKERS, 1), len(jobs)) or 1

        aggregated: Dict[str, Dict[str, Dict]] = defaultdict(dict)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._fetch_league_for_date, league, date): (league.code, date)
                for league, date in jobs
            }
            for future in as_completed(futures):
                league_code, date = futures[future]
                try:
                    events = future.result()
                except Exception as exc:
                    print(f"Failed to fetch {league_code} scoreboard for {date}: {exc}")
                    continue

                for event in events:
                    event_id = event.get('id')
                    if not event_id:
                        continue
                    aggregated[league_code][event_id] = event

        all_games = {code: list(events.values()) for code, events in aggregated.items()}

        for games in all_games.values():
            games.sort(key=lambda game: game.get('timestamp') or 0)

        self.enricher.enrich_games(all_games, self.league_lookup)
        self.latest_league_news = self._fetch_league_news(self._app_news_leagues())

        return all_games

    def get_games_summary(
        self,
        all_games: Dict[str, List[Dict]],
        *,
        league_news: Optional[Dict[str, List[Dict]]] = None,
    ) -> Dict:
        """Return a structured summary of fetched games."""
        total_games = sum(len(games) for games in all_games.values())
        league_news = league_news or self.latest_league_news

        summary = {
            'total_games': total_games,
            'sports_count': len([code for code, games in all_games.items() if games]),
            'last_updated': datetime.utcnow().isoformat(),
            'by_sport': {},
            'next_24_hours': {},
            'enriched_games': self._count_enriched_games(all_games),
            'discovery': self._build_discovery_snapshot(),
            'news_feeds': league_news,
        }

        for code, games in all_games.items():
            descriptor = self.league_lookup.get(code)
            summary['by_sport'][code] = {
                'count': len(games),
                'sport_name': descriptor.display_name if descriptor else code.upper(),
                'sport_slug': descriptor.sport_slug if descriptor else None,
            }

        cutoff = datetime.utcnow() + timedelta(hours=24)
        for code, games in all_games.items():
            upcoming = [game for game in games if self._is_within(game, cutoff)]
            if upcoming:
                summary['next_24_hours'][code] = {
                    'count': len(upcoming),
                    'games': upcoming[:5],
                }

        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _select_leagues(self, league_codes: Optional[Sequence[str]]) -> List[LeagueDescriptor]:
        if not league_codes:
            return self.leagues
        return [self.league_lookup[code] for code in league_codes if code in self.league_lookup]

    def _build_date_list(self, days_ahead: int) -> List[str]:
        today = datetime.utcnow()
        return [
            (today + timedelta(days=offset)).strftime('%Y%m%d')
            for offset in range(max(days_ahead, 1))
        ]

    def _fetch_league_for_date(self, league: LeagueDescriptor, date: str) -> List[Dict]:
        params = {'dates': date, 'limit': 300}
        if self.scoreboard_enables:
            params['enable'] = self.scoreboard_enables
        payload = self.client.get_json(league.scoreboard_url, params=params)
        games: List[Dict] = []
        for event in payload.get('events', []) or []:
            parsed = self._parse_event(league, event)
            if parsed:
                games.append(parsed)
        return games

    def _parse_event(self, league: LeagueDescriptor, event: Dict) -> Optional[Dict]:
        competitions = event.get('competitions') or []
        if not competitions:
            return None
        competition = competitions[0]

        game = {
            'id': event.get('id'),
            'uid': event.get('uid'),
            'league': {
                'code': league.code,
                'name': league.display_name,
                'sport_slug': league.sport_slug,
                'league_slug': league.league_slug,
                'season_year': league.season_year,
            },
            'sport': league.display_name,
            'sport_code': league.code,
            'name': event.get('name'),
            'short_name': event.get('shortName'),
            'date': event.get('date'),
            'season': event.get('season'),
            'week': event.get('week', {}).get('number'),
            'tickets': event.get('tickets'),
            'links': self._parse_links(event.get('links')),
            'status_detail': None,
        }

        status = event.get('status', {}).get('type', {})
        game['status'] = status.get('description') or status.get('detail')
        game['status_id'] = status.get('id')
        game['status_state'] = status.get('state')
        game['status_short'] = status.get('shortDetail')
        game['status_detail'] = status.get('detail')
        game['is_final'] = status.get('completed', False)
        game['is_live'] = status.get('state') == 'in'
        game['time_remaining'] = event.get('status', {}).get('displayClock')

        game['venue'] = self._parse_venue(competition.get('venue'))
        home_team, away_team = self._parse_competitors(competition.get('competitors'))
        game['home_team'] = home_team
        game['away_team'] = away_team
        game['home_score'] = home_team.get('score') if home_team else None
        game['away_score'] = away_team.get('score') if away_team else None
        game['leaders'] = self._parse_leaders(competition.get('leaders'))
        game['attendance'] = competition.get('attendance')
        game['broadcasts'] = self._parse_broadcasts(competition.get('broadcasts'))
        game['geo_broadcasts'] = self._parse_geo_broadcasts(competition.get('geoBroadcasts'))
        game['odds'] = competition.get('odds')
        game['predictor'] = competition.get('predictor')
        game['notes'] = self._collect_notes(event, competition)
        game['situation'] = competition.get('situation')
        game['start_date'] = competition.get('startDate')
        game['recent'] = competition.get('recent', False)
        game['headlines'] = competition.get('headlines') or event.get('headlines')

        if game['date']:
            try:
                dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
                game['formatted_date'] = dt.strftime('%Y-%m-%d')
                game['formatted_time'] = dt.strftime('%I:%M %p ET')
                game['timestamp'] = dt.timestamp()
            except ValueError:
                pass

        return game

    def _parse_competitors(self, competitors: Optional[List[Dict]]) -> (Optional[Dict], Optional[Dict]):
        home = None
        away = None
        for competitor in competitors or []:
            team = competitor.get('team') or {}
            info = {
                'id': competitor.get('id'),
                'uid': competitor.get('uid'),
                'name': team.get('displayName'),
                'location': team.get('location'),
                'abbreviation': team.get('abbreviation'),
                'logo': team.get('logo'),
                'record': self._parse_records(competitor.get('records')),
                'rank': (competitor.get('curatedRank') or {}).get('current'),
                'score': int(competitor['score']) if competitor.get('score') else None,
                'homeAway': competitor.get('homeAway'),
                'winner': competitor.get('winner'),
                'linescores': self._parse_linescores(competitor.get('linescores')),
            }
            if competitor.get('statistics'):
                info['statistics'] = competitor['statistics']

            if competitor.get('homeAway') == 'home':
                home = info
            else:
                away = info
        return home, away

    @staticmethod
    def _parse_records(records: Optional[List[Dict]]) -> List[Dict]:
        parsed = []
        for record in records or []:
            parsed.append({
                'summary': record.get('summary'),
                'type': record.get('type'),
            })
        return parsed

    @staticmethod
    def _parse_linescores(linescores: Optional[List[Dict]]) -> List[Dict]:
        parsed = []
        for line in linescores or []:
            parsed.append({
                'period': line.get('period'),
                'value': line.get('value'),
                'display': line.get('displayValue'),
            })
        return parsed

    @staticmethod
    def _parse_venue(venue: Optional[Dict]) -> Optional[Dict]:
        if not venue:
            return None
        return {
            'id': venue.get('id'),
            'name': venue.get('fullName'),
            'city': (venue.get('address') or {}).get('city'),
            'state': (venue.get('address') or {}).get('state'),
            'indoor': venue.get('indoor'),
        }

    @staticmethod
    def _parse_broadcasts(broadcasts: Optional[List[Dict]]) -> List[Dict]:
        output = []
        for broadcast in broadcasts or []:
            output.append({
                'market': broadcast.get('market'),
                'names': broadcast.get('names'),
                'type': broadcast.get('type', {}).get('shortName') if isinstance(broadcast.get('type'), dict) else None,
            })
        return output

    @staticmethod
    def _parse_geo_broadcasts(geo_broadcasts: Optional[List[Dict]]) -> List[Dict]:
        output = []
        for geo in geo_broadcasts or []:
            output.append({
                'type': (geo.get('type') or {}).get('shortName'),
                'market': (geo.get('market') or {}).get('type'),
                'media': (geo.get('media') or {}).get('shortName'),
            })
        return output

    @staticmethod
    def _parse_leaders(leaders: Optional[List[Dict]]) -> Dict[str, List[Dict]]:
        parsed: Dict[str, List[Dict]] = {}
        for leader in leaders or []:
            name = leader.get('name') or leader.get('displayName') or 'leaders'
            parsed[name] = []
            for athlete in leader.get('leaders') or []:
                parsed[name].append({
                    'athlete': (athlete.get('athlete') or {}).get('displayName'),
                    'team': (athlete.get('team') or {}).get('abbreviation'),
                    'value': athlete.get('value'),
                    'displayValue': athlete.get('displayValue'),
                })
        return parsed

    @staticmethod
    def _parse_links(links: Optional[List[Dict]]) -> List[Dict]:
        parsed = []
        for link in links or []:
            parsed.append({
                'rel': link.get('rel'),
                'href': link.get('href'),
                'text': link.get('shortText') or link.get('text'),
            })
        return parsed

    @staticmethod
    def _collect_notes(event: Dict, competition: Dict) -> List[str]:
        notes = []
        for headline in competition.get('headlines') or event.get('headlines') or []:
            text = headline.get('description') or headline.get('shortLinkText')
            if text:
                notes.append(text)
        return notes

    def _is_within(self, game: Dict, cutoff: datetime) -> bool:
        ts = game.get('timestamp')
        if not ts:
            return False
        return datetime.fromtimestamp(ts, tz=timezone.utc) <= cutoff.replace(tzinfo=timezone.utc)

    def _count_enriched_games(self, all_games: Dict[str, List[Dict]]) -> int:
        return sum(1 for games in all_games.values() for game in games if game.get('live_feed'))

    def _build_discovery_snapshot(self) -> Dict:
        return {
            'generated_at': self.discovery_snapshot,
            'league_count': len(self.leagues),
            'leagues': [
                {
                    'code': league.code,
                    'name': league.display_name,
                    'sport': league.sport_slug,
                    'league': league.league_slug,
                }
                for league in self.leagues
            ],
        }

    def _fetch_league_news(self, leagues: Sequence[Optional[LeagueDescriptor]]) -> Dict[str, List[Dict]]:
        if not SPORTS_NEWS_SETTINGS.get('enabled'):
            return {}
        limit = SPORTS_NEWS_SETTINGS.get('limit', 5)
        news: Dict[str, List[Dict]] = {}
        for league in leagues:
            if not league:
                continue
            articles = self._get_news_for_league(league, limit)
            if articles:
                news[league.code] = articles
        return news

    def _app_news_leagues(self) -> List[LeagueDescriptor]:
        leagues: List[LeagueDescriptor] = []
        seen = set()
        for code in APP_NEWS_LEAGUE_CODES:
            league = self.league_lookup.get(code) or self._fallback_league(code)
            if not league or league.code in seen:
                continue
            leagues.append(league)
            seen.add(league.code)
        return leagues

    def _get_news_for_league(self, league: LeagueDescriptor, limit: int) -> List[Dict]:
        try:
            payload = self.client.get_json(NEWS_TEMPLATE.format(path=league.scoreboard_path), params={'limit': limit})
        except Exception:
            return []

        articles = []
        for article in payload.get('articles') or []:
            web_link = ((article.get('links') or {}).get('web') or {}).get('href')
            headline = article.get('headline')
            if not headline or not web_link:
                continue
            raw_source = article.get('source')
            source = raw_source.get('name') if isinstance(raw_source, dict) else raw_source
            articles.append({
                'headline': headline,
                'description': article.get('description'),
                'link': web_link,
                'published': article.get('published'),
                'images': article.get('images'),
                'source': source or 'ESPN',
            })
        return articles

    def _fallback_leagues(self) -> List[LeagueDescriptor]:
        leagues: List[LeagueDescriptor] = []
        for code in FALLBACK_LEAGUES:
            league = self._fallback_league(code)
            if league:
                leagues.append(league)
        return leagues

    @staticmethod
    def _fallback_league(code: str) -> Optional[LeagueDescriptor]:
        fallback = FALLBACK_LEAGUES.get(code)
        if not fallback:
            return None

        sport_slug, league_slug, name, abbr = fallback
        path = f"{sport_slug}/{league_slug}"
        return LeagueDescriptor(
            sport_slug=sport_slug,
            league_slug=league_slug,
            display_name=name,
            abbreviation=abbr,
            code=code,
            api_ref='',
            scoreboard_path=path,
            scoreboard_url=SCOREBOARD_TEMPLATE.format(path=path),
        )
