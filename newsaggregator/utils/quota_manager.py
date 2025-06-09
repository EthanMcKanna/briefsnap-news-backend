"""Quota manager for NewsAPI.org to ensure free tier compliance."""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from newsaggregator.config.settings import (
    NEWSAPI_DAILY_QUOTA, NEWSAPI_QUOTA_BUFFER, DATA_DIR
)


class NewsAPIQuotaManager:
    """Manages NewsAPI.org request quota to stay within free tier limits."""
    
    def __init__(self):
        """Initialize the quota manager."""
        self.quota_file = DATA_DIR / 'newsapi_quota.json'
        self.daily_limit = int(NEWSAPI_DAILY_QUOTA * NEWSAPI_QUOTA_BUFFER)
        self.quota_data = self._load_quota_data()
    
    def _load_quota_data(self) -> Dict:
        """Load quota tracking data from file.
        
        Returns:
            Dictionary with quota tracking information
        """
        try:
            if self.quota_file.exists():
                with open(self.quota_file, 'r') as f:
                    data = json.load(f)
                    
                # Check if data is from today
                today = datetime.now().strftime('%Y-%m-%d')
                if data.get('date') == today:
                    return data
                    
            # Return fresh data for new day
            return {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'requests_made': 0,
                'requests_by_hour': {},
                'topics_processed': [],
                'last_reset': time.time()
            }
            
        except Exception as e:
            print(f"Error loading quota data: {e}")
            return {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'requests_made': 0,
                'requests_by_hour': {},
                'topics_processed': [],
                'last_reset': time.time()
            }
    
    def _save_quota_data(self):
        """Save quota tracking data to file."""
        try:
            # Ensure data directory exists
            self.quota_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.quota_file, 'w') as f:
                json.dump(self.quota_data, f, indent=2)
        except Exception as e:
            print(f"Error saving quota data: {e}")
    
    def can_make_request(self, topic: str = None) -> tuple[bool, str]:
        """Check if we can make a request without exceeding quota.
        
        Args:
            topic: Optional topic name for tracking
            
        Returns:
            Tuple of (can_make_request, reason_if_not)
        """
        current_requests = self.quota_data['requests_made']
        
        if current_requests >= self.daily_limit:
            return False, f"Daily quota exceeded ({current_requests}/{self.daily_limit})"
        
        # Check rate limiting (max 10 requests per hour for free tier)
        current_hour = datetime.now().strftime('%Y-%m-%d-%H')
        hourly_requests = self.quota_data['requests_by_hour'].get(current_hour, 0)
        
        if hourly_requests >= 10:
            return False, f"Hourly rate limit reached ({hourly_requests}/10)"
        
        return True, "OK"
    
    def record_request(self, topic: str = None, endpoint: str = None):
        """Record a successful API request.
        
        Args:
            topic: Topic the request was for
            endpoint: API endpoint used (headlines, everything)
        """
        self.quota_data['requests_made'] += 1
        
        # Track hourly requests
        current_hour = datetime.now().strftime('%Y-%m-%d-%H')
        if current_hour not in self.quota_data['requests_by_hour']:
            self.quota_data['requests_by_hour'][current_hour] = 0
        self.quota_data['requests_by_hour'][current_hour] += 1
        
        # Track topics
        if topic and topic not in self.quota_data['topics_processed']:
            self.quota_data['topics_processed'].append(topic)
        
        self._save_quota_data()
        
        print(f"📊 NewsAPI quota: {self.quota_data['requests_made']}/{self.daily_limit} requests used today")
    
    def get_quota_status(self) -> Dict:
        """Get current quota status.
        
        Returns:
            Dictionary with quota information
        """
        remaining = self.daily_limit - self.quota_data['requests_made']
        percentage_used = (self.quota_data['requests_made'] / self.daily_limit) * 100
        
        return {
            'requests_made': self.quota_data['requests_made'],
            'daily_limit': self.daily_limit,
            'remaining': remaining,
            'percentage_used': percentage_used,
            'topics_processed': self.quota_data['topics_processed'],
            'can_make_requests': remaining > 0
        }
    
    def get_recommended_topics(self, available_topics: list, max_topics: int = None) -> list:
        """Get recommended topics to process based on quota and priority.
        
        Args:
            available_topics: List of all available topics
            max_topics: Maximum number of topics to recommend
            
        Returns:
            List of recommended topics
        """
        from newsaggregator.config.settings import NEWSAPI_PRIORITY_TOPICS
        
        status = self.get_quota_status()
        
        if not status['can_make_requests']:
            return []
        
        # Calculate how many topics we can afford
        remaining_requests = status['remaining']
        
        # Reserve some requests for priority topics
        if max_topics is None:
            max_topics = min(remaining_requests, len(available_topics))
        
        # Prioritize topics
        priority_topics = [t for t in NEWSAPI_PRIORITY_TOPICS if t in available_topics]
        other_topics = [t for t in available_topics if t not in NEWSAPI_PRIORITY_TOPICS]
        
        # Start with priority topics, then add others
        recommended = priority_topics[:max_topics]
        
        if len(recommended) < max_topics:
            remaining_slots = max_topics - len(recommended)
            recommended.extend(other_topics[:remaining_slots])
        
        return recommended[:max_topics]
    
    def reset_quota(self, force: bool = False):
        """Reset daily quota (automatically happens daily).
        
        Args:
            force: Force reset even if not a new day
        """
        today = datetime.now().strftime('%Y-%m-%d')
        
        if force or self.quota_data.get('date') != today:
            self.quota_data = {
                'date': today,
                'requests_made': 0,
                'requests_by_hour': {},
                'topics_processed': [],
                'last_reset': time.time()
            }
            self._save_quota_data()
            print(f"📅 NewsAPI quota reset for {today}")
    
    def estimate_requests_needed(self, topics: list) -> int:
        """Estimate how many requests will be needed for given topics.
        
        Args:
            topics: List of topics to process
            
        Returns:
            Estimated number of requests
        """
        from newsaggregator.config.settings import NEWSAPI_MAX_REQUESTS_PER_TOPIC
        
        return len(topics) * NEWSAPI_MAX_REQUESTS_PER_TOPIC 