#!/usr/bin/env python3
"""Main entry point for live sports updates - lightweight and fast."""

import os
import sys
import traceback
import json
from datetime import datetime
from newsaggregator.briefs.pipeline import DailyBriefPipeline, PipelineOptions
from newsaggregator.fetchers.live_sports_fetcher import LiveSportsFetcher
from newsaggregator.storage.sports_storage import SportsStorage
from newsaggregator.config.settings import DATA_DIR

def main():
    """Main function to run live sports updates."""
    start_time = datetime.now()
    print(f"====== Live Sports Update Started: {start_time} ======")
    
    # Ensure data directory exists
    sports_data_dir = DATA_DIR / 'sports_data' / 'live_updates'
    os.makedirs(sports_data_dir, exist_ok=True)
    
    try:
        # Initialize the live sports fetcher
        live_fetcher = LiveSportsFetcher()
        
        # Check if it's a good time to look for live games. Even outside the
        # live window, keep cleanup and daily-brief score refreshes running so
        # morning slates do not depend on yesterday's final-score cards.
        if live_fetcher.should_check_for_live_games():
            print("Checking for live games across all sports...")
            all_live_games = live_fetcher.fetch_all_live_games()
            live_summary = live_fetcher.get_live_games_summary(all_live_games)
        else:
            print("Outside prime live-game hours - skipping live scoreboard poll")
            print("Still refreshing brief score cards and expiring stale records")
            all_live_games = {}
            live_summary = {
                'total_games': 0,
                'total_live_games': 0,
                'total_finished_games': 0,
                'sports_with_games': 0,
                'by_sport': {},
                'live_games_detail': [],
                'finished_games_detail': [],
            }
        
        print(f"\n====== Live/Recent Games Summary ======")
        print(f"Total games found: {live_summary['total_games']}")
        print(f"Live games: {live_summary['total_live_games']}")
        print(f"Recently finished: {live_summary['total_finished_games']}")
        print(f"Sports with games: {live_summary['sports_with_games']}")
        
        if live_summary['total_games'] == 0:
            print("No live or recently finished games found - expiring stale live records if needed")
        
        # Display games found by sport
        if live_summary['by_sport']:
            print("\nGames by sport:")
            for sport, info in live_summary['by_sport'].items():
                if info['live'] > 0 and info['finished'] > 0:
                    print(f"  {info['sport_name']}: {info['live']} live, {info['finished']} finished")
                elif info['live'] > 0:
                    print(f"  {info['sport_name']}: {info['live']} live games")
                elif info['finished'] > 0:
                    print(f"  {info['sport_name']}: {info['finished']} recently finished")
        
        # Show live game details
        if live_summary['live_games_detail']:
            print(f"\n🔴 Live Games:")
            for game in live_summary['live_games_detail']:
                print(f"  {game['sport']}: {game['away_team']} {game['away_score']} - {game['home_score']} {game['home_team']}")
                if game['status'] and game['time_remaining']:
                    print(f"    {game['status']} - {game['time_remaining']}")
                elif game['status']:
                    print(f"    {game['status']}")
        
        # Show recently finished games
        if live_summary['finished_games_detail']:
            print(f"\n✅ Recently Finished Games:")
            for game in live_summary['finished_games_detail']:
                print(f"  {game['sport']}: {game['away_team']} {game['away_score']} - {game['home_score']} {game['home_team']}")
                print(f"    {game['status']}")
        
        # Update only the live games in Firebase
        print(f"\n====== Updating Live Games in Firebase ======")
        update_stats = SportsStorage.update_live_games_only(all_live_games)
        
        if update_stats.get('success'):
            print("✅ Live games update completed successfully")
            
            # Show update statistics
            if (
                update_stats['games_updated'] > 0
                or update_stats.get('games_created', 0) > 0
                or update_stats.get('stale_games_expired', 0) > 0
                or update_stats.get('stale_final_scores_archived', 0) > 0
            ):
                print(f"\n📊 Update Statistics:")
                print(f"  Games processed: {update_stats['total_processed']}")
                print(f"  Games created: {update_stats.get('games_created', 0)}")
                print(f"  Games updated: {update_stats['games_updated']}")
                print(f"  Stale live games expired: {update_stats.get('stale_games_expired', 0)}")
                print(f"  Stale final scores archived: {update_stats.get('stale_final_scores_archived', 0)}")
                print(f"  Games skipped (no changes): {update_stats['games_skipped']}")
                if update_stats.get('games_not_found', 0):
                    print(f"  Games not in database: {update_stats['games_not_found']}")
                
                # Show updates by sport
                if update_stats['by_sport']:
                    print(f"\n  Updates by sport:")
                    for sport, stats in update_stats['by_sport'].items():
                        print(f"    {sport.upper()}: {stats['updated']} updated, {stats['skipped']} skipped")
                
                # Show specific updates made
                if update_stats['updates_made']:
                    print(f"\n🔄 Recent Updates:")
                    for update in update_stats['updates_made'][-5:]:  # Show last 5 updates
                        print(f"  {update['sport']}: {update['away_team']} {update['score']} {update['home_team']}")
                        print(f"    Changes: {', '.join(update['changes'])}")
                        if update['time_remaining']:
                            print(f"    {update['status']} - {update['time_remaining']}")
            else:
                print("No live games required updates (scores/time unchanged)")
        else:
            print(f"❌ Live games update failed: {update_stats.get('error', 'Unknown error')}")
            return 1

        print(f"\n====== Refreshing Daily Brief Sports Scores ======")
        try:
            refresh_stats = DailyBriefPipeline(
                PipelineOptions(dry_run=True, publish=False)
            ).refresh_latest_firestore_sports_scores()
        except Exception as exc:
            print(f"⚠️ Daily brief sports score refresh failed: {exc}")
        else:
            if refresh_stats.get("success"):
                print(
                    "✅ Daily brief sports scores refreshed "
                    f"for {refresh_stats.get('doc_id')} "
                    f"({refresh_stats.get('scores_count', 0)} game cards)"
                )
            else:
                print(f"⚠️ Daily brief sports score refresh skipped: {refresh_stats.get('error')}")
        
        # Save live update data locally (lightweight)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save live games data
        if live_summary['total_live_games'] > 0:
            live_data = {
                'timestamp': timestamp,
                'live_games': all_live_games,
                'summary': live_summary,
                'update_stats': update_stats
            }
            
            live_file = sports_data_dir / f'live_update_{timestamp}.json'
            with open(live_file, 'w') as f:
                json.dump(live_data, f, indent=2, default=str)
            print(f"Saved live update data to: {live_file}")
        
        # Get current live game stats from Firebase
        current_live = SportsStorage.get_live_games()
        if current_live:
            print(f"\n🔴 Current Live Games in Database ({len(current_live)}):")
            for game in current_live[:3]:  # Show top 3
                home_team = game.get('home_team', {}).get('abbreviation', 'TBD')
                away_team = game.get('away_team', {}).get('abbreviation', 'TBD')
                sport = game.get('sport', 'Unknown')
                status = game.get('status', 'TBD')
                home_score = game.get('home_score', 0)
                away_score = game.get('away_score', 0)
                time_remaining = game.get('time_remaining', '')
                update_count = game.get('update_count', 0)
                
                print(f"  {sport}: {away_team} {away_score} - {home_score} {home_team}")
                print(f"    {status} {time_remaining} (updated {update_count} times)")
        
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"\n====== Live Sports Update Completed: {end_time} ======")
        print(f"====== Duration: {duration} ======")
        return 0
        
    except Exception as e:
        print(f"ERROR: Live sports update failed with exception: {str(e)}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
