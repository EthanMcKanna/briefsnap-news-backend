"""File-based storage for news articles and summaries."""

import os
import json
import hashlib
import time
from datetime import datetime
from pathlib import Path

from newsaggregator.config.settings import (
    OUTPUT_DIR, COMBINED_DIR, SUMMARY_DIR, 
    PROCESSED_ARTICLES_FILE, FAILED_URLS_FILE, LAST_SUMMARY_FILE
)
from newsaggregator.utils.similarity import is_same_day

class FileStorage:
    """Class for file-based storage operations."""
    
    @staticmethod
    def save_article(title, content, source, url, date, topic='TOP_NEWS'):
        """Save the article content to a text file.
        
        Args:
            title: Title of the article
            content: Full text content of the article
            source: Source name of the article
            url: URL of the article
            date: Publication date of the article
            topic: Topic of the article
        
        Returns:
            Filepath where the article was saved
        """
        # Create a unique filename using a hash to avoid duplicates
        hash_object = hashlib.md5(title.encode('utf-8'))
        filename_hash = hash_object.hexdigest()

        # Clean the title to create a readable part of the filename
        valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        clean_title = ''.join(c for c in title if c in valid_chars)
        clean_title = clean_title.replace(' ', '_')[:50]  # Limit filename length

        filename = f"{topic}_{source}_{clean_title}_{filename_hash}.txt"
        filepath = Path(OUTPUT_DIR) / filename

        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                file.write(f"Title: {title}\n")
                file.write(f"Source: {source}\n")
                file.write(f"Topic: {topic}\n")
                file.write(f"Date: {date.strftime('%Y-%m-%d %H:%M:%S') if date else 'Unknown'}\n")
                file.write(f"URL: {url}\n")
                file.write(f"Content:\n{content}")
            print(f"Saved article: {filepath}")
            return filepath
        except Exception as e:
            print(f"Failed to save article '{title}': {e}")
            return None
    
    @staticmethod
    def get_combined_filename(topic='TOP_NEWS'):
        """Return the combined filename for the current date and topic.
        
        Args:
            topic: Topic of the article
            
        Returns:
            Filename for the combined file
        """
        today = datetime.now().strftime("%Y%m%d")
        return f"combined_articles_{topic}_{today}.txt"
    
    @staticmethod
    def append_to_combined_file(article_data):
        """Append a single article to today's combined file if it's from today.
        
        Args:
            article_data: Tuple of (title, content, source, url, date, topic)
        """
        title, content, source, url, date, topic = article_data
        
        # Skip articles without dates or from different days
        if not date or not is_same_day(date, datetime.now()):
            return
        
        # Create topic-specific combined file
        filename = FileStorage.get_combined_filename(topic)
        filepath = Path(COMBINED_DIR) / filename
        
        # Create or append to the file
        mode = 'a' if filepath.exists() else 'w'
        with open(filepath, mode, encoding='utf-8') as file:
            if mode == 'w':
                file.write(f"Combined News Articles - {topic} - {datetime.now().strftime('%Y-%m-%d')}\n")
                file.write("="*80 + "\n\n")
            
            file.write(f"{'='*40} {source} {'='*40}\n")
            file.write(f"Title: {title}\n")
            file.write(f"Source: {source}\n")
            file.write(f"Topic: {topic}\n")
            file.write(f"Date: {date.strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"URL: {url}\n")
            file.write(f"Content:\n{content}\n")
            file.write("="*80 + "\n\n")
    
    @staticmethod
    def save_combined_articles(articles, topic='TOP_NEWS'):
        """Save all articles to a single combined file.
        
        Args:
            articles: List of tuples containing (title, content, source, url, date)
            topic: Topic of the articles
            
        Returns:
            Filepath of the saved file
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = Path(COMBINED_DIR) / f"combined_articles_{topic}_{timestamp}.txt"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                file.write(f"Combined News Articles - {topic} - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                file.write("="*80 + "\n\n")
                
                for title, content, source, url, date in articles:
                    file.write(f"{'='*40} {source} {'='*40}\n")
                    file.write(f"Title: {title}\n")
                    file.write(f"Source: {source}\n")
                    file.write(f"Date: {date.strftime('%Y-%m-%d %H:%M:%S') if date else 'Unknown'}\n")
                    file.write(f"URL: {url}\n")
                    file.write(f"Content:\n{content}\n")
                    file.write("="*80 + "\n\n")
                    
            print(f"\nSaved combined articles to: {filepath}")
            return filepath
        except Exception as e:
            print(f"Failed to save combined articles: {e}")
            return None
    
    @staticmethod
    def save_summary(summary_data, topic='TOP_NEWS'):
        """Save summary and stories to a file.
        
        Args:
            summary_data: Dictionary containing Summary and Stories fields
            topic: Topic of the summary
            
        Returns:
            Filepath of the saved file
        """
        filepath = Path(SUMMARY_DIR) / f"news_summary_{topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"News Summary - {topic} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            f.write("SUMMARY:\n")
            f.write(summary_data.get('Summary', '') + "\n\n")
            f.write("TOP STORIES:\n")
            for story in summary_data.get('Stories', []):
                f.write(f"\n{story.get('StoryTitle', '')}\n")
                f.write(f"{story.get('StoryDescription', '')}\n")
                f.write(f"{story.get('FullArticle', '')}\n")
                f.write("-"*40 + "\n")
            
        print(f"Saved summary to: {filepath}")
        return filepath
    
    @staticmethod
    def load_processed_articles():
        """Load the set of previously processed article URLs.
        
        Returns:
            Set of processed article URLs
        """
        try:
            with open(PROCESSED_ARTICLES_FILE, 'r') as f:
                return set(json.load(f))
        except FileNotFoundError:
            return set()
    
    @staticmethod
    def save_processed_articles(processed_urls):
        """Save the set of processed article URLs.
        
        Args:
            processed_urls: Set of processed article URLs
        """
        with open(PROCESSED_ARTICLES_FILE, 'w') as f:
            json.dump(list(processed_urls), f)
    
    @staticmethod
    def load_failed_urls():
        """Load failed URLs and their metadata.
        
        Returns:
            Dictionary of failed URLs and their metadata
        """
        try:
            with open(FAILED_URLS_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    @staticmethod
    def save_failed_urls(failed_urls):
        """Save failed URLs and their metadata.
        
        Args:
            failed_urls: Dictionary of failed URLs and their metadata
        """
        with open(FAILED_URLS_FILE, 'w') as f:
            json.dump(failed_urls, f, indent=2)
    
    @staticmethod
    def add_failed_url(failed_urls, url, reason):
        """Add URL to failed URLs with timestamp and reason.
        
        Args:
            failed_urls: Dictionary of failed URLs and their metadata
            url: URL that failed
            reason: Reason for failure
        """
        failed_urls[url] = {
            'timestamp': time.time(),
            'reason': reason
        }
    
    @staticmethod
    def get_last_summary_time():
        """Get timestamp of last summary generation.
        
        Returns:
            Timestamp as a float or 0 if not found
        """
        try:
            with open(LAST_SUMMARY_FILE, 'r') as f:
                return float(f.read().strip())
        except FileNotFoundError:
            return 0
    
    @staticmethod
    def save_last_summary_time(timestamp):
        """Save timestamp of last summary generation.
        
        Args:
            timestamp: Current timestamp as a float
        """
        with open(LAST_SUMMARY_FILE, 'w') as f:
            f.write(str(timestamp)) 