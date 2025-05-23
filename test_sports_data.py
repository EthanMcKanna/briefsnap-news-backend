#!/usr/bin/env python3
"""Test script to demonstrate accessing sports data from Firebase."""

from datetime import datetime, timedelta
from newsaggregator.storage.sports_storage import SportsStorage

def main():
    """Test accessing sports data."""
    print("====== Sports Data Access Test ======\n")
    
    # Get latest summary
    print("1. Latest Summary:")
    summary = SportsStorage.get_latest_summary()
    if summary:
        print(f"   Total games: {summary['total_games']}")
        print(f"   Last updated: {summary['last_updated']}")
        print(f"   Sports with games: {summary['sports_count']}")
        for sport, info in summary['by_sport'].items():
            if info['count'] > 0:
                print(f"   - {info['sport_name']}: {info['count']} games")
    else:
        print("   No summary found")
    
    print("\n" + "="*50 + "\n")
    
    # Get upcoming games
    print("2. Next 10 Upcoming Games:")
    upcoming_games = SportsStorage.get_upcoming_games(limit=10)
    for i, game in enumerate(upcoming_games, 1):
        home_team = game.get('home_team', {}).get('name', 'TBD')
        away_team = game.get('away_team', {}).get('name', 'TBD')
        sport = game.get('sport', 'Unknown')
        date = game.get('formatted_date', 'TBD')
        time = game.get('formatted_time', 'TBD')
        
        print(f"   {i}. {sport}: {away_team} @ {home_team}")
        print(f"      Date: {date} at {time}")
        
        if game.get('venue', {}).get('name'):
            venue = game['venue']['name']
            city = game['venue'].get('city', '')
            print(f"      Venue: {venue}, {city}")
        
        if game.get('broadcasts'):
            networks = [b.get('network') for b in game['broadcasts'] if b.get('network')]
            if networks:
                print(f"      TV: {', '.join(networks)}")
        
        print()
    
    print("="*50 + "\n")
    
    # Get games by sport
    print("3. NBA Games:")
    nba_games = SportsStorage.get_upcoming_games(sport='nba', limit=5)
    for game in nba_games:
        home_team = game.get('home_team', {}).get('name', 'TBD')
        away_team = game.get('away_team', {}).get('name', 'TBD')
        date = game.get('formatted_date', 'TBD')
        time = game.get('formatted_time', 'TBD')
        
        print(f"   {away_team} @ {home_team} - {date} at {time}")
    
    print("\n" + "="*50 + "\n")
    
    # Get today's games
    print("4. Today's Games:")
    today_games = SportsStorage.get_games_by_date(datetime.now())
    if today_games:
        for game in today_games:
            home_team = game.get('home_team', {}).get('name', 'TBD')
            away_team = game.get('away_team', {}).get('name', 'TBD')
            sport = game.get('sport', 'Unknown')
            time = game.get('formatted_time', 'TBD')
            
            print(f"   {sport}: {away_team} @ {home_team} at {time}")
    else:
        print("   No games today")
    
    print("\n" + "="*50 + "\n")
    
    # Get live games
    print("5. Live Games:")
    live_games = SportsStorage.get_live_games()
    if live_games:
        for game in live_games[:3]:  # Show top 3 live games
            home_team = game.get('home_team', {}).get('name', 'TBD')
            away_team = game.get('away_team', {}).get('name', 'TBD')
            sport = game.get('sport', 'Unknown')
            status = game.get('status', 'TBD')
            home_score = game.get('home_score', 0)
            away_score = game.get('away_score', 0)
            time_remaining = game.get('time_remaining', '')
            
            print(f"   🔴 {sport}: {away_team} {away_score} - {home_score} {home_team}")
            print(f"      Status: {status} {time_remaining}")
            if game.get('update_count', 0) > 0:
                print(f"      Updated {game['update_count']} times")
            print()
    else:
        print("   No live games currently")
    
    print("\n" + "="*50 + "\n")
    
    # Get recently updated games
    print("6. Recently Updated Games (last 2 hours):")
    recent_updates = SportsStorage.get_recently_updated_games(hours=2)
    if recent_updates:
        for game in recent_updates[:5]:
            home_team = game.get('home_team', {}).get('name', 'TBD')
            away_team = game.get('away_team', {}).get('name', 'TBD')
            sport = game.get('sport', 'Unknown')
            changes = game.get('last_changes', [])
            update_count = game.get('update_count', 0)
            last_updated = game.get('last_updated')
            
            print(f"   📝 {sport}: {away_team} @ {home_team}")
            print(f"      Updated {update_count} times")
            if changes:
                print(f"      Last changes: {', '.join(changes)}")
            if last_updated:
                print(f"      Last update: {last_updated}")
            print()
    else:
        print("   No recent updates")
    
    print("\n" + "="*50 + "\n")
    
    # Get database stats
    print("7. Database Statistics:")
    stats = SportsStorage.get_sports_stats()
    if stats:
        print(f"   Total games in database: {stats['total_games']}")
        print(f"   Upcoming games: {stats['upcoming_games']}")
        
        if stats['by_sport']:
            print("\n   By sport:")
            for sport, sport_stats in stats['by_sport'].items():
                print(f"     {sport_stats['sport_name']}: {sport_stats['total']} total, {sport_stats['upcoming']} upcoming")
    
    print("\n====== Test Complete ======")

if __name__ == "__main__":
    main() 