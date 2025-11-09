"""Article content processor for handling news article processing workflows."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

from newsaggregator.config.settings import (
    FAILED_URL_RETRY_INTERVAL,
    SUMMARY_ENRICHMENT_WORKERS
)
from newsaggregator.fetchers.article_fetcher import ArticleFetcher
from newsaggregator.fetchers.exa_fetcher import ExaFetcher
from newsaggregator.storage.file_storage import FileStorage
from newsaggregator.storage.firebase_storage import FirebaseStorage
from newsaggregator.utils.r2_storage import r2_storage

class ArticleProcessor:
    """Class for processing article content workflows."""
    
    def __init__(self):
        """Initialize the article processor."""
        self.article_fetcher = ArticleFetcher()
        self.exa_fetcher = ExaFetcher()
        self.processed_urls = set()
        self.failed_urls = {}
        self._state_lock = Lock()
        
    def load_state(self):
        """Load the processor state from storage."""
        with self._state_lock:
            self.processed_urls = FileStorage.load_processed_articles()
            self.failed_urls = FileStorage.load_failed_urls()
            processed = len(self.processed_urls)
            failed = len(self.failed_urls)
        print(f"Loaded {processed} processed and {failed} failed articles")

    def save_state(self):
        """Save the processor state to storage."""
        with self._state_lock:
            processed_copy = set(self.processed_urls)
            failed_copy = dict(self.failed_urls)
        FileStorage.save_processed_articles(processed_copy)
        FileStorage.save_failed_urls(failed_copy)
    
    def should_retry_url(self, url):
        """Check if enough time has passed to retry a failed URL.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL should be retried, False otherwise
        """
        with self._state_lock:
            entry = self.failed_urls.get(url)
        if not entry:
            return True

        elapsed = time.time() - entry['timestamp']
        return elapsed >= FAILED_URL_RETRY_INTERVAL
    
    def process_article(self, entry, topic):
        """Process a single article entry.
        
        Args:
            entry: Dictionary containing article metadata
            topic: Topic of the article
            
        Returns:
            Tuple of (article_data, success_flag) or (None, False) if processing fails
        """
        url = entry.get('url')
        if not url:
            return None, False
            
        # Skip if URL was processed or if it recently failed
        if not self._can_process_url(url):
            return None, False

        title = entry.get('title')
        source = entry.get('source')
        date = entry.get('date')

        try:
            # Extract content from the article URL
            content, article_date = self.article_fetcher.scrape_article_content(url)
            
            # Use article date if feed date is not available
            date = date or article_date

            if content:
                article_data = (title, content, source, url, date, topic)
                
                # Save to file storage
                FileStorage.save_article(title, content, source, url, date, topic)
                FileStorage.append_to_combined_file(article_data)
                
                # Mark as processed
                self._mark_url_processed(url)
                
                print(f"Added new {topic} article: {title}")
                return article_data, True
            else:
                self._add_failed_url(url, "Content extraction failed")
                print(f"Failed to extract content: {title}")
                return None, False
                
        except Exception as e:
            self._add_failed_url(url, str(e))
            print(f"Error processing article '{title}': {e}")
            return None, False
    
    def process_for_summary(self, summary_data):
        """Process stories in summary data to add detailed content.
        
        Args:
            summary_data: Dictionary with Summary and Stories fields
            
        Returns:
            Enhanced summary data with detailed article content
        """
        # Check for duplicates and collect unique stories
        unique_stories = []

        for story in summary_data.get('Stories', []):
            story['id'] = FirebaseStorage.generate_story_id()
            story_title = story.get('StoryTitle', '')
            story_description = story.get('StoryDescription', '')
            
            if story_title and FirebaseStorage.is_duplicate_article(story_title, story_description):
                print(f"Skipping duplicate story: {story_title}")
                continue

            unique_stories.append(story)

        if not unique_stories:
            summary_data['Stories'] = []
            return summary_data

        max_workers = min(SUMMARY_ENRICHMENT_WORKERS, len(unique_stories)) or 1

        if max_workers == 1:
            enriched = [self._enrich_story(story) for story in unique_stories]
        else:
            enriched_map = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._enrich_story, story): idx for idx, story in enumerate(unique_stories)}
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        enriched_map[idx] = future.result()
                    except Exception as exc:
                        story = unique_stories[idx]
                        print(f"[ERROR] Failed to enrich story '{story.get('StoryTitle', '')}': {exc}")

            enriched = [enriched_map.get(idx) for idx in range(len(unique_stories))]

        summary_data['Stories'] = [story for story in enriched if story]
        return summary_data

    def _can_process_url(self, url):
        with self._state_lock:
            if url in self.processed_urls:
                return False
            if url in self.failed_urls:
                elapsed = time.time() - self.failed_urls[url]['timestamp']
                if elapsed < FAILED_URL_RETRY_INTERVAL:
                    return False
        return True

    def _mark_url_processed(self, url):
        with self._state_lock:
            self.processed_urls.add(url)
            if url in self.failed_urls:
                del self.failed_urls[url]

    def _add_failed_url(self, url, reason):
        with self._state_lock:
            FileStorage.add_failed_url(self.failed_urls, url, reason)

    def _enrich_story(self, story):
        story_title = story.get('StoryTitle', '')

        if not story_title:
            return story

        detailed_article, citations, img_url, summary, key_points = self.exa_fetcher.fetch_detailed_article(story_title)
        story['FullArticle'] = detailed_article
        story['Citations'] = citations

        if summary:
            story['summary'] = summary
            print(f"[INFO] Generated summary for: {story_title}")

        if key_points:
            story['keyPoints'] = key_points
            print(f"[INFO] Generated {len(key_points)} key points for: {story_title}")

        if img_url:
            print(f"[INFO] Found image URL: {img_url}")
            try:
                r2_url = r2_storage.upload_image_from_url(img_url, story_title)
                if r2_url:
                    story['img_url'] = r2_url
                    print(f"[INFO] Uploaded image to R2: {r2_url}")
                else:
                    print(f"[WARNING] Failed to upload image to R2, using original URL: {img_url}")
                    story['img_url'] = img_url
            except Exception as e:
                print(f"[ERROR] Error uploading image to R2: {e}, using original URL: {img_url}")
                story['img_url'] = img_url

        return story
