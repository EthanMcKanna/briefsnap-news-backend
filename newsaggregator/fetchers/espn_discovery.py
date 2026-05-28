"""Auto-discovery for ESPN leagues using the public directory endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

from newsaggregator.config.settings import DATA_DIR, SPORTS_DISCOVERY

from .espn_client import ESPNHTTPClient

SPORTS_CORE_ROOT = "https://sports.core.api.espn.com/v2/sports"
SCOREBOARD_TEMPLATE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"

LEGACY_CODE_OVERRIDES = {
    ("football", "college-football"): "ncaaf",
    ("basketball", "mens-college-basketball"): "ncaab",
    ("basketball", "womens-college-basketball"): "ncaaw",
    ("soccer", "usa.1"): "mls",
}


def _sanitize_list(values: List[str]) -> List[str]:
    return [value.strip() for value in values if value.strip()]


@dataclass
class LeagueDescriptor:
    """Metadata required to talk to a league's scoreboard endpoints."""

    sport_slug: str
    league_slug: str
    display_name: str
    abbreviation: str
    code: str
    api_ref: str
    scoreboard_path: str
    scoreboard_url: str
    season_year: Optional[int] = None
    season_type: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class EspnLeagueDiscovery:
    """Handles refreshing and caching the directory structure."""

    def __init__(self, client: Optional[ESPNHTTPClient] = None) -> None:
        self.client = client or ESPNHTTPClient()
        self.cache_path = DATA_DIR / "sports_discovery" / "leagues.json"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        self.settings = SPORTS_DISCOVERY
        self.sports_whitelist = set(_sanitize_list(self.settings['sports_whitelist']))
        self.league_blacklist = set(_sanitize_list(self.settings['league_blacklist']))
        self.cache_ttl = timedelta(hours=self.settings['cache_ttl_hours'])
        self.max_leagues_per_sport = max(self.settings['max_leagues_per_sport'], 1)

    def get_leagues(self, force_refresh: bool = False) -> List[LeagueDescriptor]:
        """Return cached leagues, refreshing if stale."""

        if not force_refresh:
            cached = self._load_cache()
            if cached:
                return cached

        if not self.settings['enabled']:
            return []

        leagues = self._fetch_remote_leagues()
        self._save_cache(leagues)
        return leagues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_remote_leagues(self) -> List[LeagueDescriptor]:
        payload = self.client.get_json(SPORTS_CORE_ROOT, params={'lang': 'en', 'region': 'us'})
        descriptors: List[LeagueDescriptor] = []

        for sport_item in payload.get('items', []):
            sport_ref = sport_item.get('$ref')
            if not sport_ref:
                continue

            sport_data = self.client.get_json(sport_ref)
            sport_slug = sport_data.get('slug')
            if self.sports_whitelist and sport_slug not in self.sports_whitelist:
                continue

            leagues_url = sport_data.get('leagues', {}).get('$ref')
            if not leagues_url:
                continue

            league_payload = self.client.get_json(leagues_url)
            count = 0

            for league_item in league_payload.get('items', []):
                if count >= self.max_leagues_per_sport:
                    break

                league_ref = league_item.get('$ref')
                if not league_ref:
                    continue

                descriptor = self._build_league_descriptor(sport_slug, league_ref)
                if not descriptor:
                    continue

                blacklist_key = f"{descriptor.sport_slug}/{descriptor.league_slug}"
                if blacklist_key in self.league_blacklist:
                    continue

                descriptors.append(descriptor)
                count += 1

        return descriptors

    def _build_league_descriptor(
        self,
        sport_slug: Optional[str],
        league_ref: str,
    ) -> Optional[LeagueDescriptor]:
        try:
            league_data = self.client.get_json(league_ref)
        except Exception:
            return None

        slug = league_data.get('slug')
        if not slug or not sport_slug:
            sport_slug, slug = self._parse_slugs_from_ref(league_ref)

        scoreboard_path = f"{sport_slug}/{slug}"
        scoreboard_url = SCOREBOARD_TEMPLATE.format(path=scoreboard_path)
        abbreviation = league_data.get('abbreviation') or slug.replace('-', ' ').upper()
        code = LEGACY_CODE_OVERRIDES.get((sport_slug, slug)) or abbreviation.lower()

        season = league_data.get('season', {})
        season_year = season.get('year') if isinstance(season, dict) else None
        season_type = None
        if isinstance(season, dict):
            season_type_data = season.get('type')
            if isinstance(season_type_data, dict):
                season_type = season_type_data.get('name')

        return LeagueDescriptor(
            sport_slug=sport_slug,
            league_slug=slug,
            display_name=league_data.get('displayName', slug.replace('-', ' ').title()),
            abbreviation=abbreviation,
            code=code,
            api_ref=league_ref,
            scoreboard_path=scoreboard_path,
            scoreboard_url=scoreboard_url,
            season_year=season_year,
            season_type=season_type,
        )

    @staticmethod
    def _parse_slugs_from_ref(ref: str) -> (str, str):
        parsed = urlparse(ref)
        parts = parsed.path.split('/')
        # ['', 'v2', 'sports', '{sport}', 'leagues', '{league}']
        if len(parts) >= 6:
            return parts[3], parts[5]
        return 'unknown', ref.rsplit('/', 1)[-1]

    def _load_cache(self) -> Optional[List[LeagueDescriptor]]:
        if not self.cache_path.exists():
            return None

        try:
            raw = self.cache_path.read_text()
            if not raw:
                return None
            payload = json.loads(raw)
        except Exception:
            return None

        timestamp = payload.get('generated_at')
        if timestamp:
            generated = datetime.fromisoformat(timestamp)
            if datetime.utcnow() - generated > self.cache_ttl:
                return None

        leagues = [LeagueDescriptor(**item) for item in payload.get('leagues', [])]
        return leagues

    def _save_cache(self, leagues: List[LeagueDescriptor]) -> None:
        payload = {
            'generated_at': datetime.utcnow().isoformat(),
            'leagues': [league.to_dict() for league in leagues],
        }
        self.cache_path.write_text(json.dumps(payload, indent=2))
