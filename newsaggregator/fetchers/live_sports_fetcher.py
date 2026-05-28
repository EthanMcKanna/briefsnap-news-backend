"""Lightweight fetcher for live sports games updates."""

import requests
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import time

class LiveSportsFetcher:
    """Efficient fetcher for updating live/in-progress games only."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # ESPN API endpoints for different sports
        self.espn_endpoints = {
            'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
            'nba': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
            'mlb': 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard',
            'nhl': 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
            'ncaaf': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard',
            'ncaab': 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard',
            'mls': 'https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard',
        }
        
        # Sport display names
        self.sport_names = {
            'nfl': 'NFL',
            'nba': 'NBA',
            'mlb': 'MLB',
            'nhl': 'NHL',
            'ncaaf': 'College Football',
            'ncaab': 'College Basketball',
            'mls': 'MLS',
        }
        
        # Status keywords that indicate live games
        self.live_status_keywords = [
            'live', 'in progress', 'In Progress', 'active', '1st', '2nd', '3rd', '4th', 
            'quarter', 'period', 'inning', 'half', 'overtime', 'ot',
            'bottom', 'top', 'end', 'halftime', 'intermission'
        ]
    
    def fetch_live_games_only(self, sport: str) -> List[Dict]:
        """Fetch only live/in-progress games for a specific sport.
        
        Args:
            sport: Sport code (nfl, nba, mlb, etc.)
            
        Returns:
            List of live game dictionaries
        """
        if sport not in self.espn_endpoints:
            print(f"Sport '{sport}' not supported")
            return []
        
        # Check both today and yesterday in UTC; late games can span midnight.
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y%m%d')
        yesterday = (now - timedelta(days=1)).strftime('%Y%m%d')
        dates_to_check = [yesterday, today]
        
        live_games = []
        
        for date in dates_to_check:
            try:
                print(f"Checking for live {sport.upper()} games on {date}...")
                
                response = self.session.get(
                    self.espn_endpoints[sport],
                    params={
                        'dates': date,
                        'limit': 120,
                        'enable': 'linescores,leaders,statistics,situation,odds,broadcasts',
                    },
                    timeout=8,
                )
                response.raise_for_status()
                
                data = response.json()
                
                if 'events' in data:
                    for event in data['events']:
                        # Quick check if game is live before full parsing
                        if self._is_game_live(event):
                            game = self._parse_espn_game_quick(event, sport)
                            if game:
                                live_games.append(game)
                
                # Short delay between date requests
                time.sleep(0.2)
                
            except Exception as e:
                print(f"Error fetching live {sport} games for {date}: {e}")
                continue
        
        if live_games:
            print(f"Found {len(live_games)} live {sport.upper()} games")
        
        return live_games
    
    def _is_game_live_or_recently_finished(self, event: Dict) -> bool:
        """Check if a game is currently live OR recently finished.
        
        We need to catch both live games and games that just finished
        to properly update their final status.
        
        Args:
            event: ESPN event data
            
        Returns:
            True if game is live or recently finished, False otherwise
        """
        try:
            status_type = event.get('status', {}).get('type', {})
            status = status_type.get('description', '')
            state = (status_type.get('state') or '').lower()
            completed = bool(status_type.get('completed'))
            status_lower = " ".join(
                str(value).lower()
                for value in (
                    status,
                    status_type.get('shortDetail'),
                    status_type.get('detail'),
                    event.get('status', {}).get('displayClock'),
                )
                if value
            )
            
            # Check for live status keywords
            is_live = state == 'in' or any(keyword.lower() in status_lower for keyword in self.live_status_keywords)
            
            # Also check for games that just finished so the final score lands quickly.
            is_recently_finished = completed and self._event_within_hours(event, hours=10)
            
            return is_live or is_recently_finished
            
        except Exception:
            return False
    
    def _is_game_live(self, event: Dict) -> bool:
        """Quick check if a game is currently live (backward compatibility).
        
        Args:
            event: ESPN event data
            
        Returns:
            True if game appears to be live, False otherwise
        """
        return self._is_game_live_or_recently_finished(event)
    
    def _parse_espn_game_quick(self, event: Dict, sport: str) -> Optional[Dict]:
        """Lightweight parsing focused on live game essentials.
        
        Args:
            event: ESPN event data
            sport: Sport code
            
        Returns:
            Essential game data dictionary or None
        """
        try:
            status_payload = event.get('status', {})
            status_type = status_payload.get('type', {})
            state = status_type.get('state')
            completed = bool(status_type.get('completed'))

            game = {
                'id': event.get('id'),
                'sport': self.sport_names.get(sport, sport.upper()),
                'sport_code': sport,
                'league': {
                    'code': sport,
                    'name': self.sport_names.get(sport, sport.upper()),
                },
                'name': event.get('name'),
                'short_name': event.get('shortName'),
                'date': event.get('date'),
                'status': status_type.get('description') or status_type.get('detail') or 'TBD',
                'status_id': status_type.get('id'),
                'status_state': state,
                'status_short': status_type.get('shortDetail'),
                'status_detail': status_type.get('detail'),
                'is_live': state == 'in',
                'is_final': completed or state == 'post',
                'home_team': None,
                'away_team': None,
                'home_score': None,
                'away_score': None,
                'time_remaining': None,
                'last_updated': datetime.now(timezone.utc),
            }
            
            # Parse essential team and score data
            if 'competitions' in event and event['competitions']:
                competition = event['competitions'][0]
                
                # Teams and scores
                if 'competitors' in competition:
                    for competitor in competition['competitors']:
                        team_info = {
                            'id': competitor.get('id'),
                            'uid': competitor.get('uid'),
                            'name': competitor.get('team', {}).get('displayName'),
                            'location': competitor.get('team', {}).get('location'),
                            'abbreviation': competitor.get('team', {}).get('abbreviation'),
                            'logo': competitor.get('team', {}).get('logo'),
                            'record': self._record_summary(competitor.get('records')),
                            'homeAway': competitor.get('homeAway'),
                            'winner': competitor.get('winner'),
                            'linescores': competitor.get('linescores') or [],
                        }
                        
                        score = competitor.get('score')
                        if score:
                            team_info['score'] = int(score)
                        
                        if competitor.get('homeAway') == 'home':
                            game['home_team'] = team_info
                            game['home_score'] = team_info.get('score')
                        else:
                            game['away_team'] = team_info
                            game['away_score'] = team_info.get('score')
                
                # Status and time
                status = competition.get('status', {})
                status_type = status.get('type', {})
                game['status'] = status_type.get('description') or status_type.get('detail') or 'TBD'
                game['status_id'] = status_type.get('id')
                game['status_state'] = status_type.get('state')
                game['status_short'] = status_type.get('shortDetail')
                game['status_detail'] = status_type.get('detail')
                game['is_live'] = game['status_state'] == 'in'
                game['is_final'] = bool(status_type.get('completed')) or game['status_state'] == 'post'
                
                # For baseball and sports with innings/periods, use detail instead of clock
                status_detail = status_type.get('detail', '')
                if status_detail and sport in ['mlb']:
                    # Use the inning info for baseball (e.g., "Bottom 7th")
                    game['time_remaining'] = status_detail
                elif 'displayClock' in status and status['displayClock'] != '0:00':
                    # Use clock for sports that have actual time (NBA, NFL, etc.)
                    game['time_remaining'] = status['displayClock']
                else:
                    game['time_remaining'] = None
            
            # Format date
            if game['date']:
                try:
                    dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
                    game['timestamp'] = dt.timestamp()
                    game['formatted_date'] = dt.strftime('%Y-%m-%d')
                    game['formatted_time'] = dt.strftime('%I:%M %p UTC')
                except:
                    pass
            
            return game
            
        except Exception as e:
            print(f"Error parsing live ESPN game: {e}")
            return None

    @staticmethod
    def _record_summary(records: Optional[List[Dict]]) -> str:
        for record in records or []:
            summary = record.get('summary')
            if summary:
                return summary
        return ''

    @staticmethod
    def _event_within_hours(event: Dict, hours: int) -> bool:
        try:
            event_date = datetime.fromisoformat(event.get('date', '').replace('Z', '+00:00'))
        except Exception:
            return False
        age_seconds = (datetime.now(timezone.utc) - event_date.astimezone(timezone.utc)).total_seconds()
        return 0 <= age_seconds <= hours * 3600
    
    def fetch_all_live_games(self) -> Dict[str, List[Dict]]:
        """Fetch live games for all supported sports.
        
        Returns:
            Dictionary with sport codes as keys and live game lists as values
        """
        all_live_games = {}
        total_live_games = 0
        
        for sport in self.espn_endpoints.keys():
            live_games = self.fetch_live_games_only(sport)
            all_live_games[sport] = live_games
            total_live_games += len(live_games)
            
            # Short delay between sports for rate limiting
            time.sleep(0.3)
        
        print(f"Total live games found across all sports: {total_live_games}")
        return all_live_games
    
    def get_live_games_summary(self, all_live_games: Dict[str, List[Dict]]) -> Dict:
        """Generate a summary of all live and recently finished games.
        
        Args:
            all_live_games: Dictionary of live/recent games by sport
            
        Returns:
            Summary dictionary
        """
        total_games = sum(len(games) for games in all_live_games.values())
        
        # Separate live vs finished games
        live_count = 0
        finished_count = 0
        
        for games in all_live_games.values():
            for game in games:
                status = game.get('status', '')
                if status in ['Final', 'Final/OT', 'Final/SO', 'Completed']:
                    finished_count += 1
                else:
                    live_count += 1
        
        summary = {
            'total_games': total_games,
            'total_live_games': live_count,
            'total_finished_games': finished_count,
            'sports_with_games': len([sport for sport, games in all_live_games.items() if games]),
            'last_updated': datetime.now().isoformat(),
            'by_sport': {},
            'live_games_detail': [],
            'finished_games_detail': [],
        }
        
        # Count by sport and collect game details
        for sport, games in all_live_games.items():
            if games:
                sport_live = 0
                sport_finished = 0
                
                for game in games:
                    status = game.get('status', '')
                    game_detail = {
                        'sport': game.get('sport'),
                        'away_team': game.get('away_team', {}).get('abbreviation', 'TBD'),
                        'home_team': game.get('home_team', {}).get('abbreviation', 'TBD'),
                        'away_score': game.get('away_score', 0),
                        'home_score': game.get('home_score', 0),
                        'status': status,
                        'time_remaining': game.get('time_remaining', ''),
                    }
                    
                    if game.get('is_final') or status in ['Final', 'Final/OT', 'Final/SO', 'Completed']:
                        sport_finished += 1
                        summary['finished_games_detail'].append(game_detail)
                    else:
                        sport_live += 1
                        summary['live_games_detail'].append(game_detail)
                
                summary['by_sport'][sport] = {
                    'total': len(games),
                    'live': sport_live,
                    'finished': sport_finished,
                    'sport_name': self.sport_names.get(sport, sport.upper())
                }
        
        return summary
    
    def should_check_for_live_games(self) -> bool:
        """Return whether the lightweight ESPN freshness pass should run."""
        if str(os.environ.get("BRIEFSNAP_DISABLE_LIVE_SPORTS", "")).lower() in {"1", "true", "yes"}:
            print("Live sports updates disabled by BRIEFSNAP_DISABLE_LIVE_SPORTS")
            return False
        print("✅ Running live sports freshness check")
        return True
