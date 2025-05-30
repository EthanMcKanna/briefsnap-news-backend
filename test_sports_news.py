#!/usr/bin/env python3
"""Test script to demonstrate sports news summaries functionality."""

from datetime import datetime
from newsaggregator.storage.sports_storage import SportsStorage
from newsaggregator.processors.sports_news_summarizer import SportsNewsSummarizer

def main():
    """Test sports news summaries functionality."""
    print("====== Sports News Summaries Test ======\n")
    
    # Test 1: Get latest news summaries from database
    print("1. Latest News Summaries from Database:")
    latest_summaries = SportsStorage.get_latest_news_summaries()
    
    if latest_summaries:
        for sport_code, summary_data in latest_summaries.items():
            sport_name = summary_data.get('sport_name', sport_code.upper())
            summary_text = summary_data.get('summary', 'No summary available')
            generated_at = summary_data.get('generated_at', 'Unknown')
            
            print(f"\n📰 {sport_name} (Generated: {generated_at}):")
            # Print first 200 characters of summary
            preview = summary_text[:200] + "..." if len(summary_text) > 200 else summary_text
            for line in preview.split('\n'):
                if line.strip():
                    print(f"   {line}")
            print()
    else:
        print("   No news summaries found in database")
    
    print("\n" + "="*50 + "\n")
    
    # Test 2: Get news summaries for specific sport
    print("2. NBA News Summary History:")
    nba_summaries = SportsStorage.get_news_summary_by_sport('nba', limit=3)
    
    if nba_summaries:
        for i, summary in enumerate(nba_summaries, 1):
            generated_at = summary.get('generated_at', 'Unknown')
            summary_text = summary.get('summary', 'No summary available')
            
            print(f"   {i}. Generated: {generated_at}")
            preview = summary_text[:150] + "..." if len(summary_text) > 150 else summary_text
            print(f"      Preview: {preview}")
            print()
    else:
        print("   No NBA news summaries found")
    
    print("\n" + "="*50 + "\n")
    
    # Test 3: Generate a new summary for demonstration (optional)
    print("3. Generate New Summary (Demo - Optional):")
    print("   To generate a new summary, run: python main_sports.py")
    print("   This will fetch sports data and generate news summaries for all sports with games.")
    
    print("\n" + "="*50 + "\n")
    
    # Test 4: Show sports with recent summaries
    print("4. Sports with Recent News Summaries:")
    all_latest = SportsStorage.get_latest_news_summaries()
    
    if all_latest:
        print("   Sports with news summaries:")
        for sport_code, summary_data in all_latest.items():
            sport_name = summary_data.get('sport_name', sport_code.upper())
            generated_at = summary_data.get('generated_at', 'Unknown')
            print(f"   • {sport_name}: {generated_at}")
    else:
        print("   No recent summaries found")

if __name__ == "__main__":
    main() 