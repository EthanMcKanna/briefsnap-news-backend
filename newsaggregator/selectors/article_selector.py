"""Enhanced article selector that combines multiple sources for robust discovery."""

import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from newsaggregator.config.settings import (
    RSS_FEEDS, REQUEST_DELAY, USE_NEWSAPI_FOR_DISCOVERY, 
    NEWSAPI_FALLBACK_TO_RSS, ARTICLE_QUALITY_THRESHOLD, NEWSAPI_KEY,
    TOPICS_PER_CYCLE, TOPIC_COOLDOWN_SECONDS, TOPIC_ROTATION_FILE,
    TITLE_SIMILARITY_THRESHOLD
)
from newsaggregator.fetchers.rss_fetcher import RSSFetcher
from newsaggregator.fetchers.newsapi_fetcher import NewsAPIFetcher
from newsaggregator.utils.topic_rotation import TopicRotationManager
from newsaggregator.utils.similarity import clean_text_for_comparison, calculate_similarity


class ArticleSelector:
    """Enhanced article selector that combines NewsAPI.org and RSS feeds for robust discovery."""
    
    def __init__(self):
        """Initialize the article selector with multiple sources."""
        self.rss_fetcher = RSSFetcher()
        self.topic_rotation = TopicRotationManager(TOPIC_ROTATION_FILE)
        self._fallback_source_rankings = self._get_fallback_source_rankings()
        
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
        seen_titles: List[str] = []
        
        # Process NewsAPI articles first (higher priority)
        for article in newsapi_articles:
            self._ingest_article(article, seen_articles, seen_titles, source_type='newsapi')
        
        # Process RSS articles, skipping duplicates
        for article in rss_articles:
            self._ingest_article(article, seen_articles, seen_titles, source_type='rss')
        
        return list(seen_articles.values())

    def _ingest_article(self, article: Dict, seen_articles: Dict[str, Dict], seen_titles: List[str], source_type: str):
        url = self._normalize_url(article.get('url'))
        if not url or url in seen_articles:
            return

        normalized_title = clean_text_for_comparison(article.get('title', ''))
        if normalized_title and self._should_skip_title(normalized_title, seen_titles):
            return

        article['source_type'] = source_type
        seen_articles[url] = article
        if normalized_title:
            seen_titles.append(normalized_title)
    
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
        used_fallback = True
        if hasattr(self.newsapi_fetcher, '_calculate_article_score') and article.get('source_type') == 'newsapi':
            try:
                base_score = self.newsapi_fetcher._calculate_article_score(article, topic)
                score += base_score
                used_fallback = False
            except Exception:
                used_fallback = True

        if used_fallback:
            score += self._calculate_fallback_score(article)
        
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
        if selected_articles:
            avg_score = sum(score for score, _ in scored_articles[:len(selected_articles)]) / len(selected_articles)
            print(f"Average quality score: {avg_score:.1f}")

        return selected_articles

    def get_rotating_topic_batch(self, available_topics: List[str], max_topics: Optional[int] = None) -> List[str]:
        """Return a topic batch honoring per-topic cooldown windows."""
        if not available_topics:
            return []

        limit = max_topics or TOPICS_PER_CYCLE
        return self.topic_rotation.get_next_batch(available_topics, limit, TOPIC_COOLDOWN_SECONDS)

    def mark_topics_processed(self, topics: List[str]):
        """Persist the last processed timestamp for topics."""
        self.topic_rotation.mark_processed(topics)
    
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

    def _normalize_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parts = urlparse(url)
            normalized = parts._replace(query='', fragment='')
            return urlunparse(normalized)
        except Exception:
            return url

    def _should_skip_title(self, candidate: str, seen_titles: List[str]) -> bool:
        for existing in seen_titles:
            if calculate_similarity(candidate, existing) >= TITLE_SIMILARITY_THRESHOLD:
                return True
        return False

    def _get_fallback_source_rankings(self) -> Dict[str, int]:
        return {
            'reuters.com': 100,
            'apnews.com': 95,
            'bbc.com': 90,
            'bbc.co.uk': 90,
            'cnn.com': 85,
            'nytimes.com': 85,
            'washingtonpost.com': 85,
            'wsj.com': 85,
            'theguardian.com': 85,
            'npr.org': 80,
            'abcnews.go.com': 80,
            'cbsnews.com': 80,
            'nbcnews.com': 80,
            'techcrunch.com': 75,
            'axios.com': 75,
            'politico.com': 75,
            'bloomberg.com': 75,
            'time.com': 70,
            'usatoday.com': 70,
            'forbes.com': 65,
            'cnbc.com': 65,
            'marketwatch.com': 60,
            'thehill.com': 60,
            'default': 50,
        }

    def _calculate_fallback_score(self, article: Dict) -> float:
        score = 10.0
        url = article.get('url', '')
        domain = urlparse(url).netloc.replace('www.', '').lower()
        reliability = self._fallback_source_rankings.get(domain, self._fallback_source_rankings['default'])
        score += (reliability / 100) * 40

        article_date = article.get('date') or article.get('publishedAt')
        if isinstance(article_date, str):
            try:
                article_date = datetime.fromisoformat(article_date.replace('Z', '+00:00'))
            except Exception:
                article_date = None

        if isinstance(article_date, datetime):
            if article_date.tzinfo:
                now = datetime.now(article_date.tzinfo)
            else:
                now = datetime.now()
            hours_old = max(0, (now - article_date).total_seconds() / 3600)
            recency_score = max(0, 1 - (hours_old / 24))
            score += recency_score * 25
        else:
            score += 10  # unknown recency, give moderate score

        title = article.get('title', '')
        if title:
            score += min(20, len(title.split()) * 2)
            clickbait_words = ['shocking', 'amazing', 'unbelievable', "you won't believe"]
            if any(word in title.lower() for word in clickbait_words):
                score -= 5

        description = article.get('description') or article.get('content')
        if description:
            if len(description) > 100:
                score += 8
            else:
                score += 4

        if article.get('author'):
            score += 3

        return score
