#!/usr/bin/env python3
"""Test script for game summary functionality."""

from datetime import datetime, timezone, timedelta
from newsaggregator.processors.game_summary_processor import GameSummaryProcessor
from newsaggregator.storage.sports_storage import SportsStorage

def test_game_summary_processor():
    """Test the game summary processor functionality."""
    print("====== Testing Game Summary Processor ======\n")
    
    processor = GameSummaryProcessor()
    
    # Test getting games within 24 hours
    print("1. Testing get_games_within_24_hours():")
    upcoming_games = processor.get_games_within_24_hours()
    print(f"   Found {len(upcoming_games)} games within 24 hours")
    
    if upcoming_games:
        print("   Sample upcoming games:")
        for i, game in enumerate(upcoming_games[:3]):
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown')
            formatted_date = game.get('formatted_date', 'TBD')
            formatted_time = game.get('formatted_time', 'TBD')
            
            print(f"   {i+1}. {sport}: {away_team} @ {home_team}")
            print(f"      Date: {formatted_date} at {formatted_time}")
            
            # Test game info formatting
            game_info = processor.format_game_info(game)
            print(f"      Formatted: {game_info}")
            print()
    
    print("="*50 + "\n")
    
    # Test getting recently finished games
    print("2. Testing get_recently_finished_games():")
    finished_games = processor.get_recently_finished_games(hours_back=24)
    print(f"   Found {len(finished_games)} recently finished games")
    
    if finished_games:
        print("   Sample finished games:")
        for i, game in enumerate(finished_games[:3]):
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown')
            status = game.get('status', 'Unknown')
            home_score = game.get('home_score', 0)
            away_score = game.get('away_score', 0)
            
            print(f"   {i+1}. {sport}: {away_team} {away_score} - {home_score} {home_team}")
            print(f"      Status: {status}")
            
            # Test game info formatting
            game_info = processor.format_game_info(game)
            print(f"      Formatted: {game_info}")
            print()
    
    print("="*50 + "\n")
    
    # Test checking existing summaries
    print("3. Testing has_existing_summary():")
    if upcoming_games:
        sample_game = upcoming_games[0]
        game_id = sample_game.get('id')
        
        if game_id:
            has_pre_game = processor._has_existing_summary(sample_game, 'pre_game')
            has_post_game = processor._has_existing_summary(sample_game, 'post_game')
            
            print(f"   Game ID: {game_id}")
            print(f"   Has pre-game summary: {has_pre_game}")
            print(f"   Has post-game summary: {has_post_game}")
    
    print("="*50 + "\n")
    
    # Test getting recent game summaries from Firebase
    print("4. Testing Firebase game summary queries:")
    recent_summaries = SportsStorage.get_recent_game_summaries(hours=48)
    print(f"   Found {len(recent_summaries)} recent game summaries")
    
    if recent_summaries:
        print("   Sample recent summaries:")
        for i, summary in enumerate(recent_summaries[:3]):
            game_id = summary.get('game_id', 'Unknown')
            summary_type = summary.get('summary_type', 'Unknown')
            home_team = summary.get('home_team', 'Unknown')
            away_team = summary.get('away_team', 'Unknown')
            generated_at = summary.get('generated_at', 'Unknown')
            
            print(f"   {i+1}. {summary_type} summary for game {game_id}")
            print(f"      Teams: {away_team} @ {home_team}")
            print(f"      Generated at: {generated_at}")
            
            # Show first few lines of summary
            summary_text = summary.get('summary', '')
            if summary_text:
                lines = summary_text.split('\n')
                print(f"      Preview: {lines[0][:100]}...")
            print()
    
    print("="*50 + "\n")
    
    # Test the full process (without actually generating summaries)
    print("5. Testing process_game_summaries() - DRY RUN:")
    print("   This would normally generate actual summaries using Gemini Flash 2 Lite")
    print("   For testing, we'll show what would be processed:")
    
    print(f"   Games within 24 hours that would get pre-game summaries: {len(upcoming_games)}")
    print(f"   Recently finished games that would get post-game summaries: {len(finished_games)}")
    
    # Show which games would be processed
    if upcoming_games:
        print("   \n   Pre-game summaries would be generated for:")
        for i, game in enumerate(upcoming_games[:5]):
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown')
            
            has_existing = processor._has_existing_summary(game, 'pre_game')
            status = "SKIP (already exists)" if has_existing else "GENERATE"
            
            print(f"   {i+1}. {sport}: {away_team} @ {home_team} - {status}")
    
    if finished_games:
        print("   \n   Post-game summaries would be generated for:")
        for i, game in enumerate(finished_games[:5]):
            home_team = game.get('home_team', {}).get('name', 'Home Team')
            away_team = game.get('away_team', {}).get('name', 'Away Team')
            sport = game.get('sport', 'Unknown')
            
            has_existing = processor._has_existing_summary(game, 'post_game')
            status = "SKIP (already exists)" if has_existing else "GENERATE"
            
            print(f"   {i+1}. {sport}: {away_team} @ {home_team} - {status}")

def main():
    """Main test function."""
    print("Testing Game Summary Processor\n")
    print("This script tests the game summary functionality without")
    print("actually calling the Gemini API to avoid API usage during testing.\n")
    
    try:
        test_game_summary_processor()
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 