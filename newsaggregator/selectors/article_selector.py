"""Enhanced article selector that combines multiple sources for robust article discovery."""

import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from newsaggregator.config.settings import (
    RSS_FEEDS, REQUEST_DELAY, USE_NEWSAPI_FOR_DISCOVERY, 
    NEWSAPI_FALLBACK_TO_RSS, ARTICLE_QUALITY_THRESHOLD, NEWSAPI_KEY
)
from newsaggregator.fetchers.rss_fetcher import RSSFetcher
from newsaggregator.fetchers.newsapi_fetcher import NewsAPIFetcher


class ArticleSelector:
    """Enhanced article selector that combines NewsAPI.org and RSS feeds for robust discovery."""
    
    def __init__(self):
        """Initialize the article selector with multiple sources."""
        self.rss_fetcher = RSSFetcher()
        
        # Initialize NewsAPI fetcher if API key is available
        self.newsapi_fetcher = None
        if NEWSAPI_KEY and USE_NEWSAPI_FOR_DISCOVERY:
            try:
                self.newsapi_fetcher = NewsAPIFetcher(NEWSAPI_KEY)
                quota_status = self.newsapi_fetcher.quota_manager.get_quota_status()
                print(f"NewsAPI.org integration enabled - {quota_status['remaining']}/{quota_status['daily_limit']} requests remaining")
            except Exception as e:
                print(f"Failed to initialize NewsAPI.org: {e}")
                if not NEWSAPI_FALLBACK_TO_RSS:
                    raise
    
    def _merge_and_deduplicate_articles(self, 
                                       newsapi_articles: List[Dict], 
                                       rss_articles: List[Dict]) -> List[Dict]:
        """Merge articles from different sources and remove duplicates.
        
        Args:
            newsapi_articles: Articles from NewsAPI.org
            rss_articles: Articles from RSS feeds
            
        Returns:
            Merged and deduplicated list of articles
        """
        # Create a dictionary to track articles by URL for deduplication
        seen_articles = {}
        
        # Process NewsAPI articles first (higher priority)
        for article in newsapi_articles:
            url = article.get('url')
            if url and url not in seen_articles:
                # Mark as from NewsAPI for scoring bonus
                article['source_type'] = 'newsapi'
                seen_articles[url] = article
        
        # Process RSS articles, skipping duplicates
        for article in rss_articles:
            url = article.get('url')
            if url and url not in seen_articles:
                article['source_type'] = 'rss'
                seen_articles[url] = article
        
        return list(seen_articles.values())
    
    def _calculate_enhanced_article_score(self, article: Dict, topic: str) -> float:
        """Calculate enhanced article score considering multiple factors.
        
        Args:
            article: Article data
            topic: Topic category
            
        Returns:
            Enhanced article score
        """
        score = 0.0
        
        # Base score from NewsAPI if available (use their scoring system)
        if hasattr(self.newsapi_fetcher, '_calculate_article_score'):
            try:
                base_score = self.newsapi_fetcher._calculate_article_score(article, topic)
                score += base_score
            except:
                # Fallback to basic scoring
                score = 50
        else:
            score = 50  # Default base score
        
        # Source type bonus
        source_type = article.get('source_type', 'rss')
        if source_type == 'newsapi':
            score += 10  # Bonus for NewsAPI articles (higher curation)
        
        # Additional quality indicators
        
        # URL quality (avoid suspicious domains)
        url = article.get('url', '')
        suspicious_domains = ['blogspot.', 'wordpress.', 'medium.com', 'linkedin.com']
        if any(domain in url.lower() for domain in suspicious_domains):
            score -= 5
        
        # Image presence
        if article.get('urlToImage'):
            score += 5
        
        # Content snippet quality (if available)
        content = article.get('content', '') or article.get('description', '')
        if content:
            # Longer content generally better
            if len(content) > 200:
                score += 5
            elif len(content) > 100:
                score += 2
            
            # Check for quality indicators
            quality_indicators = ['according to', 'reported', 'officials', 'sources']
            if any(indicator in content.lower() for indicator in quality_indicators):
                score += 3
        
        return score
    
    def select_best_articles_for_topic(self, topic: str, max_articles: int = 20) -> List[Dict]:
        """Select the best articles for a topic using multiple sources and ranking.
        
        Args:
            topic: Topic category
            max_articles: Maximum number of articles to return
            
        Returns:
            List of best articles ranked by quality
        """
        newsapi_articles = []
        rss_articles = []
        
        print(f"\nSelecting articles for {topic}...")
        
        # Fetch from NewsAPI.org if available
        if self.newsapi_fetcher:
            try:
                print(f"Fetching from NewsAPI.org for {topic}...")
                newsapi_articles = self.newsapi_fetcher.get_curated_articles_for_topic(
                    topic, max_articles * 2  # Get more to have better selection
                )
                print(f"Found {len(newsapi_articles)} articles from NewsAPI.org")
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"NewsAPI.org fetch failed for {topic}: {e}")
                if not NEWSAPI_FALLBACK_TO_RSS:
                    return []
        
        # Fetch from RSS feeds (either as fallback or supplement)
        if not newsapi_articles or NEWSAPI_FALLBACK_TO_RSS:
            print(f"Fetching from RSS feeds for {topic}...")
            feed_url = RSS_FEEDS.get(topic)
            if feed_url:
                try:
                    feed = self.rss_fetcher.fetch_feed(feed_url)
                    if feed:
                        rss_entries = self.rss_fetcher.extract_entries(feed)
                        # Convert RSS entries to article format
                        for entry in rss_entries:
                            rss_articles.append({
                                'url': entry.get('url'),
                                'title': entry.get('title'),
                                'source': entry.get('source'),
                                'date': entry.get('date'),
                                'description': '',  # RSS entries don't have descriptions
                                'source_type': 'rss'
                            })
                        print(f"Found {len(rss_articles)} articles from RSS")
                except Exception as e:
                    print(f"RSS fetch failed for {topic}: {e}")
        
        # Merge and deduplicate articles
        all_articles = self._merge_and_deduplicate_articles(newsapi_articles, rss_articles)
        
        if not all_articles:
            print(f"No articles found for {topic}")
            return []
        
        # Score and rank articles
        scored_articles = []
        for article in all_articles:
            score = self._calculate_enhanced_article_score(article, topic)
            
            # Only include articles above quality threshold
            if score >= ARTICLE_QUALITY_THRESHOLD:
                scored_articles.append((score, article))
        
        # Sort by score (highest first)
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        
        # Return top articles
        selected_articles = [article for score, article in scored_articles[:max_articles]]
        
        print(f"Selected {len(selected_articles)} high-quality articles for {topic}")
        if scored_articles:
            avg_score = sum(score for score, _ in scored_articles[:max_articles]) / len(selected_articles)
            print(f"Average quality score: {avg_score:.1f}")
        
        return selected_articles
    
    def get_available_topics(self) -> List[str]:
        """Get list of available topics for article selection.
        
        Returns:
            List of available topic categories
        """
        # Base topics from RSS feeds
        topics = list(RSS_FEEDS.keys())
        
        # Add additional topics supported by NewsAPI if available
        if self.newsapi_fetcher:
            additional_topics = ['SCIENCE', 'HEALTH', 'SPORTS', 'ENTERTAINMENT']
            for topic in additional_topics:
                if topic not in topics:
                    topics.append(topic)
        
        return topics
    
    def get_quota_optimized_topics(self, max_topics: int = None) -> List[str]:
        """Get topics optimized for current quota availability.
        
        Args:
            max_topics: Maximum number of topics to return
            
        Returns:
            List of prioritized topics based on quota
        """
        all_topics = self.get_available_topics()
        
        if not self.newsapi_fetcher:
            return all_topics[:max_topics] if max_topics else all_topics
        
        # Get quota-optimized recommendations
        recommended_topics = self.newsapi_fetcher.quota_manager.get_recommended_topics(
            all_topics, max_topics
        )
        
        # If we don't have enough quota for all topics, prioritize
        if len(recommended_topics) < len(all_topics):
            print(f"⚡ Quota optimization: Processing {len(recommended_topics)} priority topics")
            
        return recommended_topics
    
    def get_source_diversity_report(self, articles: List[Dict]) -> Dict[str, int]:
        """Generate a report on source diversity for selected articles.
        
        Args:
            articles: List of selected articles
            
        Returns:
            Dictionary mapping sources to article counts
        """
        source_counts = {}
        for article in articles:
            source = article.get('source', 'Unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        return source_counts
    
    def validate_article_quality(self, article: Dict) -> Tuple[bool, List[str]]:
        """Validate article quality and return issues if any.
        
        Args:
            article: Article to validate
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        # Required fields
        if not article.get('url'):
            issues.append("Missing URL")
        if not article.get('title'):
            issues.append("Missing title")
        if not article.get('source'):
            issues.append("Missing source")
        
        # Quality checks
        title = article.get('title', '')
        if len(title) < 10:
            issues.append("Title too short")
        
        # Check for placeholder content
        placeholder_phrases = ['lorem ipsum', '[removed]', 'this article', 'click here']
        content = (article.get('content', '') + ' ' + article.get('description', '')).lower()
        if any(phrase in content for phrase in placeholder_phrases):
            issues.append("Contains placeholder content")
        
        # URL validation
        url = article.get('url', '')
        if 'javascript:' in url or 'data:' in url:
            issues.append("Invalid URL scheme")
        
        return len(issues) == 0, issues 