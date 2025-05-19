"""RSS feed fetcher for retrieving news articles from RSS feeds."""

import time
import feedparser
from urllib.parse import urlparse
from datetime import datetime
from newsaggregator.config.settings import REQUEST_DELAY, ARTICLES_PER_FEED

class RSSFetcher:
    """Class for fetching and parsing RSS feeds."""
    
    @staticmethod
    def fetch_feed(feed_url):
        """Fetches and parses an RSS feed.
        
        Args:
            feed_url: URL of the RSS feed
            
        Returns:
            Parsed feed object or None if failed
        """
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo:
                print(f"Failed to parse feed: {feed_url}")
                return None
            return feed
        except Exception as e:
            print(f"Error fetching feed {feed_url}: {e}")
            return None
    
    @staticmethod
    def extract_entries(feed, limit=ARTICLES_PER_FEED):
        """Extract entries from a parsed feed.
        
        Args:
            feed: Parsed feed object
            limit: Maximum number of entries to extract
            
        Returns:
            List of entry dictionaries with normalized fields
        """
        if not feed or not hasattr(feed, 'entries'):
            return []
        
        normalized_entries = []
        for entry in feed.entries[:limit]:
            # Get URL
            url = entry.get('link')
            if not url:
                continue
                
            # Get source domain
            source = urlparse(url).netloc.replace('www.', '')
            
            # Get title
            title = entry.get('title', 'No Title')
            
            # Get date
            date = entry.get('published_parsed') or entry.get('updated_parsed')
            if date:
                date = datetime.fromtimestamp(time.mktime(date))
            
            normalized_entries.append({
                'url': url,
                'title': title,
                'source': source,
                'date': date
            })
            
        return normalized_entries 