import unittest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import time

# Assuming NewsAggregator, RSS_FEEDS, SPORTS_API_KEY are in these locations
from newsaggregator.core.aggregator import NewsAggregator
from newsaggregator.config.settings import RSS_FEEDS, SPORTS_API_KEY, COMBINED_DIR, FIRESTORE_COLLECTION
from newsaggregator.fetchers.sports_fetcher import SportsFetcher # For type hinting if needed

# Mock initial RSS_FEEDS for consistent testing
# Add SPORTS if not already there, or use a controlled set.
TEST_RSS_FEEDS = {
    'TOP_NEWS': 'http://example.com/rss/top',
    'SPORTS': 'http://example.com/rss/sports', # Ensure SPORTS is present
    'BUSINESS': 'http://example.com/rss/business'
}

class TestNewsAggregator(unittest.TestCase):

    def setUp(self):
        # Patch external dependencies for NewsAggregator
        # Patch settings if they are dynamically loaded or critical for init
        self.settings_patch = patch.dict('newsaggregator.config.settings.RSS_FEEDS', TEST_RSS_FEEDS)
        self.settings_patch.start()

        # Patch FirebaseStorage initialization and methods
        self.firebase_initialize_patch = patch('newsaggregator.storage.firebase_storage.FirebaseStorage.initialize')
        self.mock_firebase_initialize = self.firebase_initialize_patch.start()
        self.mock_db_client = MagicMock()
        self.mock_firebase_initialize.return_value = self.mock_db_client

        self.firebase_upload_patch = patch('newsaggregator.storage.firebase_storage.FirebaseStorage.upload_to_firestore')
        self.mock_firebase_upload = self.firebase_upload_patch.start()

        # Patch FileStorage methods
        self.file_storage_save_summary_patch = patch('newsaggregator.storage.file_storage.FileStorage.save_summary')
        self.mock_file_storage_save_summary = self.file_storage_save_summary_patch.start()
        
        self.file_storage_save_last_time_patch = patch('newsaggregator.storage.file_storage.FileStorage.save_last_summary_time')
        self.mock_file_storage_save_last_time = self.file_storage_save_last_time_patch.start()

        # Patch Path.exists for combined_file checks if necessary
        self.path_exists_patch = patch('pathlib.Path.exists')
        self.mock_path_exists = self.path_exists_patch.start()
        self.mock_path_exists.return_value = True # Assume combined files exist

        # Patch open for reading combined_file
        self.open_patch = patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='Mocked article content')
        self.mock_open = self.open_patch.start()

        # Mock processors and fetchers used by NewsAggregator
        self.rss_fetcher_patch = patch('newsaggregator.core.aggregator.RSSFetcher')
        self.mock_rss_fetcher_type = self.rss_fetcher_patch.start()
        self.mock_rss_fetcher_instance = self.mock_rss_fetcher_type.return_value
        self.mock_rss_fetcher_instance.fetch_feed.return_value = {"entries": []} # Default empty feed

        self.article_processor_patch = patch('newsaggregator.core.aggregator.ArticleProcessor')
        self.mock_article_processor_type = self.article_processor_patch.start()
        self.mock_article_processor_instance = self.mock_article_processor_type.return_value
        self.mock_article_processor_instance.process_for_summary.side_effect = lambda x: x # Pass through

        self.gemini_processor_patch = patch('newsaggregator.core.aggregator.GeminiProcessor')
        self.mock_gemini_processor_type = self.gemini_processor_patch.start()
        self.mock_gemini_processor_instance = self.mock_gemini_processor_type.return_value
        # Default mock for generate_summary for any topic
        self.mock_gemini_processor_instance.generate_summary.side_effect = \
            lambda content, topic: {"topic": topic, "Summary": f"Summary for {topic}", "Stories": []}
        self.mock_gemini_processor_instance.generate_brief_summary.return_value = \
            {"BriefSummary": "Brief summary", "BulletPoints": ["bp1"]}


        # Mock SportsFetcher specifically for its integration
        # This mock will be used by the NewsAggregator instance
        self.sports_fetcher_patch = patch('newsaggregator.core.aggregator.SportsFetcher')
        self.mock_sports_fetcher_type = self.sports_fetcher_patch.start()
        self.mock_sports_fetcher_instance = self.mock_sports_fetcher_type.return_value
        
        # Instantiate NewsAggregator - this will use the mocked SportsFetcher type
        self.aggregator = NewsAggregator()
        # Ensure the instance of SportsFetcher used by aggregator is our mock
        self.mock_aggregator_sports_fetcher = self.aggregator.sports_fetcher


    def tearDown(self):
        self.settings_patch.stop()
        self.firebase_initialize_patch.stop()
        self.firebase_upload_patch.stop()
        self.file_storage_save_summary_patch.stop()
        self.file_storage_save_last_time_patch.stop()
        self.path_exists_patch.stop()
        self.open_patch.stop()
        self.rss_fetcher_patch.stop()
        self.article_processor_patch.stop()
        self.gemini_processor_patch.stop()
        self.sports_fetcher_patch.stop()

    def test_fetch_and_integrate_sports_data_success(self):
        # Mock SportsFetcher methods' return values
        mock_leagues = [
            {"idLeague": "123", "strLeague": "Mock League 1", "strSport": "Soccer", "strCurrentSeason": "2024"},
            {"idLeague": "456", "strLeague": "Mock League 2", "strSport": "Basketball", "strCurrentSeason": "2024"}
        ]
        mock_games_league1 = [
            {"idEvent": "g1", "strHomeTeam": "Team A", "strAwayTeam": "Team B", "dateEvent": "2024-01-01"},
        ]
        mock_games_league2 = [] # No games for league 2

        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.side_effect = [
            [mock_leagues[0]] if sport == "Soccer" else [mock_leagues[1]] if sport == "Basketball" else []
            for sport in ['Soccer', 'Basketball', 'Baseball', 'American Football', 'Ice Hockey'] # Order matters for side_effect
        ]
        
        # More robust side_effect for get_leagues_by_sport
        def mock_get_leagues(sport_name):
            if sport_name == "Soccer": return [{"idLeague": "123", "strLeague": "Mock League Soccer", "strSport": "Soccer", "strCurrentSeason": "2024"}]
            if sport_name == "Basketball": return [{"idLeague": "456", "strLeague": "Mock League Basketball", "strSport": "Basketball", "strCurrentSeason": "2024"}]
            return []
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.side_effect = mock_get_leagues


        self.mock_aggregator_sports_fetcher.get_upcoming_games_by_league_id.side_effect = \
            lambda league_id, season: mock_games_league1 if league_id == "123" else mock_games_league2

        # Simulate that Gemini processor created a summary for SPORTS from RSS
        initial_summaries = {
            "SPORTS": {"topic": "SPORTS", "Summary": "RSS Sports Summary", "Stories": [{"StoryTitle": "RSS Story"}]}
        }

        # Call the method that includes sports data integration
        # In NewsAggregator, _fetch_and_integrate_sports_data is called at the end of generate_summaries
        # So we test generate_summaries.
        
        # Setup Gemini to return a specific summary for SPORTS
        self.mock_gemini_processor_instance.generate_summary.side_effect = \
            lambda content, topic: {"topic": topic, "Summary": f"Summary for {topic}", "Stories": [{"StoryTitle": f"RSS Story for {topic}"}]} \
                                   if topic == "SPORTS" else \
                                   {"topic": topic, "Summary": f"Summary for {topic}", "Stories": []}


        returned_summaries = self.aggregator.generate_summaries()

        # Verify SportsFetcher methods were called (at least for some sports)
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.assert_any_call("Soccer")
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.assert_any_call("Basketball")
        self.mock_aggregator_sports_fetcher.get_upcoming_games_by_league_id.assert_any_call("123", season="2024")
        self.mock_aggregator_sports_fetcher.get_upcoming_games_by_league_id.assert_any_call("456", season="2024")

        # Verify the structure of sports data in the summary
        self.assertIn("SPORTS", returned_summaries)
        sports_summary = returned_summaries["SPORTS"]
        self.assertIn("structured_sports_data", sports_summary)
        structured_data = sports_summary["structured_sports_data"]
        
        self.assertEqual(len(structured_data["leagues"]), 2)
        self.assertEqual(structured_data["leagues"][0]["name"], "Mock League Soccer")
        self.assertEqual(len(structured_data["leagues"][0]["games"]), 1)
        self.assertEqual(structured_data["leagues"][0]["games"][0]["id"], "g1")
        self.assertEqual(structured_data["leagues"][1]["name"], "Mock League Basketball")
        self.assertEqual(len(structured_data["leagues"][1]["games"]), 0)

        # Verify that the original RSS summary content is still there
        self.assertEqual(sports_summary["Summary"], "Summary for SPORTS")
        self.assertTrue(any(s['StoryTitle'] == "RSS Story for SPORTS" for s in sports_summary['Stories']))
        
        # Verify it was saved (FileStorage and Firebase)
        # Check that the sports_summary (which now includes structured_sports_data) was passed to save functions
        # The FileStorage.save_summary is called twice for SPORTS: once in main loop, once in _fetch_and_integrate
        # The FirebaseStorage.upload_to_firestore is also called twice.
        # We need to check the content of the *last* call for SPORTS topic.

        # Get all calls to save_summary and filter for SPORTS
        save_calls = [c for c in self.mock_file_storage_save_summary.call_args_list if c[0][1] == 'SPORTS']
        self.assertTrue(len(save_calls) >= 1) # Could be 1 or 2 depending on logic for new vs existing
        final_save_call_args = save_calls[-1][0][0] # Get the summary_data from the last call for SPORTS
        self.assertIn("structured_sports_data", final_save_call_args)
        self.assertEqual(len(final_save_call_args["structured_sports_data"]["leagues"]), 2)

        upload_calls = [c for c in self.mock_firebase_upload.call_args_list if c[0][1] == 'SPORTS']
        self.assertTrue(len(upload_calls) >= 1)
        final_upload_call_args = upload_calls[-1][0][0]
        self.assertIn("structured_sports_data", final_upload_call_args)


    def test_fetch_and_integrate_sports_data_no_rss_summary(self):
        # Test when there's no RSS summary for SPORTS, so a new summary should be created
        self.mock_gemini_processor_instance.generate_summary.side_effect = \
            lambda content, topic: None if topic == "SPORTS" else \
                                   {"topic": topic, "Summary": f"Summary for {topic}", "Stories": []}
        
        # Mock SportsFetcher to return some data
        mock_leagues = [{"idLeague": "789", "strLeague": "Hockey League", "strSport": "Ice Hockey", "strCurrentSeason": "2024"}]
        mock_games = [{"idEvent": "g2", "strHomeTeam": "Team C", "strAwayTeam": "Team D"}]
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.return_value = mock_leagues
        self.mock_aggregator_sports_fetcher.get_upcoming_games_by_league_id.return_value = mock_games
        
        # Assume combined file for SPORTS doesn't exist, so Gemini part is skipped for SPORTS
        def path_exists_side_effect(path_obj):
            if FileStorage.get_combined_filename("SPORTS") in str(path_obj):
                return False
            return True
        self.mock_path_exists.side_effect = path_exists_side_effect

        returned_summaries = self.aggregator.generate_summaries()

        self.assertIn("SPORTS", returned_summaries)
        sports_summary = returned_summaries["SPORTS"]
        self.assertIn("structured_sports_data", sports_summary)
        self.assertEqual(len(sports_summary["structured_sports_data"]["leagues"]), 1)
        self.assertEqual(sports_summary["structured_sports_data"]["leagues"][0]["name"], "Hockey League")
        self.assertTrue("Structured sports data including 1 leagues" in sports_summary["Summary"])
        self.assertEqual(sports_summary["topic"], "SPORTS")
        self.assertEqual(sports_summary.get("source_type"), "structured_api")


    def test_fetch_and_integrate_sports_data_fetcher_error(self):
        # Test when SportsFetcher's methods raise an error
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.side_effect = Exception("API Network Error")
        
        # Gemini produces a summary for SPORTS from RSS
        self.mock_gemini_processor_instance.generate_summary.side_effect = \
            lambda content, topic: {"topic": topic, "Summary": f"RSS Summary for {topic}", "Stories": []} \
                                   if topic == "SPORTS" else \
                                   {"topic": topic, "Summary": f"Summary for {topic}", "Stories": []}


        returned_summaries = self.aggregator.generate_summaries()

        self.assertIn("SPORTS", returned_summaries)
        sports_summary = returned_summaries["SPORTS"]
        # structured_sports_data should not be present, or be empty, if fetcher failed
        # The current implementation in aggregator's _fetch_and_integrate_sports_data:
        # if not processed_leagues_with_games: print("No structured sports data..."); return
        # So 'structured_sports_data' key might not be added if fetching fails completely before this key is set.
        # Or if it's set to {"leagues": []}
        
        # If an error occurs during fetching leagues for a sport, it's caught and printed.
        # The `processed_leagues_with_games` list would be empty.
        # Then `if not processed_leagues_with_games:` condition is met, and the method returns early.
        # So, the original sports_summary (from RSS) would be returned unmodified by this path.
        self.assertNotIn("structured_sports_data", sports_summary)
        self.assertEqual(sports_summary["Summary"], "RSS Summary for SPORTS")

    def test_fetch_and_integrate_sports_data_empty_from_fetcher(self):
        # Test when SportsFetcher returns empty lists (no leagues or games)
        self.mock_aggregator_sports_fetcher.get_leagues_by_sport.return_value = []
        self.mock_aggregator_sports_fetcher.get_upcoming_games_by_league_id.return_value = []

        self.mock_gemini_processor_instance.generate_summary.side_effect = \
            lambda content, topic: {"topic": topic, "Summary": f"RSS Summary for {topic}", "Stories": []} \
                                   if topic == "SPORTS" else \
                                   {"topic": topic, "Summary": f"Summary for {topic}", "Stories": []}

        returned_summaries = self.aggregator.generate_summaries()
        
        self.assertIn("SPORTS", returned_summaries)
        sports_summary = returned_summaries["SPORTS"]
        # As per the logic: if processed_leagues_with_games is empty, method returns early.
        self.assertNotIn("structured_sports_data", sports_summary) 
        self.assertEqual(sports_summary["Summary"], "RSS Summary for SPORTS")

    def test_sports_topic_not_in_rss_feeds(self):
        # Test behavior if SPORTS is not in RSS_FEEDS (though our test setup adds it)
        # We can achieve this by temporarily modifying TEST_RSS_FEEDS for this test
        original_rss_feeds = TEST_RSS_FEEDS.copy()
        no_sports_feeds = {k: v for k, v in original_rss_feeds.items() if k != "SPORTS"}
        
        with patch.dict('newsaggregator.config.settings.RSS_FEEDS', no_sports_feeds):
            # Re-initialize aggregator if RSS_FEEDS is used in its __init__ for topics
            # The current aggregator's _fetch_and_integrate_sports_data checks RSS_FEEDS directly.
            
            summaries = self.aggregator.generate_summaries() # Call the method
            
            # _fetch_and_integrate_sports_data should print and return early
            self.mock_aggregator_sports_fetcher.get_leagues_by_sport.assert_not_called()
            self.assertNotIn("SPORTS", summaries) # Or if it was in summaries from another source, it shouldn't have structured_data

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
