"""Article content fetcher for retrieving and parsing articles."""

import time
from newspaper import Article
from bs4 import BeautifulSoup
from googlenewsdecoder import new_decoderv1
from datetime import datetime
import requests

from newsaggregator.config.settings import REQUEST_TIMEOUT, MIN_ARTICLE_LENGTH
from newsaggregator.utils.http import get_headers

class ArticleFetcher:
    """Class for fetching and extracting article content."""
    
    @staticmethod
    def extract_real_url_from_google(google_url):
        """Extract the actual article URL from a Google News URL.
        
        Args:
            google_url: Google News URL
            
        Returns:
            Decoded URL or None if extraction fails
        """
        try:
            if 'news.google.com' in google_url:
                decoded_url = new_decoderv1(google_url, interval=1)  # 1 second interval
                if decoded_url.get("status"):
                    return decoded_url["decoded_url"]
                print(f"Failed to decode Google News URL: {decoded_url.get('message', 'Unknown error')}")
                return None
            return google_url
        except Exception as e:
            print(f"Failed to extract real URL from Google News: {e}")
            return None
    
    @staticmethod
    def extract_date_from_nyt_url(url):
        """Extract date from NYT URL format YYYY/MM/DD.
        
        Args:
            url: NYT article URL
            
        Returns:
            Extracted datetime object or None
        """
        try:
            parts = url.split('/')
            if len(parts) >= 7:  # Enough parts for YYYY/MM/DD
                year = int(parts[3])
                month = int(parts[4])
                day = int(parts[5])
                return datetime(year, month, day)
        except (ValueError, IndexError):
            pass
        return None

    @classmethod
    def fetch_archived_page_text_nyt(cls, url):
        """Fetch archived NYT article content from archive.ph.
        
        Args:
            url: Original NYT article URL
            
        Returns:
            Dictionary with text content and date, or None if failed
        """
        date = cls.extract_date_from_nyt_url(url)
        
        # Construct the archive.ph URL
        archive_url = f"https://archive.ph/{url}"
        
        # Step 1: Open the archive page
        response = requests.get(archive_url, headers=get_headers())
        if response.status_code != 200:
            print(f"Failed to retrieve archive page. Status code: {response.status_code}")
            return None

        # Step 2: Parse the page to find the top search result link
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Locate the link within the 'TEXT-BLOCK' div
        text_block = soup.find("div", class_="TEXT-BLOCK")
        if not text_block:
            print("No TEXT-BLOCK found on archive page.")
            return None

        top_result_link = text_block.find("a", href=True)
        if not top_result_link:
            print("No link found in TEXT-BLOCK.")
            return None
        
        # Extract the URL of the top result
        top_result_url = top_result_link['href']
        print(f"Top result URL found: {top_result_url}")
        
        # Step 3: Open the top result link to retrieve the archived content
        archived_content_response = requests.get(top_result_url, headers=get_headers())
        if archived_content_response.status_code != 200:
            print(f"Failed to retrieve the top result page. Status code: {archived_content_response.status_code}")
            return None
        
        # Use Newspaper3k to parse the archived content
        article = Article(top_result_url)
        article.download()
        article.parse()
        
        if not article.text:
            print("No article text found using Newspaper3k.")
            return None
        
        return {'text': article.text, 'date': date}

    @classmethod
    def scrape_article_content(cls, url):
        """Scrape full text content and publish date from an article URL.
        
        Args:
            url: URL of the news article
            
        Returns:
            Tuple of (content, publish_date) or (None, None) if extraction fails
        """
        try:
            # Handle Google News URLs
            if 'news.google.com' in url:
                real_url = cls.extract_real_url_from_google(url)
                if not real_url:
                    return None, None
                url = real_url

            # Check if it's a NYT article
            if 'nytimes.com' in url:
                content = cls.fetch_archived_page_text_nyt(url)
                if content:
                    return content['text'], content['date']
                return None, None
            
            # For other articles, use newspaper3k
            article = Article(url)
            article.config.request_timeout = REQUEST_TIMEOUT
            article.config.browser_user_agent = get_headers()['User-Agent']
            article.download()
            
            if article.download_state == 2:  # ArticleDownloadState.SUCCESS
                article.parse()
                
                content = article.text
                publish_date = article.publish_date
                
                if content:
                    lines = [line.strip() for line in content.split('\n')]
                    content = '\n\n'.join(line for line in lines if line)
                    
                    if len(content) < MIN_ARTICLE_LENGTH:
                        print(f"Article content too short ({len(content)} chars), likely failed extraction")
                        return None, None
                        
                    return content, publish_date
                
            print(f"Failed to download article from {url}")
            return None, None
                
        except Exception as e:
            print(f"Failed to scrape {url}: {e}")
            return None, None
    
    @staticmethod
    def find_article_images(url):
        """Extract all images from article URL sorted by importance.
        
        Args:
            url: URL of the article
            
        Returns:
            List of image URLs
        """
        try:
            article = Article(url)
            article.download()
            article.parse()
            
            images = []
            
            # Add top image first if available
            if article.top_image:
                images.append(article.top_image)
                
            # Add all other images from the article
            for img in article.images:
                if img not in images:  # Avoid duplicates
                    images.append(img)
                    
            return images
        except Exception as e:
            print(f"[ERROR] Could not retrieve images from {url}: {e}")
            return []
            
    @staticmethod
    def is_likely_logo(image_url):
        """Check if an image URL is likely to be a logo rather than content image.
        
        Args:
            image_url: URL of the image to check
            
        Returns:
            True if the image is likely a logo, False otherwise
        """
        if not image_url:
            return True
            
        # Common patterns in logo URLs
        logo_patterns = [
            'logo', 'header', 'brand', 'icon', 'favicon', 'site-icon', 
            'wp-content/uploads/logo', '/assets/images/logo', 
            'masthead', 'navbar', 'footer'
        ]
        
        # Check if any logo pattern is in the URL
        url_lower = image_url.lower()
        for pattern in logo_patterns:
            if pattern in url_lower:
                return True
        
        # Check if image is at a path typically used for logos
        from urllib.parse import urlparse
        parsed_url = urlparse(image_url)
        path_parts = parsed_url.path.split('/')
        if len(path_parts) <= 3 and any(p in ['images', 'img', 'assets'] for p in path_parts):
            return True
            
        return False
        
    @classmethod
    def select_best_image(cls, image_urls):
        """Select the best image from a list of URLs based on simple heuristics.
        
        Args:
            image_urls: List of image URLs to choose from
            
        Returns:
            URL of the best image, or None if no good images
        """
        if not image_urls:
            return None
            
        # Filter out likely logos
        content_images = [url for url in image_urls if not cls.is_likely_logo(url)]
        
        # If we have any non-logo images, use the first one
        if content_images:
            return content_images[0]
            
        # If all images are likely logos, use the first one anyway
        if image_urls:
            return image_urls[0]
            
        return None 