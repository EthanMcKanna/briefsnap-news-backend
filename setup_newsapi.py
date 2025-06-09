#!/usr/bin/env python3
"""
Setup script for NewsAPI.org integration with the news aggregator.

This script helps configure the enhanced article selection system that uses
NewsAPI.org for more robust article discovery and ranking.
"""

import os
import sys
from pathlib import Path


def check_newsapi_key():
    """Check if NewsAPI.org API key is configured."""
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        print("❌ NEWSAPI_KEY environment variable not found")
        print("\nTo set up NewsAPI.org integration:")
        print("1. Visit https://newsapi.org/ and sign up for a free account")
        print("2. Get your API key from the dashboard")
        print("3. Set the environment variable:")
        print("   export NEWSAPI_KEY='your-api-key-here'")
        print("4. Or add it to your .env file:")
        print("   echo 'NEWSAPI_KEY=your-api-key-here' >> .env")
        return False
    else:
        print(f"✅ NEWSAPI_KEY found: {api_key[:8]}...")
        return True


def test_newsapi_connection():
    """Test the connection to NewsAPI.org."""
    try:
        from newsapi import NewsApiClient
        
        api_key = os.environ.get("NEWSAPI_KEY")
        if not api_key:
            print("❌ No API key available for testing")
            return False
            
        client = NewsApiClient(api_key=api_key)
        
        # Test with a simple request
        print("🔍 Testing NewsAPI.org connection...")
        response = client.get_top_headlines(country='us', page_size=1)
        
        if response.get('status') == 'ok':
            print("✅ NewsAPI.org connection successful")
            print(f"   Total available articles: {response.get('totalResults', 'unknown')}")
            return True
        else:
            print(f"❌ NewsAPI.org error: {response.get('message', 'Unknown error')}")
            return False
            
    except ImportError:
        print("❌ newsapi-python package not installed")
        print("   Run: pip install newsapi-python")
        return False
    except Exception as e:
        print(f"❌ NewsAPI.org connection failed: {e}")
        return False


def check_configuration():
    """Check the current configuration settings."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from newsaggregator.config.settings import (
            USE_NEWSAPI_FOR_DISCOVERY, 
            NEWSAPI_FALLBACK_TO_RSS,
            ARTICLE_QUALITY_THRESHOLD,
            NEWSAPI_KEY
        )
        
        print("\n📋 Current Configuration:")
        print(f"   USE_NEWSAPI_FOR_DISCOVERY: {USE_NEWSAPI_FOR_DISCOVERY}")
        print(f"   NEWSAPI_FALLBACK_TO_RSS: {NEWSAPI_FALLBACK_TO_RSS}")
        print(f"   ARTICLE_QUALITY_THRESHOLD: {ARTICLE_QUALITY_THRESHOLD}")
        print(f"   NEWSAPI_KEY configured: {'Yes' if NEWSAPI_KEY else 'No'}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Configuration import failed: {e}")
        return False


def test_article_selector():
    """Test the enhanced article selector."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from newsaggregator.selectors.article_selector import ArticleSelector
        
        print("\n🚀 Testing Enhanced Article Selector...")
        selector = ArticleSelector()
        
        # Test topic availability
        topics = selector.get_available_topics()
        print(f"   Available topics: {topics}")
        
        # Test quota optimization
        if selector.newsapi_fetcher:
            quota_optimized = selector.get_quota_optimized_topics(max_topics=3)
            print(f"   Quota-optimized topics: {quota_optimized}")
            
            # Show quota status
            quota_status = selector.newsapi_fetcher.quota_manager.get_quota_status()
            print(f"   Quota remaining: {quota_status['remaining']}/{quota_status['daily_limit']}")
        
        # Test article selection for TECHNOLOGY (usually has good coverage)
        if 'TECHNOLOGY' in topics:
            print("   Testing article selection for TECHNOLOGY...")
            articles = selector.select_best_articles_for_topic('TECHNOLOGY', max_articles=3)
            print(f"   Found {len(articles)} high-quality technology articles")
            
            if articles:
                print("   Sample article:")
                article = articles[0]
                print(f"     Title: {article.get('title', 'N/A')[:80]}...")
                print(f"     Source: {article.get('source', 'N/A')}")
                print(f"     Type: {article.get('source_type', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Article selector test failed: {e}")
        return False


def main():
    """Main setup and testing function."""
    print("🔧 NewsAPI.org Integration Setup")
    print("=" * 40)
    
    # Check API key
    api_key_ok = check_newsapi_key()
    
    # Check configuration
    config_ok = check_configuration()
    
    if api_key_ok:
        # Test connection
        connection_ok = test_newsapi_connection()
        
        if connection_ok and config_ok:
            # Test article selector
            selector_ok = test_article_selector()
            
            if selector_ok:
                print("\n🎉 Setup Complete!")
                print("   Your enhanced article selection system is ready to use.")
                print("   The system will now use NewsAPI.org for robust article discovery,")
                print("   with intelligent ranking and source diversity.")
                print("\n🔥 New Feature: Headlines Context for Gemini")
                print("   - Gemini now uses trending headlines to better prioritize stories")
                print("   - Only fetches headlines for priority topics to save quota")
                print("   - Provides broader context about current news landscape")
                print("\n📊 Free Tier Management:")
                print("   - Daily limit: 100 requests (using 80 for safety buffer)")
                print("   - Aggressive caching enabled (1-hour cache)")
                print("   - Priority topics: TOP_NEWS, TECHNOLOGY, BUSINESS")
                print("   - Headlines context: Priority topics only")
                print("   - Monitor usage: python monitor_quota.py")
            else:
                print("\n⚠️  Setup partially complete")
                print("   API connection works, but article selector has issues.")
        else:
            print("\n⚠️  Setup incomplete")
            print("   Please check your API key and configuration.")
    else:
        print("\n📝 Next Steps:")
        print("   1. Get a NewsAPI.org API key")
        print("   2. Set the NEWSAPI_KEY environment variable")
        print("   3. Run this script again to test the connection")


if __name__ == "__main__":
    main() 