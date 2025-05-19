"""Exa API fetcher for finding additional content about news stories."""

from datetime import datetime, timedelta
from exa_py import Exa
import google.generativeai as genai

from newsaggregator.config.settings import EXA_API_KEY, EXA_SEARCH_LIMIT, EXA_LOOKBACK_DAYS, GEMINI_API_KEY
from newsaggregator.fetchers.article_fetcher import ArticleFetcher

class ExaFetcher:
    """Class for fetching content from the Exa API."""
    
    def __init__(self):
        """Initialize the Exa API client."""
        self.client = Exa(api_key=EXA_API_KEY)
        
    def fetch_detailed_article(self, story_title):
        """Fetch a detailed article for a given story title using Exa API and Gemini.
        
        Args:
            story_title: Title of the story to fetch content for
            
        Returns:
            Tuple of (content, citations, image_url)
        """
        try:
            # Calculate date range for search (last N days)
            end_date = datetime.now().isoformat() + "Z"
            start_date = (datetime.now() - timedelta(days=EXA_LOOKBACK_DAYS)).isoformat() + "Z"
            
            print(f"[INFO] Searching Exa for: {story_title}")
            
            # Search for relevant articles using Exa
            search_response = self.client.search_and_contents(
                story_title,
                text=True,
                category="news",
                start_published_date=start_date,
                end_published_date=end_date,
                num_results=EXA_SEARCH_LIMIT
            )
            
            # Extract article contents from search results
            article_contents = []
            citations = []
            image_candidates = []
            
            # Process search results based on the actual structure
            if isinstance(search_response, dict) and 'data' in search_response:
                if 'results' in search_response['data']:
                    for result in search_response['data']['results']:
                        # Add citation URL
                        if result.get('url'):
                            citations.append(result['url'])
                        
                        # Add article content with source
                        article_text = f"Title: {result.get('title', 'No title')}\n\n"
                        if result.get('author'):
                            article_text += f"Author: {result.get('author')}\n\n"
                        article_text += result.get('text', '')
                        article_contents.append(article_text)
                        
                        # Get image if available
                        if result.get('image'):
                            image_candidates.append(result.get('image'))
            # Handle case where results are directly accessible
            elif hasattr(search_response, 'results'):
                for result in search_response.results:
                    # Extract URL from result
                    url = getattr(result, 'url', None)
                    if url:
                        citations.append(url)
                    
                    # Extract title and author
                    title = getattr(result, 'title', 'No title')
                    author = getattr(result, 'author', None)
                    text = getattr(result, 'text', '')
                    
                    # Add article content with source
                    article_text = f"Title: {title}\n\n"
                    if author:
                        article_text += f"Author: {author}\n\n"
                    article_text += text
                    article_contents.append(article_text)
                    
                    # Get image if available
                    if hasattr(result, 'image'):
                        image_candidates.append(result.image)
            
            if not article_contents:
                print(f"[ERROR] No Exa search results found for: {story_title}")
                # Try a more generic search if specific title search failed
                try:
                    # Extract key terms from title for broader search
                    keywords = ' '.join([word for word in story_title.split() if len(word) > 3])
                    print(f"[INFO] Retrying with broader search: {keywords}")
                    
                    search_response = self.client.search_and_contents(
                        keywords,
                        text=True,
                        category="news",
                        start_published_date=start_date,
                        end_published_date=end_date,
                        num_results=EXA_SEARCH_LIMIT
                    )
                    
                    # Process results from broader search (same logic as above)
                    search_results = search_response.to_dict() if hasattr(search_response, 'to_dict') else search_response
                    
                    if isinstance(search_results, dict) and 'data' in search_results and 'results' in search_results['data']:
                        for result in search_results['data']['results']:
                            if result.get('url'):
                                citations.append(result['url'])
                            
                            article_text = f"Title: {result.get('title', 'No title')}\n\n"
                            if result.get('author'):
                                article_text += f"Author: {result.get('author')}\n\n"
                            article_text += result.get('text', '')
                            article_contents.append(article_text)
                            
                            if result.get('image'):
                                image_candidates.append(result.get('image'))
                    elif hasattr(search_response, 'results'):
                        for result in search_response.results:
                            url = getattr(result, 'url', None)
                            if url:
                                citations.append(url)
                            
                            title = getattr(result, 'title', 'No title')
                            author = getattr(result, 'author', None)
                            text = getattr(result, 'text', '')
                            
                            article_text = f"Title: {title}\n\n"
                            if author:
                                article_text += f"Author: {author}\n\n"
                            article_text += text
                            article_contents.append(article_text)
                            
                            if hasattr(result, 'image'):
                                image_candidates.append(result.image)
                except Exception as search_error:
                    print(f"[ERROR] Broader search also failed: {search_error}")
            
            # Select the best image from the candidates
            best_image_url = ArticleFetcher.select_best_image(image_candidates)
            
            if not article_contents:
                # Still no results, generate content with Gemini but without reference articles
                print(f"[WARNING] No search results found, generating article without references")
                
                # Initialize Gemini
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel(
                    model_name="gemini-2.0-flash-lite",
                    generation_config={
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "top_k": 40,
                        "max_output_tokens": 2048,
                    }
                )
                
                prompt = f"""
                Write a comprehensive news article about "{story_title}".
                The article should be factual, well-structured, and written in an engaging journalistic style.
                Include relevant context and background information.
                """
                
                print(f"[INFO] Generating article with Gemini for: {story_title}")
                response = model.generate_content(prompt)
                article_text = response.text if response and hasattr(response, 'text') else ''
                if not article_text or not article_text.strip():
                    print(f"[WARNING] Skipping generated article with empty text for: {story_title}")
                    return '', [], best_image_url
                return article_text, [], best_image_url
            
            # Use Gemini to create article from the search results
            combined_text = "\n\n---\n\n".join(article_contents)
            
            # Initialize Gemini
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                generation_config={
                    "temperature": 1,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                }
            )
            
            prompt = f"""
            Based on the following news sources about "{story_title}", create a comprehensive news article. 
            The article should be factual, balanced, well-structured, and written in an engaging journalistic style.
            Do not mention that you're summarizing or that this information is from various sources.
            Do not include a title, just start with the first paragraph.
            Write as if you are a journalist who investigated the story firsthand.

            SOURCE INFORMATION:
            {combined_text}
            """
            
            print(f"[INFO] Generating article with Gemini for: {story_title}")
            response = model.generate_content(prompt)
            
            return response.text, citations, best_image_url
        except Exception as e:
            print(f"[ERROR] Failed to fetch detailed article for '{story_title}': {e}")
            # Print stack trace for debugging
            import traceback
            traceback.print_exc()
            return "", [], None 