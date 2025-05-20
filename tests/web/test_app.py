import unittest
from unittest.mock import patch, MagicMock, ANY
from flask import Flask

# Assuming app and FirebaseStorage are in these locations
from newsaggregator.web.app import app as flask_app # Import your Flask app instance
from newsaggregator.storage.firebase_storage import FirebaseStorage
from newsaggregator.config.settings import FIRESTORE_COLLECTION, FIRESTORE_ARTICLES_COLLECTION, RSS_FEEDS

# Example structured sports data for mocking
MOCK_STRUCTURED_SPORTS_DATA = {
    "leagues": [
        {"id": "L1", "name": "Premier League", "sport": "Soccer", "country": "England", 
         "games": [{"id": "G1", "home_team": "Arsenal", "away_team": "Chelsea", "date": "2024-08-17"}]}
    ]
}

class TestWebApp(unittest.TestCase):

    def setUp(self):
        flask_app.testing = True
        self.client = flask_app.test_client()

        # Mock FirebaseStorage.get_db() and Firestore client methods
        self.mock_db_client = MagicMock()
        
        # Patch FirebaseStorage.initialize() to prevent actual Firebase connection
        # and ensure get_db() can be controlled.
        self.firebase_initialize_patch = patch('newsaggregator.storage.firebase_storage.FirebaseStorage.initialize')
        self.mock_firebase_initialize = self.firebase_initialize_patch.start()
        self.mock_firebase_initialize.return_value = self.mock_db_client # Ensure initialize returns the mock client

        # Patch FirebaseStorage.get_db() to consistently return our mock_db_client
        self.get_db_patch = patch('newsaggregator.storage.firebase_storage.FirebaseStorage.get_db')
        self.mock_get_db = self.get_db_patch.start()
        self.mock_get_db.return_value = self.mock_db_client
        
        # Mock collection references and stream() for article fetching (generic for all topics)
        self.mock_articles_collection_ref = MagicMock()
        self.mock_articles_stream = MagicMock()
        self.mock_articles_stream.return_value = [] # Default: no articles
        self.mock_articles_collection_ref.order_by.return_value.limit.return_value.stream = self.mock_articles_stream
        
        # Mock collection references and stream() for summary fetching (for SPORTS topic)
        self.mock_summary_collection_ref = MagicMock()
        self.mock_summary_stream = MagicMock()
        self.mock_summary_stream.return_value = [] # Default: no summary
        self.mock_summary_collection_ref.where.return_value.order_by.return_value.limit.return_value.stream = self.mock_summary_stream

        # Set up side_effect for db.collection calls
        def collection_side_effect(name):
            if name == FIRESTORE_ARTICLES_COLLECTION:
                return self.mock_articles_collection_ref
            elif name == FIRESTORE_COLLECTION: # This is 'news_summaries'
                return self.mock_summary_collection_ref
            return MagicMock()
        self.mock_db_client.collection.side_effect = collection_side_effect

        # Patch get_topics to ensure 'SPORTS' is available
        self.get_topics_patch = patch('newsaggregator.web.app.get_topics')
        self.mock_get_topics = self.get_topics_patch.start()
        self.mock_get_topics.return_value = sorted(list(RSS_FEEDS.keys()) + ['SPORTS', 'NATION'])


    def tearDown(self):
        self.firebase_initialize_patch.stop()
        self.get_db_patch.stop()
        self.get_topics_patch.stop()

    def test_index_route_generic_topic(self):
        # Test a non-SPORTS topic
        # Simulate some articles being returned
        mock_article_doc = MagicMock()
        mock_article_doc.id = "article1"
        mock_article_doc.to_dict.return_value = {"title": "Business News", "topic": "BUSINESS", "timestamp": MagicMock()}
        self.mock_articles_stream.return_value = [mock_article_doc]

        response = self.client.get('/?topic=BUSINESS')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Business News', response.data)
        self.assertNotIn(b'Leagues and Schedules', response.data) # Sports specific section

        # Verify summary collection was not queried for structured data for BUSINESS topic
        # Check that where('topic', '==', 'SPORTS') was not called on summary collection
        # This is tricky because the mock_summary_collection_ref is set up for SPORTS.
        # The logic in app.py only queries summary collection if topic_filter == 'SPORTS'.
        # So, if topic is BUSINESS, the specific query for SPORTS summary shouldn't happen.
        
        # We can check calls to mock_summary_collection_ref.where specifically.
        # If it was called, it means the app tried to fetch a summary.
        # For a non-SPORTS topic, it shouldn't try to fetch the SPORTS summary.
        
        # Let's refine: check if the summary query for SPORTS was made.
        # The query is db.collection(FIRESTORE_COLLECTION).where('topic', '==', 'SPORTS')...
        # We can check if self.mock_summary_collection_ref.where was called with ('topic', '==', 'SPORTS')
        
        sports_summary_query_made = False
        for call_item in self.mock_summary_collection_ref.where.call_args_list:
            args, _ = call_item
            if args == (('topic', '==', 'SPORTS'),):
                sports_summary_query_made = True
                break
        self.assertFalse(sports_summary_query_made, "SPORTS summary query should not be made for BUSINESS topic")


    def test_index_route_sports_topic_with_structured_data(self):
        # Simulate 'SPORTS' summary with structured_sports_data
        mock_sports_summary_doc = MagicMock()
        mock_sports_summary_doc.to_dict.return_value = {
            "topic": "SPORTS",
            "timestamp": MagicMock(),
            "structured_sports_data": MOCK_STRUCTURED_SPORTS_DATA
        }
        self.mock_summary_stream.return_value = [mock_sports_summary_doc] # Return this summary

        # Simulate some sports articles too
        mock_article_doc = MagicMock()
        mock_article_doc.id = "sports_article1"
        mock_article_doc.to_dict.return_value = {"title": "Sports Article", "topic": "SPORTS", "timestamp": MagicMock()}
        self.mock_articles_stream.return_value = [mock_article_doc]

        response = self.client.get('/?topic=SPORTS')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sports Article', response.data) # Regular article
        self.assertIn(b'Leagues and Schedules', response.data) # Sports specific section
        self.assertIn(b'Premier League', response.data) # From MOCK_STRUCTURED_SPORTS_DATA
        self.assertIn(b'Arsenal vs Chelsea', response.data)

        # Verify that the summary collection was queried for SPORTS
        self.mock_summary_collection_ref.where.assert_called_with('topic', '==', 'SPORTS')


    def test_index_route_sports_topic_without_structured_data(self):
        # Simulate 'SPORTS' summary but *without* structured_sports_data field
        mock_sports_summary_doc = MagicMock()
        mock_sports_summary_doc.to_dict.return_value = {
            "topic": "SPORTS", "timestamp": MagicMock() 
            # No 'structured_sports_data' key
        }
        self.mock_summary_stream.return_value = [mock_sports_summary_doc]

        response = self.client.get('/?topic=SPORTS')
        self.assertEqual(response.status_code, 200)
        # Should not display the "Leagues and Schedules" title if data is missing,
        # but the template might have a fallback message.
        # The template has:
        # {% elif active_topic == 'SPORTS' and structured_sports_data and not structured_sports_data.leagues %}
        # <div class="alert alert-info">No specific league and schedule data available...</div>
        # This case is when structured_sports_data exists but structured_sports_data.leagues is false/empty.
        # If structured_sports_data itself is None (as passed from app.py if key missing),
        # then the whole `if active_topic == 'SPORTS' and structured_sports_data` block is skipped.
        # So, "Leagues and Schedules" H2 should not be present.
        self.assertNotIn(b'Leagues and Schedules', response.data)
        self.assertNotIn(b'Premier League', response.data)
        # Check for the absence of the specific alert for "no league data" because structured_sports_data is None
        self.assertNotIn(b'No specific league and schedule data available', response.data)


    def test_index_route_sports_topic_structured_data_empty_leagues(self):
        # Simulate 'SPORTS' summary with structured_sports_data, but leagues list is empty
        mock_sports_summary_doc = MagicMock()
        empty_leagues_data = {"leagues": []}
        mock_sports_summary_doc.to_dict.return_value = {
            "topic": "SPORTS", "timestamp": MagicMock(),
            "structured_sports_data": empty_leagues_data
        }
        self.mock_summary_stream.return_value = [mock_sports_summary_doc]

        response = self.client.get('/?topic=SPORTS')
        self.assertEqual(response.status_code, 200)
        # The H2 "Leagues and Schedules" should be present because structured_sports_data is passed.
        self.assertIn(b'Leagues and Schedules', response.data)
        # Then, the template condition `{% elif active_topic == 'SPORTS' and structured_sports_data and not structured_sports_data.leagues %}`
        # This isn't quite right. The outer if is `... and structured_sports_data.leagues %}`.
        # If `leagues` is empty, this condition is false.
        # The template code is:
        # {% if active_topic == 'SPORTS' and structured_sports_data and structured_sports_data.leagues %} -> accordion
        # {% elif active_topic == 'SPORTS' and structured_sports_data and not structured_sports_data.leagues %} -> alert
        # So, if structured_sports_data = {"leagues": []}, the second `elif` should be hit.
        self.assertIn(b'No specific league and schedule data available', response.data)
        self.assertNotIn(b'Premier League', response.data) # No league names should be rendered


    def test_index_route_no_sports_summary_found(self):
        # Simulate no summary document found for SPORTS in Firestore
        self.mock_summary_stream.return_value = [] # Empty stream

        response = self.client.get('/?topic=SPORTS')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'Leagues and Schedules', response.data)
        self.assertNotIn(b'Premier League', response.data)

    def test_get_db_failure_graceful_handling(self):
        # Test graceful failure if Firestore connection fails
        self.mock_get_db.return_value = None # Simulate DB connection failure

        response = self.client.get('/?topic=SPORTS')
        self.assertEqual(response.status_code, 200) # App should still render
        self.assertIn(b'Could not connect to Firestore', response.data) # Flash message
        self.assertNotIn(b'Leagues and Schedules', response.data) # No data fetched


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
