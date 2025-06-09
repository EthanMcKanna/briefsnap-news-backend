"""NewsAPI.org fetcher for robust article discovery and ranking."""

import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from typing import List, Dict, Optional, Tuple
from newsapi import NewsApiClient

from newsaggregator.config.settings import (
    REQUEST_DELAY, ARTICLES_PER_FEED, NEWSAPI_MAX_REQUESTS_PER_TOPIC
)
from newsaggregator.utils.quota_manager import NewsAPIQuotaManager
from newsaggregator.utils.article_cache import ArticleCache


class NewsAPIFetcher:
    """Class for fetching and ranking articles using NewsAPI.org for robust discovery."""
    
    def __init__(self, api_key: str):
        """Initialize the NewsAPI client.
        
        Args:
            api_key: NewsAPI.org API key
        """
        self.client = NewsApiClient(api_key=api_key)
        self.source_rankings = self._get_source_rankings()
        self.quota_manager = NewsAPIQuotaManager()
        self.cache = ArticleCache()
        
        # Clean up expired cache on initialization
        self.cache.clear_expired_cache()
    
    def _get_source_rankings(self) -> Dict[str, int]:
        """Get source rankings based on reliability and authority.
        
        Returns:
            Dictionary mapping source domains to ranking scores (higher = better)
        """
        # High-authority sources get higher scores
        return {
            # Tier 1: Premium news sources (score: 90-100)
            'reuters.com': 100,
            'apnews.com': 95,
            'bbc.com': 90,
            'bbc.co.uk': 90,
            
            # Tier 2: Major established news (score: 80-89)
            'cnn.com': 85,
            'nytimes.com': 85,
            'washingtonpost.com': 85,
            'wsj.com': 85,
            'theguardian.com': 85,
            'npr.org': 80,
            'abcnews.go.com': 80,
            'cbsnews.com': 80,
            'nbcnews.com': 80,
            
            # Tier 3: Specialized and regional (score: 70-79)
            'techcrunch.com': 75,
            'axios.com': 75,
            'politico.com': 75,
            'bloomberg.com': 75,
            'time.com': 70,
            'usatoday.com': 70,
            
            # Tier 4: Other reputable sources (score: 60-69)
            'forbes.com': 65,
            'cnbc.com': 65,
            'marketwatch.com': 60,
            'thehill.com': 60,
            
            # Default score for unknown sources
            'default': 50
        }
    
    def _get_source_score(self, url: str) -> int:
        """Get reliability score for a source based on URL.
        
        Args:
            url: Article URL
            
        Returns:
            Reliability score (higher = more reliable)
        """
        domain = urlparse(url).netloc.replace('www.', '').lower()
        return self.source_rankings.get(domain, self.source_rankings['default'])
    
    def _calculate_article_score(self, article: Dict, topic: str) -> float:
        """Calculate comprehensive score for article selection.
        
        Args:
            article: Article data from NewsAPI
            topic: Topic category
            
        Returns:
            Composite score for article ranking
        """
        score = 0.0
        
        # Source reliability (40% of score)
        source_score = self._get_source_score(article.get('url', ''))
        score += (source_score / 100) * 40
        
        # Recency (25% of score)
        published_at = article.get('publishedAt')
        if published_at:
            try:
                pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                hours_old = (datetime.now().replace(tzinfo=pub_date.tzinfo) - pub_date).total_seconds() / 3600
                
                # Fresher articles get higher scores (decay over 24 hours)
                recency_score = max(0, 1 - (hours_old / 24))
                score += recency_score * 25
            except:
                # If date parsing fails, give moderate recency score
                score += 10
        
        # Title quality (20% of score)
        title = article.get('title', '')
        if title:
            # Longer, more descriptive titles generally better
            title_score = min(20, len(title.split()) * 2)  # Cap at 20 points
            score += title_score
            
            # Penalty for clickbait indicators
            clickbait_words = ['shocking', 'amazing', 'unbelievable', 'you won\'t believe']
            if any(word in title.lower() for word in clickbait_words):
                score -= 5
        
        # Description quality (10% of score)
        description = article.get('description', '')
        if description and len(description) > 50:
            score += 10
        elif description:
            score += 5
        
        # Author presence (5% of score)
        if article.get('author'):
            score += 5
            
        return score
    
    def fetch_top_headlines(self, 
                           category: Optional[str] = None,
                           country: str = 'us',
                           sources: Optional[str] = None,
                           page_size: int = 100,
                           topic: str = None) -> List[Dict]:
        """Fetch top headlines from NewsAPI with caching and quota management.
        
        Args:
            category: News category (business, entertainment, general, health, science, sports, technology)
            country: Country code (us, gb, etc.)
            sources: Comma-separated string of source identifiers
            page_size: Number of articles to fetch
            topic: Topic name for caching and quota tracking
            
        Returns:
            List of normalized article dictionaries
        """
        # Check cache first
        cache_params = {'category': category, 'country': country, 'sources': sources}
        cached_articles = self.cache.get_cached_articles(topic or 'headlines', 'headlines', cache_params)
        if cached_articles:
            return cached_articles
        
        # Check quota before making request
        can_request, reason = self.quota_manager.can_make_request(topic)
        if not can_request:
            print(f"⚠️  Cannot make NewsAPI request: {reason}")
            return []
        
        try:
            print(f"🌐 Making NewsAPI request: top headlines for {topic or 'general'}")
            response = self.client.get_top_headlines(
                category=category,
                country=country,
                sources=sources,
                page_size=min(page_size, 100)  # API limit
            )
            
            # Record the request
            self.quota_manager.record_request(topic, 'headlines')
            
            if response['status'] == 'ok':
                articles = self._normalize_articles(response['articles'])
                
                # Cache the results
                self.cache.cache_articles(topic or 'headlines', 'headlines', articles, cache_params)
                
                return articles
            else:
                print(f"NewsAPI error: {response.get('message', 'Unknown error')}")
                return []
                
        except Exception as e:
            print(f"Error fetching top headlines: {e}")
            return []
    
    def fetch_everything(self,
                        query: Optional[str] = None,
                        sources: Optional[str] = None,
                        domains: Optional[str] = None,
                        from_date: Optional[str] = None,
                        to_date: Optional[str] = None,
                        sort_by: str = 'publishedAt',
                        page_size: int = 100,
                        topic: str = None) -> List[Dict]:
        """Fetch articles using the Everything endpoint with caching and quota management.
        
        Args:
            query: Keywords to search for
            sources: Comma-separated string of source identifiers
            domains: Comma-separated string of domains to search
            from_date: Date in YYYY-MM-DD format
            to_date: Date in YYYY-MM-DD format
            sort_by: Sort order (relevancy, popularity, publishedAt)
            page_size: Number of articles to fetch
            topic: Topic name for caching and quota tracking
            
        Returns:
            List of normalized article dictionaries
        """
        # Check cache first
        cache_params = {
            'query': query, 'sources': sources, 'domains': domains,
            'from_date': from_date, 'sort_by': sort_by
        }
        cached_articles = self.cache.get_cached_articles(topic or 'everything', 'everything', cache_params)
        if cached_articles:
            return cached_articles
        
        # Check quota before making request
        can_request, reason = self.quota_manager.can_make_request(topic)
        if not can_request:
            print(f"⚠️  Cannot make NewsAPI request: {reason}")
            return []
        
        try:
            print(f"🌐 Making NewsAPI request: everything for {topic or 'general'} (query: {query})")
            response = self.client.get_everything(
                q=query,
                sources=sources,
                domains=domains,
                from_param=from_date,
                to=to_date,
                sort_by=sort_by,
                page_size=min(page_size, 100)  # API limit
            )
            
            # Record the request
            self.quota_manager.record_request(topic, 'everything')
            
            if response['status'] == 'ok':
                articles = self._normalize_articles(response['articles'])
                
                # Cache the results
                self.cache.cache_articles(topic or 'everything', 'everything', articles, cache_params)
                
                return articles
            else:
                print(f"NewsAPI error: {response.get('message', 'Unknown error')}")
                return []
                
        except Exception as e:
            print(f"Error fetching everything: {e}")
            return []
    
    def _normalize_articles(self, articles: List[Dict]) -> List[Dict]:
        """Normalize article data to match existing format.
        
        Args:
            articles: Raw articles from NewsAPI
            
        Returns:
            List of normalized article dictionaries
        """
        normalized = []
        for article in articles:
            url = article.get('url')
            if not url:
                continue
                
            # Parse date
            published_at = article.get('publishedAt')
            date = None
            if published_at:
                try:
                    date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                except:
                    pass
            
            # Extract source name
            source_info = article.get('source', {})
            source = source_info.get('name', urlparse(url).netloc.replace('www.', ''))
            
            normalized.append({
                'url': url,
                'title': article.get('title', 'No Title'),
                'description': article.get('description', ''),
                'source': source,
                'author': article.get('author'),
                'date': date,
                'urlToImage': article.get('urlToImage'),
                'content': article.get('content'),
                'publishedAt': published_at
            })
            
        return normalized
    
    def get_curated_articles_for_topic(self, topic: str, max_articles: int = 20) -> List[Dict]:
        """Get curated, high-quality articles for a specific topic with quota management.
        
        Args:
            topic: Topic category
            max_articles: Maximum number of articles to return
            
        Returns:
            List of ranked and filtered articles
        """
        # Check quota status first
        quota_status = self.quota_manager.get_quota_status()
        if not quota_status['can_make_requests']:
            print(f"⚠️  NewsAPI quota exhausted for today ({quota_status['requests_made']}/{quota_status['daily_limit']})")
            return []
        
        all_articles = []
        requests_made = 0
        max_requests_for_topic = NEWSAPI_MAX_REQUESTS_PER_TOPIC
        
        # Map topic to NewsAPI category and search terms
        topic_mapping = {
            'TOP_NEWS': {'category': 'general', 'query': None},
            'WORLD': {'category': None, 'query': 'world news international'},
            'BUSINESS': {'category': 'business', 'query': 'business economy finance'},
            'TECHNOLOGY': {'category': 'technology', 'query': 'technology tech innovation'},
            'SCIENCE': {'category': 'science', 'query': 'science research discovery'},
            'HEALTH': {'category': 'health', 'query': 'health medical healthcare'},
            'SPORTS': {'category': 'sports', 'query': 'sports'},
            'ENTERTAINMENT': {'category': 'entertainment', 'query': 'entertainment'}
        }
        
        topic_config = topic_mapping.get(topic, {'category': None, 'query': topic.lower()})
        
        # Prioritize which endpoint to use based on available requests
        if max_requests_for_topic >= 2:
            # We can afford both endpoints
            
            # Fetch from top headlines if category available
            if topic_config['category'] and requests_made < max_requests_for_topic:
                headlines = self.fetch_top_headlines(
                    category=topic_config['category'],
                    page_size=50,
                    topic=topic
                )
                all_articles.extend(headlines)
                requests_made += 1
                time.sleep(REQUEST_DELAY)
            
            # Fetch from everything endpoint with search query
            if topic_config['query'] and requests_made < max_requests_for_topic:
                # Get articles from last 24 hours
                from_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                
                everything_articles = self.fetch_everything(
                    query=topic_config['query'],
                    from_date=from_date,
                    sort_by='popularity',
                    page_size=50,
                    topic=topic
                )
                all_articles.extend(everything_articles)
                requests_made += 1
                time.sleep(REQUEST_DELAY)
        
        else:
            # Limited requests - choose the best endpoint for this topic
            if topic_config['category']:
                # Prefer headlines for topics with specific categories
                headlines = self.fetch_top_headlines(
                    category=topic_config['category'],
                    page_size=100,  # Get more since we're only making one request
                    topic=topic
                )
                all_articles.extend(headlines)
                requests_made += 1
            elif topic_config['query']:
                # Use everything endpoint for topics without specific categories
                from_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                everything_articles = self.fetch_everything(
                    query=topic_config['query'],
                    from_date=from_date,
                    sort_by='popularity',
                    page_size=100,
                    topic=topic
                )
                all_articles.extend(everything_articles)
                requests_made += 1
        
        if not all_articles:
            print(f"No articles retrieved for {topic}")
            return []
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_articles.append(article)
        
        # Score and rank articles
        scored_articles = []
        for article in unique_articles:
            score = self._calculate_article_score(article, topic)
            scored_articles.append((score, article))
        
        # Sort by score (highest first) and return top articles
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        
        selected_articles = [article for score, article in scored_articles[:max_articles]]
        print(f"📰 Selected {len(selected_articles)} articles for {topic} using {requests_made} API requests")
        
        return selected_articles
    
    def get_reliable_sources_for_topic(self, topic: str) -> List[str]:
        """Get list of reliable sources for a specific topic.
        
        Args:
            topic: Topic category
            
        Returns:
            List of reliable source identifiers
        """
        # Topic-specific reliable sources
        topic_sources = {
            'TECHNOLOGY': ['techcrunch', 'ars-technica', 'wired', 'the-verge'],
            'BUSINESS': ['bloomberg', 'financial-times', 'fortune', 'reuters'],
            'SCIENCE': ['new-scientist', 'national-geographic', 'scientific-american'],
            'HEALTH': ['medical-news-today', 'webmd'],
            'SPORTS': ['espn', 'bbc-sport', 'the-sport-bible'],
            'ENTERTAINMENT': ['entertainment-weekly', 'variety', 'hollywood-reporter']
        }
        
        # General reliable sources for all topics
        general_sources = ['reuters', 'bbc-news', 'associated-press', 'cnn', 'abc-news']
        
        # Combine topic-specific and general sources
        sources = topic_sources.get(topic, []) + general_sources
        return sources[:10]  # Limit to 10 sources to stay within API limits 