"""Main aggregator for the news system that orchestrates all components."""

import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from newsaggregator.config.settings import (
    RSS_FEEDS, REQUEST_DELAY,
    COMBINED_DIR, USE_NEWSAPI_FOR_DISCOVERY,
    MAX_CONCURRENT_ARTICLE_FETCHES
)
from newsaggregator.fetchers.rss_fetcher import RSSFetcher
from newsaggregator.processors.article_processor import ArticleProcessor
from newsaggregator.selectors.article_selector import ArticleSelector
from newsaggregator.processors.gemini_processor import GeminiProcessor
from newsaggregator.storage.file_storage import FileStorage
from newsaggregator.storage.firebase_storage import FirebaseStorage
from newsaggregator.utils.rate_limiter import RateLimiter

class NewsAggregator:
    """Main aggregator class that orchestrates the news collection and processing."""
    
    def __init__(self):
        """Initialize the news aggregator system."""
        self.running = True
        self.rss_fetcher = RSSFetcher()
        self.article_processor = ArticleProcessor()
        self.gemini_processor = GeminiProcessor()
        self.article_selector = ArticleSelector()
        self.article_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ARTICLE_FETCHES)
        self.article_rate_limiter = RateLimiter(REQUEST_DELAY)
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Initialize Firebase
        self.db = FirebaseStorage.initialize()
        if not self.db:
            print("Warning: Proceeding without Firestore integration")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        print("\nShutdown signal received. Completing current tasks...")
        self.running = False
    
    def process_feeds(self):
        """Process feeds for all topics using enhanced article selection.
        
        Returns:
            Dictionary of new articles by topic
        """
        new_articles_by_topic = {}
        
        # Get quota-optimized topics to stay within free tier limits
        if USE_NEWSAPI_FOR_DISCOVERY:
            topics = self.article_selector.get_quota_optimized_topics()
            print(f"🎯 Processing {len(topics)} quota-optimized topics: {topics}")
        else:
            topics = self.article_selector.get_available_topics()
        
        for topic in topics:
            print(f"\nProcessing {topic} articles...")
            
            if USE_NEWSAPI_FOR_DISCOVERY:
                # Use enhanced article selection with NewsAPI.org + RSS
                selected_articles = self.article_selector.select_best_articles_for_topic(topic)
            else:
                # Fallback to traditional RSS-only method
                feed_url = RSS_FEEDS.get(topic)
                if not feed_url:
                    continue
                    
                print(f"Using RSS-only method for {topic}...")
                feed = self.rss_fetcher.fetch_feed(feed_url)
                if not feed:
                    continue
                    
                entries = self.rss_fetcher.extract_entries(feed)
                selected_articles = []
                for entry in entries:
                    selected_articles.append({
                        'url': entry.get('url'),
                        'title': entry.get('title'),
                        'source': entry.get('source'),
                        'date': entry.get('date'),
                        'description': '',
                        'source_type': 'rss'
                    })
            
            # Process selected articles
            new_articles_by_topic[topic] = []
            processed_count = 0
            futures = []

            for article in selected_articles:
                # Validate article quality
                is_valid, issues = self.article_selector.validate_article_quality(article)
                if not is_valid:
                    print(f"Skipping invalid article: {', '.join(issues)}")
                    continue

                # Convert to entry format for processing
                entry = {
                    'url': article.get('url'),
                    'title': article.get('title'),
                    'source': article.get('source'),
                    'date': article.get('date')
                }

                futures.append(
                    self.article_executor.submit(self._process_article_task, entry, topic)
                )

            for future in as_completed(futures):
                try:
                    article_data = future.result()
                except Exception as exc:
                    print(f"[ERROR] Article processing failed: {exc}")
                    continue

                if article_data:
                    new_articles_by_topic[topic].append(article_data)
                    processed_count += 1
            
            # Generate source diversity report
            if new_articles_by_topic[topic]:
                diversity_report = self.article_selector.get_source_diversity_report(selected_articles)
                print(f"Source diversity for {topic}: {dict(list(diversity_report.items())[:5])}")
        
        return new_articles_by_topic
    
    def generate_summaries(self):
        """Generate summaries for each topic.
        
        Returns:
            Dictionary of summaries by topic
        """
        print("\nGenerating news summaries...")
        summaries = {}
        
        for topic in RSS_FEEDS.keys():
            try:
                print(f"\nProcessing {topic}...")

                # Get the combined file path for this topic
                combined_file = Path(COMBINED_DIR) / FileStorage.get_combined_filename(topic)

                if not combined_file.exists():
                    print(f"No combined file found for topic: {topic}")
                    continue

                # Read the combined file content
                with open(combined_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Generate summary using Gemini
                summary = self.gemini_processor.generate_chunked_summary(content, topic)

                if summary:
                    # Add detailed content to each story
                    summary = self.article_processor.process_for_summary(summary)

                    # Generate brief summary
                    try:
                        brief_data = self.gemini_processor.generate_brief_summary(
                            summary.get('Summary', ''), topic
                        )

                        if brief_data:
                            summary['brief_summary'] = brief_data.get('BriefSummary', '')
                            summary['bullet_points'] = brief_data.get('BulletPoints', [])
                    except Exception as e:
                        print(f"[WARNING] Failed to generate brief summary for {topic} after all retries: {e}")
                        print(f"[INFO] Continuing with full summary only")

                    # Save summary to storage
                    FileStorage.save_summary(summary, topic)

                    # Upload to Firestore if available
                    if self.db:
                        FirebaseStorage.upload_to_firestore(summary, topic)

                    summaries[topic] = summary
                else:
                    print(f"[WARNING] No summary generated for {topic}")

            except Exception as e:
                print(f"[ERROR] Failed to process summary for {topic} after all retries: {e}")
                print(f"[INFO] Continuing with remaining topics")
                continue
        
        return summaries
    
    def run(self):
        """Run the news aggregation process as a single execution."""
        # Initialize
        print(f"Starting news aggregation process at {datetime.now()}")
        self.article_processor.load_state()
        
        try:
            # Process feeds for all topics
            new_articles_by_topic = self.process_feeds()
            
            # Log processed articles
            total_new_articles = sum(len(articles) for articles in new_articles_by_topic.values())
            print(f"\nAdded {total_new_articles} new articles across all topics")
            for topic, articles in new_articles_by_topic.items():
                if articles:
                    print(f"- {topic}: {len(articles)} articles")
            
            # Generate summaries for each topic
            summaries = self.generate_summaries()
            FileStorage.save_last_summary_time(time.time())
            
            # Log summary generation
            print(f"\nGenerated summaries for {len(summaries)} topics")
            for topic in summaries.keys():
                print(f"- {topic}: Summary generated")
                
            print(f"\nNews aggregation process completed at {datetime.now()}")
            
        except Exception as e:
            print(f"Error during news aggregation: {str(e)}")
            raise
            
        finally:
            print("\nSaving final state...")
            self.article_processor.save_state()
            print("Process complete")
            self.article_executor.shutdown(wait=True)

    def _process_article_task(self, entry, topic):
        """Process a single article task using shared rate limiting."""
        self.article_rate_limiter.acquire()
        article_data, success = self.article_processor.process_article(entry, topic)
        return article_data if success else None
