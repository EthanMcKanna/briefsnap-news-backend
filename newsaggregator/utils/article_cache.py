"""Article caching system to reduce NewsAPI.org requests and improve efficiency."""

import json
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from newsaggregator.config.settings import (
    NEWSAPI_CACHE_DURATION, NEWSAPI_ENABLE_CACHING, DATA_DIR
)


class ArticleCache:
    """Caches NewsAPI.org results to minimize API requests."""
    
    def __init__(self):
        """Initialize the article cache."""
        self.cache_dir = DATA_DIR / 'newsapi_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_duration = NEWSAPI_CACHE_DURATION
        self.enabled = NEWSAPI_ENABLE_CACHING
    
    def _get_cache_key(self, topic: str, endpoint: str, params: Dict = None) -> str:
        """Generate a cache key for the request.
        
        Args:
            topic: Topic name
            endpoint: API endpoint (headlines, everything)
            params: Additional parameters
            
        Returns:
            Cache key string
        """
        # Create a unique key based on topic, endpoint, and key parameters
        key_data = {
            'topic': topic,
            'endpoint': endpoint,
            'date': datetime.now().strftime('%Y-%m-%d')  # Include date for daily refresh
        }
        
        if params:
            # Include relevant parameters but exclude time-sensitive ones
            filtered_params = {k: v for k, v in params.items() 
                             if k not in ['page', 'pageSize', 'apiKey']}
            key_data.update(filtered_params)
        
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_cache_file(self, cache_key: str) -> Path:
        """Get the cache file path for a given key.
        
        Args:
            cache_key: Cache key
            
        Returns:
            Path to cache file
        """
        return self.cache_dir / f"{cache_key}.json"
    
    def get_cached_articles(self, topic: str, endpoint: str, params: Dict = None) -> Optional[List[Dict]]:
        """Get cached articles if available and not expired.
        
        Args:
            topic: Topic name
            endpoint: API endpoint
            params: Request parameters
            
        Returns:
            Cached articles or None if not available/expired
        """
        if not self.enabled:
            return None
        
        cache_key = self._get_cache_key(topic, endpoint, params)
        cache_file = self._get_cache_file(cache_key)
        
        try:
            if not cache_file.exists():
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Check if cache is expired
            cached_time = cache_data.get('timestamp', 0)
            if time.time() - cached_time > self.cache_duration:
                # Cache expired, remove file
                cache_file.unlink()
                return None
            
            articles = cache_data.get('articles', [])
            print(f"📦 Using cached articles for {topic}/{endpoint}: {len(articles)} articles")
            return articles
            
        except Exception as e:
            print(f"Error reading cache for {topic}: {e}")
            # Remove corrupted cache file
            if cache_file.exists():
                cache_file.unlink()
            return None
    
    def cache_articles(self, topic: str, endpoint: str, articles: List[Dict], params: Dict = None):
        """Cache articles for future use.
        
        Args:
            topic: Topic name
            endpoint: API endpoint
            articles: Articles to cache
            params: Request parameters
        """
        if not self.enabled:
            return
        
        cache_key = self._get_cache_key(topic, endpoint, params)
        cache_file = self._get_cache_file(cache_key)
        
        try:
            cache_data = {
                'timestamp': time.time(),
                'topic': topic,
                'endpoint': endpoint,
                'articles': articles,
                'count': len(articles)
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, default=str)
            
            print(f"💾 Cached {len(articles)} articles for {topic}/{endpoint}")
            
        except Exception as e:
            print(f"Error caching articles for {topic}: {e}")
    
    def clear_expired_cache(self):
        """Remove expired cache files."""
        if not self.cache_dir.exists():
            return
        
        current_time = time.time()
        removed_count = 0
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                cached_time = cache_data.get('timestamp', 0)
                if current_time - cached_time > self.cache_duration:
                    cache_file.unlink()
                    removed_count += 1
                    
            except Exception:
                # Remove corrupted files
                cache_file.unlink()
                removed_count += 1
        
        if removed_count > 0:
            print(f"🧹 Cleaned up {removed_count} expired cache files")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        if not self.cache_dir.exists():
            return {
                'total_files': 0,
                'total_articles': 0,
                'cache_size_mb': 0,
                'oldest_cache': None,
                'newest_cache': None
            }
        
        cache_files = list(self.cache_dir.glob("*.json"))
        total_articles = 0
        cache_times = []
        total_size = 0
        
        for cache_file in cache_files:
            try:
                total_size += cache_file.stat().st_size
                
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                total_articles += cache_data.get('count', 0)
                cache_times.append(cache_data.get('timestamp', 0))
                
            except Exception:
                continue
        
        return {
            'total_files': len(cache_files),
            'total_articles': total_articles,
            'cache_size_mb': round(total_size / (1024 * 1024), 2),
            'oldest_cache': datetime.fromtimestamp(min(cache_times)).isoformat() if cache_times else None,
            'newest_cache': datetime.fromtimestamp(max(cache_times)).isoformat() if cache_times else None,
            'enabled': self.enabled
        }
    
    def clear_all_cache(self):
        """Clear all cached articles."""
        if not self.cache_dir.exists():
            return
        
        removed_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            removed_count += 1
        
        print(f"🗑️  Cleared all cache: {removed_count} files removed")
    
    def warm_cache_for_topics(self, topics: List[str]) -> Dict[str, bool]:
        """Check which topics have cached data available.
        
        Args:
            topics: List of topics to check
            
        Returns:
            Dictionary mapping topics to cache availability
        """
        cache_status = {}
        
        for topic in topics:
            # Check both endpoints
            headlines_cached = self.get_cached_articles(topic, 'headlines') is not None
            everything_cached = self.get_cached_articles(topic, 'everything') is not None
            
            cache_status[topic] = headlines_cached or everything_cached
        
        return cache_status 