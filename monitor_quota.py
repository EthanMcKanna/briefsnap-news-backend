#!/usr/bin/env python3
"""
NewsAPI.org quota monitoring script.

This script provides real-time monitoring of NewsAPI quota usage,
cache statistics, and optimization recommendations.
"""

import os
import sys
from pathlib import Path
from datetime import datetime


def load_quota_manager():
    """Load the quota manager."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from newsaggregator.utils.quota_manager import NewsAPIQuotaManager
        return NewsAPIQuotaManager()
    except ImportError as e:
        print(f"❌ Failed to import quota manager: {e}")
        return None


def load_cache():
    """Load the cache manager."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from newsaggregator.utils.article_cache import ArticleCache
        return ArticleCache()
    except ImportError as e:
        print(f"❌ Failed to import cache: {e}")
        return None


def print_quota_status(quota_manager):
    """Print current quota status."""
    status = quota_manager.get_quota_status()
    
    print("📊 NewsAPI Quota Status")
    print("=" * 30)
    print(f"Daily Limit:      {status['daily_limit']}")
    print(f"Requests Made:    {status['requests_made']}")
    print(f"Remaining:        {status['remaining']}")
    print(f"Usage:            {status['percentage_used']:.1f}%")
    
    # Status indicator
    if status['percentage_used'] < 50:
        status_icon = "🟢"
        status_text = "Good"
    elif status['percentage_used'] < 80:
        status_icon = "🟡"
        status_text = "Warning"
    else:
        status_icon = "🔴"
        status_text = "Critical"
    
    print(f"Status:           {status_icon} {status_text}")
    
    if status['topics_processed']:
        print(f"Topics Processed: {', '.join(status['topics_processed'])}")


def print_cache_stats(cache):
    """Print cache statistics."""
    stats = cache.get_cache_stats()
    
    print("\n💾 Cache Statistics")
    print("=" * 30)
    print(f"Cache Enabled:    {'Yes' if stats['enabled'] else 'No'}")
    print(f"Total Files:      {stats['total_files']}")
    print(f"Total Articles:   {stats['total_articles']}")
    print(f"Cache Size:       {stats['cache_size_mb']} MB")
    
    if stats['oldest_cache']:
        oldest = datetime.fromisoformat(stats['oldest_cache'])
        print(f"Oldest Cache:     {oldest.strftime('%Y-%m-%d %H:%M')}")
    
    if stats['newest_cache']:
        newest = datetime.fromisoformat(stats['newest_cache'])
        print(f"Newest Cache:     {newest.strftime('%Y-%m-%d %H:%M')}")


def print_optimization_tips(quota_manager, cache):
    """Print optimization recommendations."""
    status = quota_manager.get_quota_status()
    cache_stats = cache.get_cache_stats()
    
    print("\n💡 Optimization Tips")
    print("=" * 30)
    
    tips = []
    
    # Quota-based tips
    if status['percentage_used'] > 80:
        tips.append("🔥 High quota usage! Consider reducing NEWSAPI_MAX_REQUESTS_PER_TOPIC")
        tips.append("📅 Spread requests throughout the day instead of batch processing")
    
    if status['percentage_used'] > 50:
        tips.append("⚡ Enable aggressive caching with NEWSAPI_CACHE_DURATION = 7200 (2 hours)")
        tips.append("🎯 Focus on priority topics: TOP_NEWS, TECHNOLOGY, BUSINESS")
    
    # Cache-based tips
    if not cache_stats['enabled']:
        tips.append("💾 Enable caching to reduce API calls: NEWSAPI_ENABLE_CACHING = True")
    elif cache_stats['total_files'] == 0:
        tips.append("📦 No cached articles found - cache will build up over time")
    elif cache_stats['total_files'] > 50:
        tips.append("🧹 Large cache detected - run cache cleanup periodically")
    
    # General tips
    if len(status['topics_processed']) > 5:
        tips.append("📊 Processing many topics - consider limiting to 3-4 priority topics")
    
    tips.append("🔄 Run the aggregator less frequently (every 2-3 hours instead of hourly)")
    tips.append("📈 Monitor quota daily to avoid hitting limits")
    
    for i, tip in enumerate(tips, 1):
        print(f"{i:2}. {tip}")


def estimate_daily_usage(quota_manager):
    """Estimate daily usage based on current patterns."""
    status = quota_manager.get_quota_status()
    
    print("\n📈 Usage Projection")
    print("=" * 30)
    
    current_hour = datetime.now().hour
    if current_hour > 0:
        hourly_rate = status['requests_made'] / current_hour
        projected_daily = hourly_rate * 24
        
        print(f"Current Rate:     {hourly_rate:.1f} requests/hour")
        print(f"Projected Daily:  {projected_daily:.0f} requests")
        
        if projected_daily > status['daily_limit']:
            print(f"⚠️  PROJECTION EXCEEDS LIMIT by {projected_daily - status['daily_limit']:.0f} requests")
        else:
            print(f"✅ Projection within limit ({status['daily_limit'] - projected_daily:.0f} requests buffer)")
    else:
        print("Not enough data for projection (early in the day)")


def run_cache_commands(cache, command):
    """Run cache management commands."""
    if command == "clear":
        cache.clear_all_cache()
        print("✅ Cache cleared")
    elif command == "cleanup":
        cache.clear_expired_cache()
        print("✅ Expired cache cleaned up")
    else:
        print(f"❌ Unknown cache command: {command}")
        print("Available commands: clear, cleanup")


def main():
    """Main monitoring function."""
    print("🔍 NewsAPI.org Quota Monitor")
    print("=" * 40)
    
    # Check if API key is configured
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        print("❌ NEWSAPI_KEY not found in environment variables")
        print("Set it with: export NEWSAPI_KEY='your-api-key'")
        return
    
    # Load managers
    quota_manager = load_quota_manager()
    cache = load_cache()
    
    if not quota_manager or not cache:
        print("❌ Failed to load quota manager or cache")
        return
    
    # Handle command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command in ["clear", "cleanup"]:
            run_cache_commands(cache, command)
            return
        elif command == "reset":
            quota_manager.reset_quota(force=True)
            print("✅ Quota reset (use with caution!)")
            return
        elif command == "help":
            print("\nAvailable commands:")
            print("  python monitor_quota.py          - Show status")
            print("  python monitor_quota.py clear    - Clear all cache")
            print("  python monitor_quota.py cleanup  - Clean expired cache")
            print("  python monitor_quota.py reset    - Reset quota (emergency)")
            return
    
    # Display status
    print_quota_status(quota_manager)
    print_cache_stats(cache)
    estimate_daily_usage(quota_manager)
    print_optimization_tips(quota_manager, cache)
    
    print(f"\n📅 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nRun 'python monitor_quota.py help' for available commands")


if __name__ == "__main__":
    main() 