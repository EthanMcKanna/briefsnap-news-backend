#!/usr/bin/env python3
"""Main entry point for the sports aggregator system."""

import os
import sys
import traceback
import json
from datetime import datetime
from newsaggregator.fetchers.sports_fetcher import SportsFetcher
from newsaggregator.storage.sports_storage import SportsStorage
from newsaggregator.config.settings import DATA_DIR

def main():
    """Main function to run the sports aggregator."""
    start_time = datetime.now()
    print(f"====== Sports Aggregator Started: {start_time} ======")
    
    # Ensure data directory exists
    sports_data_dir = DATA_DIR / 'sports_data'
    os.makedirs(sports_data_dir, exist_ok=True)
    
    try:
        # Initialize the sports fetcher
        sports_fetcher = SportsFetcher()
        
        # For frequent updates, focus on games today and tomorrow for better performance
        print("Fetching sports games for next 7 days...")
        all_games = sports_fetcher.fetch_all_sports(days_ahead=7)
        
        # Generate summary
        summary = sports_fetcher.get_games_summary(all_games)
        
        # Log summary
        print(f"\n====== Sports Data Summary ======")
        print(f"Total games found: {summary['total_games']}")
        print(f"Sports with games: {summary['sports_count']}")
        
        for sport, info in summary['by_sport'].items():
            if info['count'] > 0:
                print(f"  {info['sport_name']}: {info['count']} games")
        
        if summary['next_24_hours']:
            print(f"\nGames in next 24 hours:")
            for sport, info in summary['next_24_hours'].items():
                print(f"  {summary['by_sport'][sport]['sport_name']}: {info['count']} games")
        
        # Store data locally
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save all games to JSON
        games_file = sports_data_dir / f'all_games_{timestamp}.json'
        with open(games_file, 'w') as f:
            json.dump(all_games, f, indent=2, default=str)
        print(f"Saved games data to: {games_file}")
        
        # Save summary to JSON
        summary_file = sports_data_dir / f'summary_{timestamp}.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"Saved summary to: {summary_file}")
        
        # Store in Firebase
        print("\nStoring data in Firebase...")
        success = SportsStorage.store_games(all_games, summary)
        
        if success:
            print("✅ Successfully stored sports data in Firebase")
            
            # Show live games
            live_games = SportsStorage.get_live_games()
            if live_games:
                print(f"\n====== Live Games ({len(live_games)}) ======")
                for game in live_games[:5]:  # Show top 5 live games
                    home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
                    away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
                    sport = game.get('sport', 'Unknown')
                    status = game.get('status', 'TBD')
                    home_score = game.get('home_score', 0)
                    away_score = game.get('away_score', 0)
                    time_remaining = game.get('time_remaining', '')
                    
                    print(f"  🔴 {sport}: {away_team} {away_score} - {home_score} {home_team}")
                    print(f"      Status: {status} {time_remaining}")
            
            # Show recently updated games
            recent_updates = SportsStorage.get_recently_updated_games(hours=1)
            if recent_updates:
                print(f"\n====== Recent Updates ({len(recent_updates)}) ======")
                for game in recent_updates[:3]:  # Show top 3 recent updates
                    home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
                    away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
                    sport = game.get('sport', 'Unknown')
                    changes = game.get('last_changes', [])
                    update_count = game.get('update_count', 0)
                    
                    print(f"  📝 {sport}: {away_team} @ {home_team} (updated {update_count} times)")
                    if changes:
                        print(f"      Changes: {', '.join(changes)}")
            
            # Get and display stats
            stats = SportsStorage.get_sports_stats()
            if stats:
                print(f"\n====== Firebase Stats ======")
                print(f"Total games in database: {stats['total_games']}")
                print(f"Upcoming games: {stats['upcoming_games']}")
                
                if stats['by_sport']:
                    print("\nBy sport:")
                    for sport, sport_stats in stats['by_sport'].items():
                        print(f"  {sport_stats['sport_name']}: {sport_stats['total']} total, {sport_stats['upcoming']} upcoming")
        else:
            print("❌ Failed to store sports data in Firebase")
            return 1
        
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"\n====== Sports Aggregator Completed: {end_time} ======")
        print(f"====== Total Duration: {duration} ======")
        return 0
        
    except Exception as e:
        print(f"ERROR: Sports aggregator failed with exception: {str(e)}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main()) 