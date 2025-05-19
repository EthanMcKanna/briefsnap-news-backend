"""Main aggregator for the news system that orchestrates all components."""

import time
import signal
from datetime import datetime
from pathlib import Path

from newsaggregator.config.settings import (
    RSS_FEEDS, REQUEST_DELAY,
    COMBINED_DIR
)
from newsaggregator.fetchers.rss_fetcher import RSSFetcher
from newsaggregator.processors.article_processor import ArticleProcessor
from newsaggregator.processors.gemini_processor import GeminiProcessor
from newsaggregator.storage.file_storage import FileStorage
from newsaggregator.storage.firebase_storage import FirebaseStorage

class NewsAggregator:
    """Main aggregator class that orchestrates the news collection and processing."""
    
    def __init__(self):
        """Initialize the news aggregator system."""
        self.running = True
        self.rss_fetcher = RSSFetcher()
        self.article_processor = ArticleProcessor()
        self.gemini_processor = GeminiProcessor()
        
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
        """Process feeds for all topics.
        
        Returns:
            Dictionary of new articles by topic
        """
        new_articles_by_topic = {}
        
        for topic, feed_url in RSS_FEEDS.items():
            print(f"\nChecking {topic} news feed...")
            feed = self.rss_fetcher.fetch_feed(feed_url)
            if not feed:
                continue

            new_articles_by_topic[topic] = []
            entries = self.rss_fetcher.extract_entries(feed)
            
            for entry in entries:
                article_data, success = self.article_processor.process_article(entry, topic)
                if success:
                    new_articles_by_topic[topic].append(article_data)
                time.sleep(REQUEST_DELAY)
        
        return new_articles_by_topic
    
    def generate_summaries(self):
        """Generate summaries for each topic.
        
        Returns:
            Dictionary of summaries by topic
        """
        print("\nGenerating news summaries...")
        summaries = {}
        
        for topic in RSS_FEEDS.keys():
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
            summary = self.gemini_processor.generate_summary(content, topic)
            
            if summary:
                # Add detailed content to each story
                summary = self.article_processor.process_for_summary(summary)
                
                # Generate brief summary
                brief_data = self.gemini_processor.generate_brief_summary(
                    summary.get('Summary', ''), topic
                )
                
                if brief_data:
                    summary['brief_summary'] = brief_data.get('BriefSummary', '')
                    summary['bullet_points'] = brief_data.get('BulletPoints', [])
                
                # Save summary to storage
                FileStorage.save_summary(summary, topic)
                
                # Upload to Firestore if available
                if self.db:
                    FirebaseStorage.upload_to_firestore(summary, topic)
                
                summaries[topic] = summary
        
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
            
            # Save processor state
            self.article_processor.save_state()
            
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