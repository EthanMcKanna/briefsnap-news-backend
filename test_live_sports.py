#!/usr/bin/env python3
"""Test script for live sports updates functionality."""

from datetime import datetime
from newsaggregator.fetchers.live_sports_fetcher import LiveSportsFetcher
from newsaggregator.storage.sports_storage import SportsStorage


def _synthetic_live_games():
    return {
        'mlb': [
            {
                'sport': 'mlb',
                'away_team': {'abbreviation': 'SEA'},
                'home_team': {'abbreviation': 'NYY'},
                'away_score': 3,
                'home_score': 4,
                'status': 'Bot 7th',
                'time_remaining': 'Bot 7th',
                'is_final': False,
            },
            {
                'sport': 'mlb',
                'away_team': {'abbreviation': 'LAD'},
                'home_team': {'abbreviation': 'SF'},
                'away_score': 6,
                'home_score': 2,
                'status': 'Final',
                'time_remaining': '',
                'is_final': True,
            },
        ],
        'nba': [
            {
                'sport': 'nba',
                'away_team': {'abbreviation': 'BOS'},
                'home_team': {'abbreviation': 'NYK'},
                'away_score': 88,
                'home_score': 91,
                'status': '4th Quarter',
                'time_remaining': '6:21',
                'status_state': 'in',
            }
        ],
        'nhl': [],
    }


def test_live_games_summary_counts_live_and_recent_finals():
    fetcher = LiveSportsFetcher()
    summary = fetcher.get_live_games_summary(_synthetic_live_games())

    assert summary['total_games'] == 3
    assert summary['total_live_games'] == 2
    assert summary['total_finished_games'] == 1
    assert summary['sports_with_games'] == 2
    assert summary['sports_with_live_games'] == 2
    assert summary['sports_with_finished_games'] == 1

    assert summary['by_sport']['mlb']['count'] == 2
    assert summary['by_sport']['mlb']['total'] == 2
    assert summary['by_sport']['mlb']['live'] == 1
    assert summary['by_sport']['mlb']['finished'] == 1
    assert summary['by_sport']['nba']['sport_name'] == 'NBA'

    assert len(summary['live_games_detail']) == 2
    assert len(summary['finished_games_detail']) == 1
    assert summary['finished_games_detail'][0]['status'] == 'Final'


def run_live_fetcher_smoke():
    """Test the live sports fetcher."""
    print("====== Testing Live Sports Fetcher ======\n")
    
    fetcher = LiveSportsFetcher()
    
    # Test time checking
    should_check = fetcher.should_check_for_live_games()
    print(f"Should check for live games now: {should_check}")
    
    # Test fetching live games for each sport
    print("\nTesting individual sport fetching:")
    for sport in ['nfl', 'nba', 'mlb', 'nhl']:
        print(f"\n--- {sport.upper()} ---")
        live_games = fetcher.fetch_live_games_only(sport)
        print(f"Found {len(live_games)} live {sport.upper()} games")
        
        for game in live_games:
            home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
            away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
            status = game.get('status', 'TBD')
            home_score = game.get('home_score', 0)
            away_score = game.get('away_score', 0)
            time_remaining = game.get('time_remaining', '')
            
            print(f"  🔴 {away_team} {away_score} - {home_score} {home_team}")
            print(f"     Status: {status} {time_remaining}")
    
    # Test fetching all live games
    print(f"\n--- All Sports Live Games ---")
    all_live_games = fetcher.fetch_all_live_games()
    
    total_live = sum(len(games) for games in all_live_games.values())
    print(f"Total live games across all sports: {total_live}")
    
    # Generate summary
    if total_live > 0:
        summary = fetcher.get_live_games_summary(all_live_games)
        
        print(f"\nLive Games Summary:")
        print(f"  Total live games: {summary['total_live_games']}")
        print(f"  Sports with live games: {summary['sports_with_live_games']}")
        
        if summary['by_sport']:
            print("\n  By sport:")
            for sport, info in summary['by_sport'].items():
                print(f"    {info['sport_name']}: {info['count']} games")
        
        print("\n  Live game details:")
        for game in summary['live_games_detail']:
            print(f"    {game['sport']}: {game['away_team']} {game['away_score']} - {game['home_score']} {game['home_team']}")
            if game['time_remaining']:
                print(f"      {game['status']} - {game['time_remaining']}")
        
        return all_live_games, summary
    else:
        print("No live games found")
        return {}, {}

def run_live_storage_smoke(live_games, summary):
    """Test the live sports storage."""
    print(f"\n====== Testing Live Sports Storage ======\n")
    
    if not live_games or sum(len(games) for games in live_games.values()) == 0:
        print("No live games to test storage with")
        return
    
    # Test updating live games
    print("Testing live games update...")
    update_stats = SportsStorage.update_live_games_only(live_games)
    
    if update_stats.get('success'):
        print("✅ Live games update test successful")
        
        print(f"\nUpdate Statistics:")
        print(f"  Games processed: {update_stats['total_processed']}")
        print(f"  Games updated: {update_stats['games_updated']}")
        print(f"  Games skipped: {update_stats['games_skipped']}")
        print(f"  Games not found: {update_stats['games_not_found']}")
        
        if update_stats['by_sport']:
            print(f"\n  By sport:")
            for sport, stats in update_stats['by_sport'].items():
                print(f"    {sport.upper()}: {stats['updated']} updated, {stats['skipped']} skipped, {stats['not_found']} not in DB")
        
        if update_stats['updates_made']:
            print(f"\n  Updates made:")
            for update in update_stats['updates_made']:
                print(f"    {update['sport']}: {update['away_team']} {update['score']} {update['home_team']}")
                print(f"      Changes: {', '.join(update['changes'])}")
    else:
        print(f"❌ Live games update test failed: {update_stats.get('error')}")

def run_existing_data_smoke():
    """Test accessing existing data."""
    print(f"\n====== Testing Existing Data Access ======\n")
    
    # Get current live games
    print("Current live games in database:")
    live_games = SportsStorage.get_live_games()
    
    if live_games:
        print(f"Found {len(live_games)} live games in database:")
        for game in live_games[:5]:  # Show first 5
            home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
            away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
            sport = game.get('sport', 'Unknown')
            status = game.get('status', 'TBD')
            home_score = game.get('home_score', 0)
            away_score = game.get('away_score', 0)
            time_remaining = game.get('time_remaining', '')
            update_count = game.get('update_count', 0)
            last_updated = game.get('last_updated')
            
            print(f"  🔴 {sport}: {away_team} {away_score} - {home_score} {home_team}")
            print(f"     {status} {time_remaining}")
            print(f"     Updated {update_count} times, last: {last_updated}")
    else:
        print("No live games found in database")
    
    # Get recently updated games
    print(f"\nRecently updated games (last hour):")
    recent_updates = SportsStorage.get_recently_updated_games(hours=1)
    
    if recent_updates:
        print(f"Found {len(recent_updates)} recently updated games:")
        for game in recent_updates[:3]:  # Show first 3
            home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
            away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
            sport = game.get('sport', 'Unknown')
            changes = game.get('last_changes', [])
            update_count = game.get('update_count', 0)
            
            print(f"  📝 {sport}: {away_team} @ {home_team}")
            print(f"     Updated {update_count} times")
            if changes:
                print(f"     Last changes: {', '.join(changes)}")
    else:
        print("No recently updated games found")

def main():
    """Run all tests."""
    print("====== Live Sports Test Suite ======")
    print(f"Test started at: {datetime.now()}")
    
    try:
        # Test the fetcher
        live_games, summary = run_live_fetcher_smoke()
        
        # Test the storage
        run_live_storage_smoke(live_games, summary)
        
        # Test existing data access
        run_existing_data_smoke()
        
        print(f"\n====== Test Complete: {datetime.now()} ======")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
