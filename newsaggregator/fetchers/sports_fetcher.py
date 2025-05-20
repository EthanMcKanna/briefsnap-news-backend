"""
Fetcher for sports data from TheSportsDB API.
"""
import requests
import time
from newsaggregator.config.settings import SPORTS_API_KEY

# Base URL for TheSportsDB API
THE_SPORTS_DB_API_URL = f"https://www.thesportsdb.com/api/v1/json/{SPORTS_API_KEY}/"

class SportsFetcher:
    """
    A class to fetch sports-related data from TheSportsDB API.
    """

    def __init__(self, api_key: str = SPORTS_API_KEY):
        """
        Initializes the SportsFetcher with an API key and a requests session.

        Args:
            api_key (str): The API key for TheSportsDB. Defaults to SPORTS_API_KEY from settings.
        """
        if not api_key:
            raise ValueError("API key for TheSportsDB must be provided.")
        self.api_key = api_key  # Though included in BASE_URL, might be useful for other request types
        self.session = requests.Session()
        self.base_url = THE_SPORTS_DB_API_URL # Updated to use the one with API key

    def _make_request(self, endpoint: str, params: dict = None) -> dict | None:
        """
        Makes a GET request to the specified API endpoint.

        Args:
            endpoint (str): The API endpoint to call (e.g., 'all_sports.php').
            params (dict, optional): A dictionary of query parameters. Defaults to None.

        Returns:
            dict | None: The parsed JSON response data, or None if an error occurs.
        """
        url = f"{self.base_url}{endpoint}"
        # The API key is already in self.base_url, so no need to add it to params explicitly unless API changes.
        # If params are needed for the specific endpoint, they will be passed in.

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            
            # Small delay to respect potential rate limits
            time.sleep(0.5) # 0.5 seconds delay

            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {e}")
            return None
        except ValueError as e: # Includes JSONDecodeError
            print(f"Error parsing JSON response from {url}: {e}")
            return None

    def get_all_sports(self) -> list[str]:
        """
        Fetches a list of all available sports.

        Returns:
            list[str]: A list of sport names, or an empty list if the request fails or no sports are found.
        """
        data = self._make_request("all_sports.php")
        if data and "sports" in data and data["sports"]:
            return [sport["strSport"] for sport in data["sports"] if "strSport" in sport]
        return []

    def get_leagues_by_sport(self, sport_name: str) -> list[dict]:
        """
        Fetches a list of leagues for a given sport.

        Args:
            sport_name (str): The name of the sport (e.g., 'Soccer').

        Returns:
            list[dict]: A list of league details, or an empty list if the request fails or no leagues are found.
        """
        # The API endpoint for searching leagues by sport is search_all_leagues.php?s={sport_name}
        # However, the API documentation also suggests searchleagues.php?s={sport_name} for just league names.
        # Let's use search_all_leagues.php to get more details.
        # The API key is already part of self.base_url
        # The parameter 's' is for sport name
        data = self._make_request("search_all_leagues.php", params={"s": sport_name})
        if data and "countries" in data and data["countries"]: # API returns 'countries' which contains leagues
            return data["countries"]
        elif data and "leagues" in data and data["leagues"]: # some endpoints might return "leagues"
             return data["leagues"]
        return []

    def get_upcoming_games_by_league_id(self, league_id: str, season: str) -> list[dict]:
        """
        Fetches upcoming games for a given league and season.
        Note: The 'eventsseason.php' endpoint is used, which might be limited on the free tier.

        Args:
            league_id (str): The ID of the league.
            season (str): The season identifier (e.g., "2023-2024", "2024").

        Returns:
            list[dict]: A list of upcoming game details, or an empty list if an error occurs or no games are found.
        """
        # Endpoint: eventsseason.php?id={league_id}&s={season}
        params = {"id": league_id, "s": season}
        data = self._make_request("eventsseason.php", params=params)
        if data and "events" in data and data["events"]:
            return data["events"]
        return []

if __name__ == '__main__':
    # Example usage (requires SPORTS_API_KEY to be set correctly in settings or passed)
    # Ensure you have a valid API key in your settings for this to work.
    # The default key "3" used in the previous step is likely a placeholder and won't work.
    # You would need a real key from TheSportsDB.
    print(f"Attempting to use API Key: {SPORTS_API_KEY}")
    if SPORTS_API_KEY == "3" or not SPORTS_API_KEY:
        print("Warning: SPORTS_API_KEY is set to a placeholder or is empty. API calls will likely fail.")
        print("Please obtain a valid API key from https://www.thesportsdb.com/api.php and update it in your settings.")
    
    fetcher = SportsFetcher()

    print("\nFetching all sports...")
    sports = fetcher.get_all_sports()
    if sports:
        print(f"Found {len(sports)} sports. First 5: {sports[:5]}")
        
        # Example: Get leagues for the first sport found (if any)
        if sports:
            first_sport = sports[0]
            print(f"\nFetching leagues for sport: {first_sport}...")
            leagues = fetcher.get_leagues_by_sport(first_sport)
            if leagues:
                print(f"Found {len(leagues)} leagues for {first_sport}.")
                # Print details of the first league if available
                # The structure of league details can vary.
                # Based on common API responses, a league might have 'idLeague', 'strLeague', 'strSport'.
                # The endpoint search_all_leagues.php?s={sport_name} returns leagues under "countries" key.
                # Each item in "countries" might represent a country and its leagues, or just leagues directly.
                # Let's inspect the first item.
                if leagues[0]:
                     print(f"First league details: {str(leagues[0])[:200]}...") # Print first 200 chars
                
                # Try to get games for the first league found (e.g., English Premier League id 4328, season 2023-2024)
                # This is an example, the actual first league ID might be different or not exist.
                # For testing, let's use a known league ID if available, otherwise skip.
                # English Premier League ID: 4328
                # La Liga ID: 4335
                test_league_id = "4328" # English Premier League
                test_season = "2023-2024" 
                # Check if the first league has an idLeague field
                dynamic_league_id = None
                if leagues and isinstance(leagues[0], dict) and leagues[0].get("idLeague"):
                    dynamic_league_id = leagues[0]["idLeague"]
                    print(f"\nUsing dynamically found league ID: {dynamic_league_id} for sport {leagues[0].get('strSport', '')}")
                    # For season, it's harder to guess. Let's use a common recent season.
                    # Or if the league object has a current season field, use that.
                    # For now, we stick with test_season for predictability in example.
                    
                    print(f"\nFetching upcoming games for league ID: {dynamic_league_id} and season: {test_season}...")
                    games = fetcher.get_upcoming_games_by_league_id(dynamic_league_id, test_season)
                    if games:
                        print(f"Found {len(games)} upcoming games for league {dynamic_league_id}, season {test_season}.")
                        # Print details of the first game
                        if games[0]:
                            print(f"First game details: {str(games[0])[:200]}...")
                    else:
                        print(f"No upcoming games found for league {dynamic_league_id}, season {test_season}.")
                else:
                     print(f"\nCould not dynamically find a league ID from sport {first_sport}. Skipping game fetching for it.")

            else:
                print(f"No leagues found for {first_sport}.")
    else:
        print("No sports found.")

    # Example for a specific known league (e.g., NBA)
    # Sport: Basketball, League: NBA (idLeague: 4387)
    # Note: Requires the API key to be valid and have access to this data.
    print("\nFetching leagues for sport: Basketball...")
    basketball_leagues = fetcher.get_leagues_by_sport("Basketball")
    if basketball_leagues:
        nba_league = next((l for l in basketball_leagues if l.get("idLeague") == "4387"), None)
        if nba_league:
            print(f"Found NBA league: {nba_league.get('strLeague')}")
            nba_id = nba_league["idLeague"]
            current_season = "2023-2024" # Adjust as needed
            print(f"\nFetching games for NBA (ID: {nba_id}) for season {current_season}...")
            nba_games = fetcher.get_upcoming_games_by_league_id(nba_id, current_season)
            if nba_games:
                print(f"Found {len(nba_games)} games for NBA, season {current_season}.")
                if nba_games[0]:
                    print(f"First NBA game details: {str(nba_games[0])[:200]}...")
            else:
                print(f"No games found for NBA, season {current_season}.")
        else:
            print("NBA league not found within Basketball leagues.")
    else:
        print("No leagues found for Basketball.")
