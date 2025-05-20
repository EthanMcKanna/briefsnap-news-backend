import unittest
from unittest.mock import patch, MagicMock
import requests # Import requests for requests.exceptions.RequestException

# Assuming SPORTS_API_KEY is needed for constructing the base URL in SportsFetcher
# If SportsFetcher gets it from settings, we might need to mock settings or ensure it's set for tests
from newsaggregator.config import settings
from newsaggregator.fetchers.sports_fetcher import SportsFetcher, THE_SPORTS_DB_API_URL

# Ensure a test API key is available for the fetcher, otherwise it might raise an error on init
# or when constructing the base URL if the settings.SPORTS_API_KEY is not set.
# For testing, we can override it, or ensure SportsFetcher is initialized with a dummy key.
TEST_API_KEY = "testkey123" 
settings.SPORTS_API_KEY = TEST_API_KEY # Override for test session if SportsFetcher uses it directly

# Update the module-level constant in sports_fetcher if it was defined using the settings key
# This is a bit tricky as the fetcher module might have already been loaded.
# A cleaner way is to ensure SportsFetcher instance uses a passed key or a mockable settings object.
# For now, let's assume SportsFetcher constructor takes api_key and uses it.
# The actual THE_SPORTS_DB_API_URL in sports_fetcher.py is f"https://www.thesportsdb.com/api/v1/json/{SPORTS_API_KEY}/"
# We need to ensure our mock URLs match this, or that the fetcher uses a predictable base URL for tests.

class TestSportsFetcher(unittest.TestCase):

    def setUp(self):
        # Initialize SportsFetcher with a test API key.
        # This ensures that even if the global settings.SPORTS_API_KEY is not "testkey123",
        # our fetcher instance uses a known key for constructing URLs.
        self.fetcher = SportsFetcher(api_key=TEST_API_KEY)
        # The base_url in the fetcher instance will be based on TEST_API_KEY
        self.expected_base_url = f"https://www.thesportsdb.com/api/v1/json/{TEST_API_KEY}/"

    @patch('requests.Session.get')
    def test_get_all_sports_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sports": [
                {"idSport": "101", "strSport": "Soccer", "strFormat": "TeamvsTeam", "strSportThumb": "", "strSportIconGreen": "", "strSportDescription": ""},
                {"idSport": "102", "strSport": "Basketball", "strFormat": "TeamvsTeam", "strSportThumb": "", "strSportIconGreen": "", "strSportDescription": ""}
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        sports = self.fetcher.get_all_sports()
        self.assertEqual(len(sports), 2)
        self.assertIn("Soccer", sports)
        self.assertIn("Basketball", sports)
        mock_get.assert_called_once_with(f"{self.expected_base_url}all_sports.php", params=None, timeout=10)

    @patch('requests.Session.get')
    def test_get_all_sports_api_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.RequestException("API Error")
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        sports = self.fetcher.get_all_sports()
        self.assertEqual(sports, [])
        mock_get.assert_called_once_with(f"{self.expected_base_url}all_sports.php", params=None, timeout=10)

    @patch('requests.Session.get')
    def test_get_all_sports_empty_list(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"sports": []}
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        sports = self.fetcher.get_all_sports()
        self.assertEqual(sports, [])

    @patch('requests.Session.get')
    def test_get_all_sports_none_response(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"sports": None} # API might return null for sports key
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        sports = self.fetcher.get_all_sports()
        self.assertEqual(sports, [])

    @patch('requests.Session.get')
    def test_get_leagues_by_sport_success(self, mock_get):
        sport_name = "Soccer"
        mock_response = MagicMock()
        # The API for search_all_leagues.php returns leagues under "countries" or "leagues"
        mock_response.json.return_value = {
            "countries": [ # Or "leagues" depending on API consistency
                {"idLeague": "4328", "strLeague": "English Premier League", "strSport": "Soccer"},
                {"idLeague": "4335", "strLeague": "La Liga", "strSport": "Soccer"}
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        leagues = self.fetcher.get_leagues_by_sport(sport_name)
        self.assertEqual(len(leagues), 2)
        self.assertEqual(leagues[0]["strLeague"], "English Premier League")
        mock_get.assert_called_once_with(f"{self.expected_base_url}search_all_leagues.php", params={"s": sport_name}, timeout=10)

    @patch('requests.Session.get')
    def test_get_leagues_by_sport_no_leagues_found(self, mock_get):
        sport_name = "NonExistentSport"
        mock_response = MagicMock()
        # API might return empty list or null for the relevant key
        mock_response.json.return_value = {"countries": []} 
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        leagues = self.fetcher.get_leagues_by_sport(sport_name)
        self.assertEqual(leagues, [])

    @patch('requests.Session.get')
    def test_get_leagues_by_sport_api_error(self, mock_get):
        sport_name = "Soccer"
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.RequestException("API Error")
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        leagues = self.fetcher.get_leagues_by_sport(sport_name)
        self.assertEqual(leagues, [])

    @patch('requests.Session.get')
    def test_get_upcoming_games_by_league_id_success(self, mock_get):
        league_id = "4328"
        season = "2023-2024"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "events": [
                {"idEvent": "1", "strEvent": "Team A vs Team B", "dateEvent": "2023-08-15"},
                {"idEvent": "2", "strEvent": "Team C vs Team D", "dateEvent": "2023-08-16"}
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        games = self.fetcher.get_upcoming_games_by_league_id(league_id, season)
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0]["strEvent"], "Team A vs Team B")
        mock_get.assert_called_once_with(f"{self.expected_base_url}eventsseason.php", params={"id": league_id, "s": season}, timeout=10)

    @patch('requests.Session.get')
    def test_get_upcoming_games_no_games_found(self, mock_get):
        league_id = "0000" # A league with no games
        season = "2023-2024"
        mock_response = MagicMock()
        mock_response.json.return_value = {"events": []} # API returns empty list for events
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        games = self.fetcher.get_upcoming_games_by_league_id(league_id, season)
        self.assertEqual(games, [])
        
    @patch('requests.Session.get')
    def test_get_upcoming_games_events_key_is_none(self, mock_get):
        league_id = "0001" 
        season = "2023-2024"
        mock_response = MagicMock()
        mock_response.json.return_value = {"events": None} # API returns null for events key
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        games = self.fetcher.get_upcoming_games_by_league_id(league_id, season)
        self.assertEqual(games, [])


    @patch('requests.Session.get')
    def test_get_upcoming_games_api_error(self, mock_get):
        league_id = "4328"
        season = "2023-2024"
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.RequestException("API Error")
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        games = self.fetcher.get_upcoming_games_by_league_id(league_id, season)
        self.assertEqual(games, [])

    def test_api_key_in_url(self):
        # This test checks if the base_url used by the fetcher instance for its requests
        # correctly incorporates the API key it was initialized with.
        # The SportsFetcher._make_request method uses self.base_url
        self.assertTrue(TEST_API_KEY in self.fetcher.base_url)
        self.assertEqual(self.fetcher.base_url, self.expected_base_url)

    @patch('requests.Session.get')
    def test_make_request_json_decode_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("JSON Decode Error") # Simulate malformed JSON
        mock_get.return_value = mock_response

        # Call any method that uses _make_request
        result = self.fetcher.get_all_sports()
        self.assertEqual(result, []) # Expect empty list or appropriate error handling
        # Check that a print statement about parsing error occurred (if SportsFetcher prints)
        # This might require capturing stdout if we want to assert the print.

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
