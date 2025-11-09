"""Game summary processor using Gemini Flash 2 Lite with Google Search."""

import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types
from newsaggregator.storage.sports_storage import SportsStorage


class GameSummaryProcessor:
    """Class for generating pre-game and post-game summaries using Gemini Flash 2 Lite with Google Search."""
    
    def __init__(self):
        """Initialize the Gemini client."""
        self.client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
        )
        self.model = "gemini-2.0-flash-lite"
        self.summary_index = {}
        
    def get_games_within_24_hours(self) -> List[Dict]:
        """Get all games happening within the next 24 hours.
        
        Returns:
            List of games within 24 hours
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=24)
        
        upcoming_games = SportsStorage.get_upcoming_games(limit=100)
        
        games_within_24h = []
        for game in upcoming_games:
            if game.get('date'):
                try:
                    game_dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
                    if game_dt <= cutoff:
                        games_within_24h.append(game)
                except:
                    continue
        
        return games_within_24h
    
    def get_recently_finished_games(self, hours_back: int = 4) -> List[Dict]:
        """Get games that finished within the specified hours.
        
        Args:
            hours_back: How many hours back to look for finished games
            
        Returns:
            List of recently finished games
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        
        # Get recently updated games that might be finished
        recent_games = SportsStorage.get_recently_updated_games(hours=hours_back)
        
        finished_games = []
        for game in recent_games:
            status = game.get('status', '').lower()
            if any(keyword in status for keyword in ['final', 'completed', 'ended']):
                # Check if game finished within our timeframe
                last_updated = game.get('last_updated')
                if last_updated and last_updated >= cutoff_time:
                    finished_games.append(game)
        
        return finished_games
    
    def format_game_info(self, game: Dict) -> str:
        """Format game information for the LLM prompt.
        
        Args:
            game: Game dictionary
            
        Returns:
            Formatted game info string
        """
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        
        home_name = home_team.get('name', 'Home Team')
        away_name = away_team.get('name', 'Away Team')
        sport = game.get('sport', 'Unknown Sport')
        
        formatted_date = game.get('formatted_date', 'TBD')
        formatted_time = game.get('formatted_time', 'TBD')
        
        venue_info = ""
        if game.get('venue', {}).get('name'):
            venue = game['venue']['name']
            city = game['venue'].get('city', '')
            venue_info = f" at {venue}, {city}"
        
        broadcast_info = ""
        if game.get('broadcasts'):
            networks = [b.get('network') for b in game['broadcasts'] if b.get('network')]
            if networks:
                broadcast_info = f" (TV: {', '.join(networks)})"
        
        # Add scores for finished games
        scores_info = ""
        if game.get('home_score') is not None and game.get('away_score') is not None:
            scores_info = f" - Final Score: {away_name} {game['away_score']}, {home_name} {game['home_score']}"
        
        return f"{sport}: {away_name} @ {home_name} on {formatted_date} at {formatted_time}{venue_info}{broadcast_info}{scores_info}"
    
    def generate_pre_game_summary(self, game: Dict) -> Optional[Dict]:
        """Generate a pre-game summary for a specific game.
        
        Args:
            game: Game dictionary
            
        Returns:
            Dictionary with summary data, or None if failed
        """
        try:
            game_info = self.format_game_info(game)
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown Sport')
            
            prompt = f"""Please search for and generate a helpful pre-game summary for this upcoming {sport} game:

{game_info}

Search for recent information about both teams and generate a concise pre-game analysis focusing on:
- Recent team performance and form
- Key players to watch (injuries, notable performers)
- Head-to-head matchup history or significance
- What's at stake for both teams
- Any notable storylines or context

Keep the summary helpful but succinct - around 100-150 words total. Make it clear this is about the {away_team} vs {home_team} game.

Format your response as:
**Pre-Game Summary:** [Concise analysis of the matchup and what to expect]

**Key Points:**
• [Key point 1]
• [Key point 2]
• [Key point 3]"""

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                    ],
                ),
            ]
            
            tools = [
                types.Tool(google_search=types.GoogleSearch()),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                tools=tools,
                response_mime_type="text/plain",
                temperature=0.7,
            )

            # Generate content using streaming
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text:
                    response_text += chunk.text

            if response_text.strip():
                return {
                    'game_id': game.get('id'),
                    'doc_id': game.get('doc_id'),
                    'sport_code': game.get('sport_code'),
                    'home_team': home_team,
                    'away_team': away_team,
                    'game_date': game.get('date'),
                    'summary_type': 'pre_game',
                    'summary': response_text.strip(),
                    'generated_at': datetime.now(timezone.utc),
                    'model_used': self.model
                }
            else:
                print(f"No pre-game summary generated for {away_team} @ {home_team}")
                return None
                
        except Exception as e:
            print(f"Error generating pre-game summary for {away_team} @ {home_team}: {e}")
            return None
    
    def generate_post_game_summary(self, game: Dict) -> Optional[Dict]:
        """Generate a post-game summary for a recently finished game.
        
        Args:
            game: Game dictionary
            
        Returns:
            Dictionary with summary data, or None if failed
        """
        try:
            game_info = self.format_game_info(game)
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown Sport')
            
            prompt = f"""Please search for and generate a helpful post-game summary for this recently completed {sport} game:

{game_info}

Search for game recap information and generate a concise post-game analysis focusing on:
- How the game unfolded and key moments
- Standout individual performances
- Turning points or decisive plays
- Statistical highlights
- Impact on teams' seasons or standings
- Notable quotes or reactions

Keep the summary informative but succinct - around 100-150 words total. Make it clear this is a recap of the completed {away_team} vs {home_team} game.

Format your response as:
**Post-Game Summary:** [Concise recap of how the game played out and key takeaways]

**Key Highlights:**
• [Key highlight 1]
• [Key highlight 2]
• [Key highlight 3]"""

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                    ],
                ),
            ]
            
            tools = [
                types.Tool(google_search=types.GoogleSearch()),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                tools=tools,
                response_mime_type="text/plain",
                temperature=0.7,
            )

            # Generate content using streaming
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text:
                    response_text += chunk.text

            if response_text.strip():
                return {
                    'game_id': game.get('id'),
                    'doc_id': game.get('doc_id'),
                    'sport_code': game.get('sport_code'),
                    'home_team': home_team,
                    'away_team': away_team,
                    'game_date': game.get('date'),
                    'final_score': f"{away_team} {game.get('away_score', 0)}, {home_team} {game.get('home_score', 0)}",
                    'summary_type': 'post_game',
                    'summary': response_text.strip(),
                    'generated_at': datetime.now(timezone.utc),
                    'model_used': self.model
                }
            else:
                print(f"No post-game summary generated for {away_team} @ {home_team}")
                return None
                
        except Exception as e:
            print(f"Error generating post-game summary for {away_team} @ {home_team}: {e}")
            return None
    
    def process_game_summaries(self) -> Dict:
        """Process and generate game summaries for upcoming and recently finished games.
        
        Returns:
            Dictionary with processing results
        """
        results = {
            'pre_game_summaries': [],
            'post_game_summaries': [],
            'pre_game_generated': 0,
            'post_game_generated': 0,
            'pre_game_skipped': 0,
            'post_game_skipped': 0,
            'errors': []
        }
        
        print("\n====== Processing Game Summaries ======")
        
        print("Checking for upcoming games within 24 hours...")
        upcoming_games = self.get_games_within_24_hours()
        print(f"Found {len(upcoming_games)} games within 24 hours")

        print("Checking for recently finished games...")
        finished_games = self.get_recently_finished_games(hours_back=4)
        print(f"Found {len(finished_games)} recently finished games")

        game_ids = {
            game.get('id')
            for game in [*upcoming_games, *finished_games]
            if game.get('id')
        }
        self.summary_index = SportsStorage.get_summary_index(list(game_ids))

        for game in upcoming_games:
            try:
                # Check if pre-game summary already exists
                if self._has_existing_summary(game, 'pre_game'):
                    results['pre_game_skipped'] += 1
                    continue
                
                home_team = game.get('home_team', {}).get('name', 'Home Team')
                away_team = game.get('away_team', {}).get('name', 'Away Team')
                
                print(f"Generating pre-game summary for {away_team} @ {home_team}...")
                
                summary = self.generate_pre_game_summary(game)
                if summary:
                    # Store in Firebase
                    if SportsStorage.store_game_summary(summary):
                        results['pre_game_summaries'].append(summary)
                        results['pre_game_generated'] += 1
                        self._mark_summary_generated(game, 'pre_game')
                        print(f"✅ Generated pre-game summary for {away_team} @ {home_team}")
                    else:
                        results['errors'].append(f"Failed to store pre-game summary for {away_team} @ {home_team}")
                else:
                    results['errors'].append(f"Failed to generate pre-game summary for {away_team} @ {home_team}")
                    
            except Exception as e:
                results['errors'].append(f"Error processing pre-game for {game.get('id', 'unknown')}: {e}")
        
        for game in finished_games:
            try:
                # Check if post-game summary already exists
                if self._has_existing_summary(game, 'post_game'):
                    results['post_game_skipped'] += 1
                    continue
                
                home_team = game.get('home_team', {}).get('name', 'Home Team')
                away_team = game.get('away_team', {}).get('name', 'Away Team')
                
                print(f"Generating post-game summary for {away_team} @ {home_team}...")
                
                summary = self.generate_post_game_summary(game)
                if summary:
                    # Store in Firebase
                    if SportsStorage.store_game_summary(summary):
                        results['post_game_summaries'].append(summary)
                        results['post_game_generated'] += 1
                        self._mark_summary_generated(game, 'post_game')
                        print(f"✅ Generated post-game summary for {away_team} @ {home_team}")
                    else:
                        results['errors'].append(f"Failed to store post-game summary for {away_team} @ {home_team}")
                else:
                    results['errors'].append(f"Failed to generate post-game summary for {away_team} @ {home_team}")
                    
            except Exception as e:
                results['errors'].append(f"Error processing post-game for {game.get('id', 'unknown')}: {e}")
        
        print(f"Game summary processing complete:")
        print(f"  Pre-game: {results['pre_game_generated']} generated, {results['pre_game_skipped']} skipped")
        print(f"  Post-game: {results['post_game_generated']} generated, {results['post_game_skipped']} skipped")
        if results['errors']:
            print(f"  Errors: {len(results['errors'])}")
        
        return results
    
    def _has_existing_summary(self, game: Dict, summary_type: str) -> bool:
        game_id = game.get('id')
        if not game_id:
            return False
        return summary_type in self.summary_index.get(game_id, set())

    def _mark_summary_generated(self, game: Dict, summary_type: str):
        game_id = game.get('id')
        if not game_id:
            return
        self.summary_index.setdefault(game_id, set()).add(summary_type)
