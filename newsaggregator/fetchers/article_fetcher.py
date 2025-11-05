"""Article content fetcher for retrieving and parsing articles."""

import re
import time
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse

from newspaper import Article
from bs4 import BeautifulSoup
from googlenewsdecoder import new_decoderv1
from datetime import datetime
import requests

from newsaggregator.config.settings import REQUEST_TIMEOUT, MIN_ARTICLE_LENGTH
from newsaggregator.utils.http import get_headers

class ArticleFetcher:
    """Class for fetching and extracting article content."""

    _article_html_cache = OrderedDict()
    _image_validation_cache = OrderedDict()
    _session = requests.Session()
    _MAX_ARTICLE_CACHE = 128
    _MAX_IMAGE_CACHE = 256

    @classmethod
    def _cache_article_html(cls, url, html):
        if not url or not html:
            return

        cache = cls._article_html_cache
        if url in cache:
            cache.move_to_end(url)
        cache[url] = html

        if len(cache) > cls._MAX_ARTICLE_CACHE:
            cache.popitem(last=False)

    @classmethod
    def _get_cached_article_html(cls, url):
        if url in cls._article_html_cache:
            cls._article_html_cache.move_to_end(url)
            return cls._article_html_cache[url]
        return None

    @classmethod
    def _cache_image_validation_result(cls, image_url, result):
        cache = cls._image_validation_cache
        if image_url in cache:
            cache.move_to_end(image_url)
        cache[image_url] = result

        if len(cache) > cls._MAX_IMAGE_CACHE:
            cache.popitem(last=False)

    @classmethod
    def _get_cached_image_validation_result(cls, image_url):
        if image_url in cls._image_validation_cache:
            cls._image_validation_cache.move_to_end(image_url)
            return cls._image_validation_cache[image_url]
        return None

    @classmethod
    def extract_real_url_from_google(cls, google_url):
        """Extract the actual article URL from a Google News URL.
        
        Args:
            google_url: Google News URL
            
        Returns:
            Decoded URL or None if extraction fails
        """
        try:
            if 'news.google.com' in google_url:
                parsed = urlparse(google_url)
                query_params = parse_qs(parsed.query)

                candidate = query_params.get('url', [])
                if candidate:
                    real_url = candidate[0]
                    if real_url:
                        return real_url

                decoded_url = new_decoderv1(google_url, interval=0)
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
        headers = get_headers()
        with cls._session.get(archive_url, headers=headers) as response:
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
        with cls._session.get(top_result_url, headers=headers) as archived_content_response:
            if archived_content_response.status_code != 200:
                print(f"Failed to retrieve the top result page. Status code: {archived_content_response.status_code}")
                return None

            archived_html = archived_content_response.text
        
        # Use Newspaper3k to parse the archived content
        article = Article(top_result_url)
        article.download(input_html=archived_html)
        article.parse()

        if not article.text:
            print("No article text found using Newspaper3k.")
            return None

        cls._cache_article_html(url, archived_html)
        cls._cache_article_html(top_result_url, archived_html)

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

            cached_html = cls._get_cached_article_html(url)
            if cached_html:
                article.download(input_html=cached_html)
            else:
                article.download()

            if article.download_state == 2:  # ArticleDownloadState.SUCCESS
                article.parse()
                if article.html:
                    cls._cache_article_html(url, article.html)
                
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
    
    @classmethod
    def find_article_images(cls, url):
        """Extract all images from article URL sorted by importance.
        
        Args:
            url: URL of the article
            
        Returns:
            List of image URLs
        """
        try:
            article = Article(url)

            cached_html = cls._get_cached_article_html(url)
            if cached_html:
                article.download(input_html=cached_html)
            else:
                article.download()
            article.parse()
            if article.html:
                cls._cache_article_html(url, article.html)
            
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
        parsed_url = urlparse(image_url)
        path_parts = parsed_url.path.split('/')
        if len(path_parts) <= 3 and any(p in ['images', 'img', 'assets'] for p in path_parts):
            return True
            
        return False
        
    @classmethod
    def _is_valid_image_url(cls, image_url):
        """Quick validation to ensure an image URL is worth considering."""
        if not image_url:
            return False

        image_url = image_url.strip()
        if not image_url or image_url.startswith('data:'):
            return False

        parsed = urlparse(image_url)
        if not parsed.scheme:
            # Some feeds return URLs like //example.com/image.jpg
            image_url = f"https:{image_url}" if image_url.startswith('//') else image_url
            parsed = urlparse(image_url)

        if parsed.scheme not in ('http', 'https'):
            return False

        # Basic extension filtering
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.avif', '.gif'}
        path = parsed.path.lower()
        if '.' not in path:
            return False
        if not any(path.endswith(ext) for ext in valid_extensions):
            return False

        # Skip very short filenames that are commonly tracking pixels
        filename = path.split('/')[-1]
        if len(filename) <= 6:
            return False

        if cls.is_likely_logo(image_url):
            return False

        return True

    @classmethod
    def _score_image(cls, image_url):
        """Generate a heuristic score for how suitable an image might be."""
        score = 0
        url_lower = image_url.lower()

        positive_keywords = [
            'featured', 'feature', 'hero', 'lead', 'main', 'promo',
            'large', 'hd', 'wide', '1200', '1080', '2048', 'original',
            'media', 'article', 'story', 'content', 'uploads'
        ]
        negative_keywords = [
            'thumb', 'thumbnail', 'small', 'sm_', 'icon', 'placeholder',
            'default', 'sprite', 'banner', 'header', 'social', 'share',
            'avatar', 'profile', 'transparent', 'background', 'og-image',
            'meta-logo', 'masthead', 'brand', 'badge'
        ]

        for keyword in positive_keywords:
            if keyword in url_lower:
                score += 3
        for keyword in negative_keywords:
            if keyword in url_lower:
                score -= 4

        # Prefer HTTPS and avoid GIFs where possible
        if url_lower.startswith('https://'):
            score += 2
        if url_lower.endswith('.gif'):
            score -= 3

        # Reward likely high-resolution images based on dimensions in filename
        dimension_match = re.search(r'(\d{3,4})[xX](\d{3,4})', url_lower)
        if dimension_match:
            width, height = map(int, dimension_match.groups())
            if width >= 800 and height >= 500:
                score += 4
            elif width >= 600 and height >= 400:
                score += 2

        # Reward explicit width query parameters suggesting a large image
        width_match = re.search(r'(?:width|w)=([0-9]{3,4})', url_lower)
        if width_match and int(width_match.group(1)) >= 800:
            score += 2

        # Penalize URLs from known tracking hosts
        tracking_hosts = ['doubleclick.net', 'googlesyndication.com']
        host = urlparse(image_url).netloc.lower()
        if any(host.endswith(th) for th in tracking_hosts):
            score -= 6

        return score

    @classmethod
    def _rank_images(cls, image_urls):
        """Return candidate image URLs ordered by heuristic score."""
        seen = set()
        candidates = []

        for url in image_urls or []:
            if not url or url in seen:
                continue

            normalized_url = url.strip()
            if normalized_url.startswith('//'):
                normalized_url = f"https:{normalized_url}"

            if not cls._is_valid_image_url(normalized_url):
                continue

            seen.add(normalized_url)
            score = cls._score_image(normalized_url)
            candidates.append((score, normalized_url))

        # Sort by score descending then by URL to keep deterministic ordering
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [url for _, url in candidates]

    @classmethod
    def _url_returns_image(cls, image_url, timeout=10):
        """Check whether fetching an image URL returns image content."""
        cached = cls._get_cached_image_validation_result(image_url)
        if cached is not None:
            return cached

        result = False
        try:
            headers = get_headers()
            response = cls._session.head(image_url, headers=headers, timeout=timeout, allow_redirects=True)
            try:
                if response.status_code in (403, 405) or 'content-type' not in response.headers:
                    with cls._session.get(image_url, headers=headers, timeout=timeout, stream=True) as get_response:
                        content_type = get_response.headers.get('content-type', '')
                        if content_type.startswith('image/'):
                            content_length = get_response.headers.get('content-length')
                            if not content_length or int(content_length) >= 5 * 1024:
                                result = True
                else:
                    content_type = response.headers.get('content-type', '')
                    if content_type.startswith('image/'):
                        content_length = response.headers.get('content-length')
                        if not content_length or int(content_length) >= 5 * 1024:
                            result = True
            finally:
                response.close()
        except Exception:
            result = False

        cls._cache_image_validation_result(image_url, result)
        return result

    @classmethod
    def select_best_image(cls, image_urls, fallback_urls=None, max_fallback_articles=3):
        """Select the best image from a list of URLs with validation and fallbacks.

        Args:
            image_urls: Initial list of candidate image URLs
            fallback_urls: Optional list of article URLs to scrape for additional images
            max_fallback_articles: Number of fallback articles to inspect

        Returns:
            URL of the best image, or None if no viable image is found
        """
        ranked_candidates = cls._rank_images(image_urls)

        for url in ranked_candidates[:5]:
            if cls._url_returns_image(url):
                return url

        # If validation failed for all ranked candidates, try fallbacks from article pages
        if fallback_urls:
            fallback_candidates = list(ranked_candidates)

            for article_url in fallback_urls[:max_fallback_articles]:
                fallback_images = cls.find_article_images(article_url)
                fallback_candidates.extend(fallback_images)

            # Re-rank with the new fallback images included
            fallback_ranked = cls._rank_images(fallback_candidates)

            for url in fallback_ranked[:5]:
                if cls._url_returns_image(url):
                    return url

        # If nothing validated, fall back to the top-ranked candidate without validation
        if ranked_candidates:
            return ranked_candidates[0]

        return None
