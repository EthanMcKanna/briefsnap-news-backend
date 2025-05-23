"""Sports data fetcher for upcoming games from popular sports."""

import requests
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import time
import re
from typing import List, Dict, Optional

class SportsFetcher:
    """Fetches upcoming sports games from various free sources."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # ESPN API endpoints for different sports
        self.espn_endpoints = {
            'nfl': 'http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
            'nba': 'http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
            'mlb': 'http://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard',
            'nhl': 'http://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
            'ncaaf': 'http://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard',
            'ncaab': 'http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard',
            'mls': 'http://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard',
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
    
    def fetch_espn_games(self, sport: str, dates: List[str] = None) -> List[Dict]:
        """Fetch games for a specific sport from ESPN API.
        
        Args:
            sport: Sport code (nfl, nba, mlb, etc.)
            dates: List of dates in YYYYMMDD format. If None, fetches next 7 days.
            
        Returns:
            List of game dictionaries
        """
        if sport not in self.espn_endpoints:
            print(f"Sport '{sport}' not supported")
            return []
        
        if dates is None:
            # Default to next 7 days
            dates = []
            for i in range(7):
                date = datetime.now() + timedelta(days=i)
                dates.append(date.strftime('%Y%m%d'))
        
        games = []
        
        for date in dates:
            try:
                url = f"{self.espn_endpoints[sport]}?dates={date}"
                print(f"Fetching {sport.upper()} games for {date}")
                
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                
                if 'events' in data:
                    for event in data['events']:
                        game = self._parse_espn_game(event, sport)
                        if game:
                            games.append(game)
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error fetching {sport} games for {date}: {e}")
                continue
        
        return games
    
    def _parse_espn_game(self, event: Dict, sport: str) -> Optional[Dict]:
        """Parse ESPN game event into standardized format.
        
        Args:
            event: ESPN event data
            sport: Sport code
            
        Returns:
            Standardized game dictionary or None
        """
        try:
            game = {
                'id': event.get('id'),
                'sport': self.sport_names.get(sport, sport.upper()),
                'sport_code': sport,
                'date': event.get('date'),
                'status': event.get('status', {}).get('type', {}).get('description', 'TBD'),
                'venue': None,
                'home_team': None,
                'away_team': None,
                'home_score': None,
                'away_score': None,
                'time_remaining': None,
                'broadcasts': [],
                'odds': None,
                'notes': [],
                'season': event.get('season', {}).get('year'),
                'week': event.get('week', {}).get('number') if sport in ['nfl', 'ncaaf'] else None,
            }
            
            # Parse teams
            if 'competitions' in event and event['competitions']:
                competition = event['competitions'][0]
                
                # Venue information
                if 'venue' in competition:
                    venue = competition['venue']
                    game['venue'] = {
                        'name': venue.get('fullName'),
                        'city': venue.get('address', {}).get('city'),
                        'state': venue.get('address', {}).get('state'),
                    }
                
                # Teams and scores
                if 'competitors' in competition:
                    for competitor in competition['competitors']:
                        team_info = {
                            'id': competitor.get('id'),
                            'name': competitor.get('team', {}).get('displayName'),
                            'abbreviation': competitor.get('team', {}).get('abbreviation'),
                            'logo': competitor.get('team', {}).get('logo'),
                            'record': competitor.get('records', [{}])[0].get('summary') if competitor.get('records') else None,
                            'rank': competitor.get('curatedRank', {}).get('current') if competitor.get('curatedRank') else None,
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
                
                # Broadcast information
                if 'broadcasts' in competition:
                    game['broadcasts'] = [
                        {
                            'network': broadcast.get('names', [None])[0],
                            'type': broadcast.get('type', {}).get('shortName')
                        }
                        for broadcast in competition['broadcasts']
                    ]
                
                # Odds (if available)
                if 'odds' in competition and competition['odds']:
                    odds = competition['odds'][0]
                    game['odds'] = {
                        'provider': odds.get('provider', {}).get('name'),
                        'spread': odds.get('details'),
                        'over_under': odds.get('overUnder'),
                    }
                
                # Status and time
                status = competition.get('status', {})
                game['status'] = status.get('type', {}).get('description', 'TBD')
                if 'displayClock' in status:
                    game['time_remaining'] = status['displayClock']
                
                # Headlines/notes
                if 'headlines' in event:
                    game['notes'] = [headline.get('description') for headline in event['headlines']]
            
            # Format date
            if game['date']:
                try:
                    dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
                    game['formatted_date'] = dt.strftime('%Y-%m-%d')
                    game['formatted_time'] = dt.strftime('%I:%M %p ET')
                    game['timestamp'] = dt.timestamp()
                except:
                    pass
            
            return game
            
        except Exception as e:
            print(f"Error parsing ESPN game: {e}")
            return None
    
    def fetch_all_sports(self, days_ahead: int = 7) -> Dict[str, List[Dict]]:
        """Fetch upcoming games for all supported sports.
        
        Args:
            days_ahead: Number of days ahead to fetch games for
            
        Returns:
            Dictionary with sport codes as keys and game lists as values
        """
        # Generate date list
        dates = []
        for i in range(days_ahead):
            date = datetime.now() + timedelta(days=i)
            dates.append(date.strftime('%Y%m%d'))
        
        all_games = {}
        
        for sport in self.espn_endpoints.keys():
            print(f"Fetching {sport.upper()} games...")
            games = self.fetch_espn_games(sport, dates)
            all_games[sport] = games
            print(f"Found {len(games)} upcoming {sport.upper()} games")
            
            # Rate limiting between sports
            time.sleep(1)
        
        return all_games
    
    def get_games_summary(self, all_games: Dict[str, List[Dict]]) -> Dict:
        """Generate a summary of all fetched games.
        
        Args:
            all_games: Dictionary of games by sport
            
        Returns:
            Summary dictionary
        """
        total_games = sum(len(games) for games in all_games.values())
        
        summary = {
            'total_games': total_games,
            'sports_count': len([sport for sport, games in all_games.items() if games]),
            'last_updated': datetime.now().isoformat(),
            'by_sport': {},
            'next_24_hours': {},
        }
        
        # Count by sport
        for sport, games in all_games.items():
            summary['by_sport'][sport] = {
                'count': len(games),
                'sport_name': self.sport_names.get(sport, sport.upper())
            }
        
        # Games in next 24 hours
        cutoff = datetime.now() + timedelta(hours=24)
        for sport, games in all_games.items():
            next_24_games = []
            for game in games:
                if game.get('date'):
                    try:
                        game_dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
                        if game_dt <= cutoff:
                            next_24_games.append(game)
                    except:
                        continue
            
            if next_24_games:
                summary['next_24_hours'][sport] = {
                    'count': len(next_24_games),
                    'games': next_24_games[:5]  # Top 5 soonest games
                }
        
        return summary 