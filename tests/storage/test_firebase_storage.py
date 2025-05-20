import unittest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timezone

from newsaggregator.storage.firebase_storage import FirebaseStorage
# Assuming FIRESTORE_COLLECTION and FIRESTORE_ARTICLES_COLLECTION are used
from newsaggregator.config.settings import FIRESTORE_COLLECTION, FIRESTORE_ARTICLES_COLLECTION

class TestFirebaseStorage(unittest.TestCase):

    def setUp(self):
        # Mock Firebase Admin SDK and Firestore client
        # Patch initialize to prevent actual Firebase connection and control the db client
        self.mock_db_client = MagicMock()
        
        self.firebase_initialize_patch = patch('newsaggregator.storage.firebase_storage.firebase_admin.initialize_app')
        self.mock_firebase_initialize_app = self.firebase_initialize_patch.start()

        # Patch firestore.client() to return our mock_db_client
        self.firestore_client_patch = patch('newsaggregator.storage.firebase_storage.firestore.client')
        self.mock_firestore_client_func = self.firestore_client_patch.start()
        self.mock_firestore_client_func.return_value = self.mock_db_client
        
        # Ensure FirebaseStorage uses the mocked client by re-initializing or patching get_db
        # If FirebaseStorage.initialize() was already called by other modules,
        # we need to ensure its _db is our mock.
        # A direct way:
        FirebaseStorage._db = self.mock_db_client
        FirebaseStorage._initialized = True # Mark as initialized to use the mock _db

        # Mock specific client behaviors needed for upload_to_firestore
        self.mock_collection_ref = MagicMock()
        self.mock_db_client.collection.return_value = self.mock_collection_ref
        
        # Mock the document reference and its methods if needed for summary_ref
        self.mock_summary_doc_ref = MagicMock()
        self.mock_summary_doc_ref.id = "test_summary_doc_id" # For summary_ref[1] if it's a tuple
        
        # .add() usually returns a tuple (timestamp, DocumentReference) or just DocumentReference
        # Let's assume it returns a DocumentReference like object that has an id.
        # Or if it's a tuple (timestamp, ref), we need to mock that.
        # The code uses `summary_ref[1]` which suggests it's a tuple.
        # Let's mock .add() to return a tuple: (timestamp, mock_document_reference)
        mock_timestamp = datetime.now(timezone.utc)
        self.mock_collection_ref.add.return_value = (mock_timestamp, self.mock_summary_doc_ref)

        # Mock messaging for FCM notifications
        self.fcm_send_patch = patch('newsaggregator.storage.firebase_storage.messaging.send')
        self.mock_fcm_send = self.fcm_send_patch.start()
        self.mock_fcm_send.return_value = MagicMock(message_id="test_fcm_id")


    def tearDown(self):
        self.firebase_initialize_patch.stop()
        self.firestore_client_patch.stop()
        self.fcm_send_patch.stop()
        # Reset FirebaseStorage internal state if necessary
        FirebaseStorage._db = None
        FirebaseStorage._initialized = False

    def test_upload_to_firestore_with_structured_sports_data(self):
        topic = "SPORTS"
        summary_data = {
            "Summary": "Sports summary text",
            "Stories": [
                {"StoryTitle": "Game 1", "StoryDescription": "Recap of game 1", "FullArticle": "...", "Citations": [], "img_url": ""}
            ],
            "brief_summary": "Brief sports news",
            "bullet_points": ["Point 1", "Point 2"],
            "structured_sports_data": {
                "leagues": [{"id": "L1", "name": "League One", "games": []}],
                "games": [] # Assuming the structure in aggregator was {"leagues": [...]} without top-level "games"
                           # The FirebaseStorage just saves whatever is under 'structured_sports_data'
            }
        }
        
        # Expected document structure for the summary
        expected_summary_doc = {
            'summary': summary_data['Summary'],
            'topic': topic,
            'timestamp': ANY, # datetime.now(timezone.utc)
            'created_at': ANY, # firestore.SERVER_TIMESTAMP
            'brief_summary': summary_data['brief_summary'],
            'brief_updated_at': ANY,
            'bullet_points': summary_data['bullet_points'],
            'structured_sports_data': summary_data['structured_sports_data'] # This is key
        }

        success = FirebaseStorage.upload_to_firestore(summary_data, topic)
        self.assertTrue(success)

        # Verify summary document upload
        self.mock_db_client.collection.assert_any_call(FIRESTORE_COLLECTION)
        # The first argument to 'add' will be the summary_doc
        # Check that the first positional argument to 'add' matches our expected_summary_doc
        # This depends on how many times .collection().add() is called.
        # The first call to .add() on FIRESTORE_COLLECTION should be the summary.
        
        summary_add_call = None
        for call_args in self.mock_collection_ref.add.call_args_list:
            # Check if the document being added has 'summary' and 'topic' keys, typical of summary_doc
            # This is a heuristic if multiple .add calls happen on the same mock_collection_ref instance
            # from different collection names but we only mocked one.
            # Better: ensure different mock_collection_ref for different collection names.
            # For now, let's assume the first .add() to the FIRESTORE_COLLECTION is the summary.
            
            # Check based on the collection name used for the call
            # The mock_collection_ref is returned by mock_db_client.collection(FIRESTORE_COLLECTION)
            # and mock_db_client.collection(FIRESTORE_ARTICLES_COLLECTION)
            # We need to distinguish. Let's refine setup.

            # For simplicity, let's assume first add to FIRESTORE_COLLECTION is the summary.
            # This requires collection name to be passed to .add or verifying via .collection call.
            # The current mock setup is a bit too simple.

            # Let's check the arguments of the call that added the summary.
            # The summary_doc is the first positional argument to .add().
            # We expect summary_doc to contain 'structured_sports_data'.
            
            # Correct approach: Set up side_effect for db.collection
            mock_summary_collection_ref = MagicMock()
            mock_articles_collection_ref = MagicMock()
            def collection_side_effect(name):
                if name == FIRESTORE_COLLECTION: return mock_summary_collection_ref
                if name == FIRESTORE_ARTICLES_COLLECTION: return mock_articles_collection_ref
                return MagicMock() # Default mock for other collections
            self.mock_db_client.collection.side_effect = collection_side_effect
            
            # Mock .add for summary collection
            mock_summary_collection_ref.add.return_value = (datetime.now(timezone.utc), MagicMock(id="summary_id"))


            FirebaseStorage.upload_to_firestore(summary_data, topic) # Call again with refined mocks

            mock_summary_collection_ref.add.assert_called_once()
            called_summary_doc = mock_summary_collection_ref.add.call_args[0][0]
            
            self.assertEqual(called_summary_doc['summary'], expected_summary_doc['summary'])
            self.assertEqual(called_summary_doc['topic'], expected_summary_doc['topic'])
            self.assertIn('structured_sports_data', called_summary_doc)
            self.assertEqual(called_summary_doc['structured_sports_data'], summary_data['structured_sports_data'])
            self.assertIn('brief_summary', called_summary_doc)
            self.assertIn('bullet_points', called_summary_doc)


    def test_upload_to_firestore_without_structured_sports_data(self):
        topic = "BUSINESS" # A non-sports topic
        summary_data = {
            "Summary": "Business summary text",
            "Stories": [{"StoryTitle": "Market News", "StoryDescription": "Market is up."}],
            "brief_summary": "Brief business news",
            "bullet_points": ["Point A"]
        }
        
        expected_summary_doc = {
            'summary': summary_data['Summary'],
            'topic': topic,
            'timestamp': ANY,
            'created_at': ANY,
            'brief_summary': summary_data['brief_summary'],
            'brief_updated_at': ANY,
            'bullet_points': summary_data['bullet_points']
            # 'structured_sports_data' should NOT be here
        }

        # Setup side_effect for db.collection for this test too
        mock_summary_collection_ref = MagicMock()
        mock_articles_collection_ref = MagicMock()
        def collection_side_effect(name):
            if name == FIRESTORE_COLLECTION: return mock_summary_collection_ref
            if name == FIRESTORE_ARTICLES_COLLECTION: return mock_articles_collection_ref
            return MagicMock()
        self.mock_db_client.collection.side_effect = collection_side_effect
        mock_summary_collection_ref.add.return_value = (datetime.now(timezone.utc), MagicMock(id="summary_id_biz"))


        success = FirebaseStorage.upload_to_firestore(summary_data, topic)
        self.assertTrue(success)

        mock_summary_collection_ref.add.assert_called_once()
        called_summary_doc = mock_summary_collection_ref.add.call_args[0][0]

        self.assertEqual(called_summary_doc['summary'], expected_summary_doc['summary'])
        self.assertEqual(called_summary_doc['topic'], expected_summary_doc['topic'])
        self.assertNotIn('structured_sports_data', called_summary_doc) # Key check
        self.assertIn('brief_summary', called_summary_doc)

    def test_upload_to_firestore_sports_topic_no_structured_data_field(self):
        # Test for SPORTS topic but the structured_sports_data field is missing from input
        topic = "SPORTS"
        summary_data = { # structured_sports_data key is absent
            "Summary": "Sports summary text - no structured data provided",
            "Stories": [{"StoryTitle": "Old Game", "StoryDescription": "Recap of old game."}],
            "brief_summary": "Brief sports news",
        }
        
        expected_summary_doc = {
            'summary': summary_data['Summary'],
            'topic': topic,
            'timestamp': ANY,
            'created_at': ANY,
            'brief_summary': summary_data['brief_summary'],
            'brief_updated_at': ANY,
            # 'bullet_points' might be missing if not in summary_data, that's fine
            # 'structured_sports_data' should NOT be here
        }

        mock_summary_collection_ref = MagicMock()
        mock_articles_collection_ref = MagicMock()
        def collection_side_effect(name):
            if name == FIRESTORE_COLLECTION: return mock_summary_collection_ref
            if name == FIRESTORE_ARTICLES_COLLECTION: return mock_articles_collection_ref
            return MagicMock()
        self.mock_db_client.collection.side_effect = collection_side_effect
        mock_summary_collection_ref.add.return_value = (datetime.now(timezone.utc), MagicMock(id="summary_id_sports_no_struct"))

        success = FirebaseStorage.upload_to_firestore(summary_data, topic)
        self.assertTrue(success)
        
        mock_summary_collection_ref.add.assert_called_once()
        called_summary_doc = mock_summary_collection_ref.add.call_args[0][0]

        self.assertNotIn('structured_sports_data', called_summary_doc)
        self.assertEqual(called_summary_doc['summary'], expected_summary_doc['summary'])

    def test_upload_to_firestore_db_failure(self):
        # Test when Firestore client is not initialized or fails
        FirebaseStorage._db = None # Simulate DB not available
        FirebaseStorage._initialized = False 
        
        summary_data = {"Summary": "Test", "Stories": []}
        success = FirebaseStorage.upload_to_firestore(summary_data, "ANYTOPIC")
        self.assertFalse(success)

        # Restore for other tests
        FirebaseStorage._db = self.mock_db_client
        FirebaseStorage._initialized = True

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
