"""Main aggregator for the news system that orchestrates all components."""

import time
import signal
from datetime import datetime
from pathlib import Path

from newsaggregator.config.settings import (
    RSS_FEEDS, REQUEST_DELAY,
    COMBINED_DIR, SPORTS_API_KEY
)
from newsaggregator.fetchers.rss_fetcher import RSSFetcher
from newsaggregator.fetchers.sports_fetcher import SportsFetcher
from newsaggregator.processors.article_processor import ArticleProcessor
from newsaggregator.processors.gemini_processor import GeminiProcessor
from newsaggregator.storage.file_storage import FileStorage
from newsaggregator.storage.firebase_storage import FirebaseStorage

class NewsAggregator:
    """Main aggregator class that orchestrates the news collection and processing."""
    
    def __init__(self):
        """Initialize the news aggregator system."""
        self.running = True
        self.rss_fetcher = RSSFetcher()
        self.article_processor = ArticleProcessor()
        self.gemini_processor = GeminiProcessor()
        self.sports_fetcher = SportsFetcher(api_key=SPORTS_API_KEY)
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Initialize Firebase
        self.db = FirebaseStorage.initialize()
        if not self.db:
            print("Warning: Proceeding without Firestore integration")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        print("\nShutdown signal received. Completing current tasks...")
        self.running = False
    
    def process_feeds(self):
        """Process feeds for all topics.
        
        Returns:
            Dictionary of new articles by topic
        """
        new_articles_by_topic = {}
        
        for topic, feed_url in RSS_FEEDS.items():
            print(f"\nChecking {topic} news feed...")
            feed = self.rss_fetcher.fetch_feed(feed_url)
            if not feed:
                continue

            new_articles_by_topic[topic] = []
            entries = self.rss_fetcher.extract_entries(feed)
            
            for entry in entries:
                article_data, success = self.article_processor.process_article(entry, topic)
                if success:
                    new_articles_by_topic[topic].append(article_data)
                time.sleep(REQUEST_DELAY)
        
        return new_articles_by_topic
    
    def generate_summaries(self):
        """Generate summaries for each topic.
        
        Returns:
            Dictionary of summaries by topic
        """
        print("\nGenerating news summaries...")
        summaries = {}
        
        for topic in RSS_FEEDS.keys():
            print(f"\nProcessing {topic}...")
            
            # Get the combined file path for this topic
            combined_file = Path(COMBINED_DIR) / FileStorage.get_combined_filename(topic)
            
            if not combined_file.exists():
                print(f"No combined file found for topic: {topic}")
                continue
                
            # Read the combined file content
            with open(combined_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Generate summary using Gemini
            summary = self.gemini_processor.generate_summary(content, topic)
            
            if summary:
                # Add detailed content to each story
                summary = self.article_processor.process_for_summary(summary)
                
                # Generate brief summary
                brief_data = self.gemini_processor.generate_brief_summary(
                    summary.get('Summary', ''), topic
                )
                
                if brief_data:
                    summary['brief_summary'] = brief_data.get('BriefSummary', '')
                    summary['bullet_points'] = brief_data.get('BulletPoints', [])
                
                # Save summary to storage
                FileStorage.save_summary(summary, topic)
                
                # Upload to Firestore if available
                if self.db:
                    FirebaseStorage.upload_to_firestore(summary, topic)
                
                summaries[topic] = summary
        
        return summaries

    def _fetch_and_integrate_sports_data(self, summaries: dict):
        """
        Fetches structured sports data (leagues, games) and integrates it
        into the 'SPORTS' summary.
        This method is called after the initial summaries are generated.
        """
        if 'SPORTS' not in RSS_FEEDS:  # Check if SPORTS topic is configured
            print("SPORTS topic not configured in RSS_FEEDS, skipping structured sports data fetch.")
            return

        print("\nFetching and integrating structured sports data for SPORTS topic...")
        popular_sports = ['Soccer', 'Basketball', 'Baseball', 'American Football', 'Ice Hockey']
        # Use the structure: {"leagues": [{"id": ..., "name": ..., "sport": ..., "games": [...]}]}
        processed_leagues_with_games = []

        for sport_name in popular_sports:
            try:
                leagues_from_api = self.sports_fetcher.get_leagues_by_sport(sport_name)
                if not leagues_from_api:
                    # print(f"No leagues found for sport: {sport_name}")
                    continue

                for league_data in leagues_from_api:
                    league_id = league_data.get('idLeague')
                    league_name = league_data.get('strLeague')
                    # Ensure basic league info is present
                    if not (league_id and league_name):
                        # print(f"Skipping league due to missing ID or name: {league_data.get('strLeagueAlternate', 'Unknown league in sport ' + sport_name)}")
                        continue
                    
                    current_sport_for_league = league_data.get('strSport', sport_name)
                    league_games = []
                    try:
                        # Using a common recent/current season, adjust if dynamic season is available
                        season_to_fetch = league_data.get('strCurrentSeason', "2024") 
                        games_from_api = self.sports_fetcher.get_upcoming_games_by_league_id(league_id, season=season_to_fetch)
                        if games_from_api:
                            for game_data in games_from_api:
                                if game_data and game_data.get('idEvent'):
                                    game_info = {
                                        "id": game_data.get('idEvent'),
                                        # league_id is already part of the parent league_info
                                        "home_team": game_data.get('strHomeTeam'),
                                        "away_team": game_data.get('strAwayTeam'),
                                        "date": game_data.get('dateEvent'),
                                        "time": game_data.get('strTime', game_data.get('strTimestamp')), # strTimestamp as fallback
                                        "venue": game_data.get('strVenue'),
                                        "status": game_data.get('strStatus', game_data.get('strPostponed')), # strPostponed as fallback
                                        "round": game_data.get('intRound'),
                                        "season": game_data.get('strSeason', season_to_fetch),
                                        "home_score": game_data.get('intHomeScore'),
                                        "away_score": game_data.get('intAwayScore'),
                                        "description": game_data.get('strDescriptionEN'), # Event description
                                        "spectators": game_data.get('intSpectators'),
                                        "tv_station": game_data.get('strTVStation'),
                                    }
                                    league_games.append(game_info)
                    except Exception as e_games:
                        print(f"Error fetching games for league {league_name} ({league_id}), sport {current_sport_for_league}: {e_games}")
                    
                    league_info_with_games = {
                        "id": league_id,
                        "name": league_name,
                        "sport": current_sport_for_league,
                        "country": league_data.get('strCountry'), # Optional: include country if available
                        "games": league_games
                    }
                    processed_leagues_with_games.append(league_info_with_games)

            except Exception as e_leagues:
                print(f"Error fetching leagues for sport {sport_name}: {e_leagues}")

        if not processed_leagues_with_games:
            print("No structured sports data (leagues/games) was fetched.")
            return

        structured_sports_data = {"leagues": processed_leagues_with_games}
        
        # Get the summary for 'SPORTS' if it was created by Gemini, or initialize a new one
        sports_summary = summaries.get('SPORTS') # Get existing summary, could be None
        
        if not sports_summary: # No RSS-based summary for SPORTS
            print("No existing RSS-based summary for SPORTS. Creating a new summary for structured data.")
            sports_summary = {
                'topic': 'SPORTS',
                'title': f"Sports Update - {datetime.now().strftime('%Y-%m-%d %H:%M')}", # Informative title
                'Summary': f"Structured sports data including {len(processed_leagues_with_games)} leagues.", # Basic summary
                'Stories': [], # No article-based stories
                'published_at': datetime.now().isoformat(), # Timestamp
                'source_type': 'structured_api' # Indicate origin
            }
        else:
            print("Augmenting existing SPORTS summary with structured data.")
            # If summary exists, ensure its source_type reflects mixed content if applicable
            if 'source_type' in sports_summary:
                 sports_summary['source_type'] = f"{sports_summary['source_type']}_plus_structured_api"
            else:
                 sports_summary['source_type'] = 'rss_plus_structured_api'


        # Add/update the structured data
        sports_summary['structured_sports_data'] = structured_sports_data
        
        # Update the summaries dictionary (in case it was newly created)
        summaries['SPORTS'] = sports_summary
        
        # Persist this updated/new sports summary
        # This ensures that if SPORTS summary was already processed and saved by the main loop,
        # it gets updated with the structured data. If it's new, it gets saved here.
        print(f"Saving updated/new summary for SPORTS (topic: {sports_summary.get('topic')}) with structured data...")
        FileStorage.save_summary(sports_summary, 'SPORTS') # Use 'SPORTS' as topic for filename
        if self.db:
            # Ensure topic is correctly passed for Firestore path
            FirebaseStorage.upload_to_firestore(sports_summary, 'SPORTS')
        print("Structured sports data integration for SPORTS complete.")


    def generate_summaries(self):
        """Generate summaries for each topic.
        
        Returns:
            Dictionary of summaries by topic
        """
        print("\nGenerating news summaries...")
        summaries = {}
        
        for topic in RSS_FEEDS.keys():
            print(f"\nProcessing {topic}...")
            
            # Get the combined file path for this topic
            combined_file = Path(COMBINED_DIR) / FileStorage.get_combined_filename(topic)
            
            if not combined_file.exists():
                print(f"No combined file found for topic: {topic}")
                # If topic is SPORTS and no combined file, sports_fetcher will create the summary later
                if topic == 'SPORTS':
                    summaries['SPORTS'] = None # Placeholder to indicate SPORTS is a target
                continue
                
            # Read the combined file content
            with open(combined_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Generate summary using Gemini
            summary = self.gemini_processor.generate_summary(content, topic)
            
            if summary:
                # Add detailed content to each story
                summary = self.article_processor.process_for_summary(summary)
                
                # Generate brief summary
                brief_data = self.gemini_processor.generate_brief_summary(
                    summary.get('Summary', ''), topic
                )
                
                if brief_data:
                    summary['brief_summary'] = brief_data.get('BriefSummary', '')
                    summary['bullet_points'] = brief_data.get('BulletPoints', [])
                
                # Save summary to storage (This will be for RSS-based summary)
                FileStorage.save_summary(summary, topic)
                
                # Upload to Firestore if available
                if self.db:
                    FirebaseStorage.upload_to_firestore(summary, topic)
                
                summaries[topic] = summary
            elif topic == 'SPORTS': # Gemini failed for SPORTS or content was empty
                summaries['SPORTS'] = None # Ensure SPORTS is in summaries for sports_fetcher if Gemini fails

        # After processing all RSS-based summaries, fetch and integrate structured sports data
        self._fetch_and_integrate_sports_data(summaries)
        
        return summaries
    
    def run(self):
        """Run the news aggregation process as a single execution."""
        # Initialize
        print(f"Starting news aggregation process at {datetime.now()}")
        self.article_processor.load_state()
        
        try:
            # Process feeds for all topics
            new_articles_by_topic = self.process_feeds()
            
            # Log processed articles
            total_new_articles = sum(len(articles) for articles in new_articles_by_topic.values())
            print(f"\nAdded {total_new_articles} new articles across all topics")
            for topic, articles in new_articles_by_topic.items():
                if articles:
                    print(f"- {topic}: {len(articles)} articles")
            
            # Save processor state
            self.article_processor.save_state()
            
            # Generate summaries for each topic
            summaries = self.generate_summaries()
            FileStorage.save_last_summary_time(time.time())
            
            # Log summary generation
            print(f"\nGenerated summaries for {len(summaries)} topics")
            for topic in summaries.keys():
                print(f"- {topic}: Summary generated")
                
            print(f"\nNews aggregation process completed at {datetime.now()}")
            
        except Exception as e:
            print(f"Error during news aggregation: {str(e)}")
            raise
            
        finally:
            print("\nSaving final state...")
            self.article_processor.save_state()
            print("Process complete") 