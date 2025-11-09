"""Gemini API processor for generating summaries and articles."""

import json
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content

from newsaggregator.utils.retry import smart_retry_with_backoff, api_manager
from newsaggregator.config.settings import (
    TOPIC_PROMPTS, DEFAULT_PROMPT,
    BRIEF_GENERATION_CONFIG, NEWSAPI_KEY, USE_NEWSAPI_FOR_DISCOVERY,
    NEWSAPI_HEADLINES_CONTEXT, NEWSAPI_MIN_QUOTA_FOR_HEADLINES,
    SUMMARY_CHUNK_MAX_CHARS
)
from newsaggregator.utils.chunking import chunk_text

class GeminiProcessor:
    """Class for processing news data with Google's Gemini API."""
    
    def __init__(self):
        """Initialize the Gemini API client."""
        self.configure_gemini()
        self.chat_session = None
        self.brief_chat_session = None
        self.weekly_chat_session = None
        
        # Initialize NewsAPI fetcher for headlines context
        self.newsapi_fetcher = None
        if NEWSAPI_KEY and USE_NEWSAPI_FOR_DISCOVERY and NEWSAPI_HEADLINES_CONTEXT:
            try:
                from newsaggregator.fetchers.newsapi_fetcher import NewsAPIFetcher
                self.newsapi_fetcher = NewsAPIFetcher(NEWSAPI_KEY)
                print("📰 Headlines context enabled for Gemini summary generation")
            except Exception as e:
                print(f"Warning: Could not initialize NewsAPI for headlines context: {e}")
        
    def configure_gemini(self):
        """Configure the Gemini API client."""
        # The API manager handles configuration automatically
        pass
    
    def setup_gemini(self):
        """Configure and return Gemini model for summaries.
        
        Returns:
            Gemini chat session
        """
        if self.chat_session:
            return self.chat_session
            
        generation_config = {
            "temperature": 1.5,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_schema": content.Schema(
                type=content.Type.OBJECT,
                required=["Summary", "Stories"],
                properties={
                    "Stories": content.Schema(
                        type=content.Type.ARRAY,
                        items=content.Schema(
                            type=content.Type.OBJECT,
                            required=["StoryTitle", "StoryDescription"],
                            properties={
                                "StoryTitle": content.Schema(
                                    type=content.Type.STRING,
                                ),
                                "StoryDescription": content.Schema(
                                    type=content.Type.STRING,
                                ),
                            },
                        ),
                    ),
                    "Summary": content.Schema(
                        type=content.Type.STRING,
                    ),
                },
            ),
            "response_mime_type": "application/json",
        }
        
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-preview-05-20",
            generation_config=generation_config,
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        self.chat_session = model.start_chat()
        return self.chat_session
    
    def setup_brief_gemini(self):
        """Configure and return Gemini model for brief summaries.
        
        Returns:
            Gemini chat session for brief summaries
        """
        if self.brief_chat_session:
            return self.brief_chat_session
            
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-lite",
            generation_config=BRIEF_GENERATION_CONFIG,
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        self.brief_chat_session = model.start_chat()
        return self.brief_chat_session
    
    def get_trending_headlines_context(self, topic):
        """Get trending headlines from NewsAPI to provide context for summary generation.
        
        Args:
            topic: The topic to get headlines for
            
        Returns:
            String containing formatted headlines for context, or empty string if unavailable
        """
        if not self.newsapi_fetcher:
            return ""
        
        # Only fetch headlines for priority topics to conserve quota
        from newsaggregator.config.settings import NEWSAPI_PRIORITY_TOPICS
        if topic not in NEWSAPI_PRIORITY_TOPICS:
            print(f"Skipping headlines context for {topic} - not in priority topics")
            return ""
        
        try:
            # Map topics to NewsAPI categories for headlines
            topic_mapping = {
                'TOP_NEWS': {'category': 'general'},
                'WORLD': {'category': None, 'query': 'world news'},
                'BUSINESS': {'category': 'business'},
                'TECHNOLOGY': {'category': 'technology'},
                'SCIENCE': {'category': 'science'},
                'HEALTH': {'category': 'health'},
                'SPORTS': {'category': 'sports'},
                'ENTERTAINMENT': {'category': 'entertainment'}
            }
            
            topic_config = topic_mapping.get(topic, {'category': None})
            headlines = []
            
            # Try to get headlines without consuming too much quota
            # Check if we have quota available
            quota_status = self.newsapi_fetcher.quota_manager.get_quota_status()
            if quota_status['remaining'] < NEWSAPI_MIN_QUOTA_FOR_HEADLINES:
                print(f"Skipping headlines context for {topic} - low quota ({quota_status['remaining']} remaining, need {NEWSAPI_MIN_QUOTA_FOR_HEADLINES})")
                return ""
            
            if topic_config['category']:
                # Use top headlines endpoint
                articles = self.newsapi_fetcher.fetch_top_headlines(
                    category=topic_config['category'],
                    page_size=15,  # Get fewer headlines to save quota
                    topic=f"{topic}_headlines"
                )
                headlines.extend([article.get('title', '') for article in articles if article.get('title')])
            
            elif topic_config.get('query'):
                # Use everything endpoint with search
                from datetime import datetime, timedelta
                from_date = (datetime.now() - timedelta(hours=12)).strftime('%Y-%m-%d')
                
                articles = self.newsapi_fetcher.fetch_everything(
                    query=topic_config['query'],
                    from_date=from_date,
                    sort_by='popularity',
                    page_size=15,
                    topic=f"{topic}_headlines"
                )
                headlines.extend([article.get('title', '') for article in articles if article.get('title')])
            
            if headlines:
                # Remove duplicates and filter out very similar headlines
                unique_headlines = []
                for headline in headlines[:15]:  # Process more to filter better
                    # Simple deduplication - avoid headlines that are too similar
                    is_duplicate = False
                    for existing in unique_headlines:
                        # Check if headlines are very similar (same key words)
                        common_words = set(headline.lower().split()) & set(existing.lower().split())
                        if len(common_words) >= 3:  # If they share 3+ words, likely similar
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        unique_headlines.append(headline)
                
                if unique_headlines:
                    # Format headlines for context
                    headlines_text = "\n".join([f"• {headline}" for headline in unique_headlines[:8]])  # Limit to top 8 unique
                    return f"\n\nCURRENT TRENDING HEADLINES FOR CONTEXT:\n{headlines_text}\n"
            
        except Exception as e:
            print(f"Warning: Could not fetch headlines context for {topic}: {e}")
        
        return ""
    
    @smart_retry_with_backoff
    def generate_summary(self, content_text, topic='TOP_NEWS'):
        """Generate summary and top stories for a specific topic.

        Args:
            content_text: Text content to summarize
            topic: News topic

        Returns:
            Dictionary containing Summary and Stories fields, or None if generation fails
        """
        if not content_text:
            print(f"INFO: No content provided for topic {topic}")
            return None

        print(f"INFO: Generating summary for topic: {topic}")

        # Get trending headlines for additional context
        headlines_context = self.get_trending_headlines_context(topic)

        # Get topic-specific prompt or fall back to default
        prompt_template = TOPIC_PROMPTS.get(topic, DEFAULT_PROMPT)

        # Escape any problematic characters in the content
        content_escaped = json.dumps(content_text)

        # Enhanced prompt with headlines context
        if headlines_context:
            prompt = f"""{prompt_template}

        Use the current trending headlines below to help prioritize the most important and relevant stories. Focus on topics that align with what's currently trending and newsworthy.

        {headlines_context}

        Format your response as a JSON object with these exact field names.

        News Articles:
        {content_escaped}"""
            print(f"INFO: Including {len(headlines_context.split('•'))-1} trending headlines as context for {topic}")
        else:
            prompt = f"""{prompt_template}

        Format your response as a JSON object with these exact field names.

        News Articles:
        {content_escaped}"""

        # Initialize chat session if needed
        chat_session = self.setup_gemini()

        print(f"INFO: Sending request to Gemini API for topic: {topic}")
        response = chat_session.send_message(prompt)
        print(f"INFO: Received response from Gemini API for topic: {topic}")

        # Parse the response
        return json.loads(response.text)

    def generate_chunked_summary(self, content_text, topic='TOP_NEWS'):
        """Summarize large content blobs by chunking into manageable pieces."""
        chunks = chunk_text(content_text, SUMMARY_CHUNK_MAX_CHARS)
        if not chunks:
            return None

        if len(chunks) == 1:
            return self.generate_summary(chunks[0], topic)

        chunk_summaries = []
        for idx, chunk in enumerate(chunks, start=1):
            print(f"[INFO] Summarizing chunk {idx}/{len(chunks)} for {topic}")
            result = self.generate_summary(chunk, topic)
            if result:
                chunk_summaries.append(result)

        if not chunk_summaries:
            print(f"[WARNING] Failed to summarize chunks for {topic}")
            return None

        combined_parts = []
        for idx, chunk_summary in enumerate(chunk_summaries, start=1):
            combined_parts.append(f"Chunk {idx} Summary:\n{chunk_summary.get('Summary', '')}")
            for story in chunk_summary.get('Stories', []):
                combined_parts.append(
                    f"StoryTitle: {story.get('StoryTitle', '')}\nStoryDescription: {story.get('StoryDescription', '')}"
                )

        combined_input = "\n\n".join(part for part in combined_parts if part)
        final_summary = self.generate_summary(combined_input, topic)
        if final_summary:
            merged_stories = self._merge_story_lists(final_summary.get('Stories', []), chunk_summaries)
            final_summary['Stories'] = merged_stories

        return final_summary
    
    @smart_retry_with_backoff
    def generate_brief_summary(self, summary_text, topic):
        """Generate brief bullet-point summary.

        Args:
            summary_text: Original summary to compress
            topic: News topic

        Returns:
            Dictionary containing BriefSummary and BulletPoints fields
        """
        prompt = f"""Create an extremely concise version of this news summary for topic: {topic}

        Original Summary:
        {summary_text}

        Please provide:
        1. A "BriefSummary" field with a succint 1 sentence summary
        2. A "BulletPoints" array with 2-4 extremely short bullet points of key takeaways

        Format as JSON with exactly these fields."""

        # Initialize brief chat session if needed
        brief_chat = self.setup_brief_gemini()

        response = brief_chat.send_message(prompt)
        return json.loads(response.text)

    def _merge_story_lists(self, primary_stories, chunk_summaries, limit=10):
        """Merge stories from chunk outputs while preserving uniqueness."""
        merged = []
        seen = set()

        def add_story(story):
            if not story:
                return
            title = (story.get('StoryTitle') or '').strip()
            if not title:
                return
            key = title.lower()
            if key in seen:
                return
            seen.add(key)
            merged.append(story)

        for story in primary_stories or []:
            add_story(story)
            if len(merged) >= limit:
                return merged[:limit]

        for summary in chunk_summaries:
            for story in summary.get('Stories', []):
                add_story(story)
                if len(merged) >= limit:
                    return merged[:limit]

        return merged[:limit]
    
    @smart_retry_with_backoff
    def generate_weekly_summary(self, content_text, topic):
        """Generate weekly summary for a specific topic.
        
        Args:
            content_text: Text content of daily summaries from the week
            topic: News topic
            
        Returns:
            Dictionary containing weekly summary, key developments, and trending topics
        """
        if not content_text:
            print(f"INFO: No content provided for weekly summary of {topic}")
            return None

        print(f"INFO: Generating weekly summary for topic: {topic}")
        print(f"INFO: Content size for {topic}: {len(content_text)} characters")

        # Setup weekly summary generation model
        if not self.weekly_chat_session:
            generation_config = {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_schema": content.Schema(
                    type=content.Type.OBJECT,
                    required=["weekly_summary", "key_developments", "trending_topics"],
                    properties={
                        "weekly_summary": content.Schema(
                            type=content.Type.STRING,
                            description="A comprehensive 1-paragraph summary of the week's events"
                        ),
                        "key_developments": content.Schema(
                            type=content.Type.ARRAY,
                            description="8-10 key developments from the week",
                            items=content.Schema(
                                type=content.Type.OBJECT,
                                required=["title", "description"],
                                properties={
                                    "title": content.Schema(
                                        type=content.Type.STRING,
                                        description="Short title for the development"
                                    ),
                                    "description": content.Schema(
                                        type=content.Type.STRING,
                                        description="1-2 sentence description of the development"
                                    ),
                                },
                            ),
                        ),
                        "trending_topics": content.Schema(
                            type=content.Type.ARRAY,
                            description="5 trending topics or themes from the week",
                            items=content.Schema(
                                type=content.Type.STRING
                            ),
                        ),
                    },
                ),
                "response_mime_type": "application/json",
            }

            print(f"INFO: Initializing weekly summary model for {topic}")
            model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                generation_config=generation_config,
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
            )

            self.weekly_chat_session = model.start_chat()
            print(f"INFO: Weekly summary model initialized for {topic}")

        # Prepare prompt
        prompt = f"""Create a comprehensive weekly summary for the topic {topic} based on the
        daily summaries provided below. The summary will be used for a news application's weekly digest.

        {content_text}

        Format your response as a JSON object with these exact fields:
        1. "weekly_summary": A comprehensive paragraph (at least 200 words) that captures the major developments,
           trends, and significant events of the week related to {topic}.
        2. "key_developments": An array of 8-10 objects, each with "title" and "description" fields,
           representing the most important news stories or developments from the week.
        3. "trending_topics": An array of 5 strings representing broader themes or trends observed across multiple stories.

        Make sure to capture the most important developments of the week while maintaining journalistic integrity.
        """

        print(f"INFO: Sending request to Gemini API for weekly summary of topic: {topic}")
        response = self.weekly_chat_session.send_message(prompt)
        print(f"INFO: Received response from Gemini API for topic: {topic}")

        # Parse the response
        try:
            result = json.loads(response.text)

            # Validate response structure
            if "weekly_summary" not in result:
                print(f"WARNING: Weekly summary response for {topic} missing 'weekly_summary' field")

            if "key_developments" not in result:
                print(f"WARNING: Weekly summary response for {topic} missing 'key_developments' field")

            if "trending_topics" not in result:
                print(f"WARNING: Weekly summary response for {topic} missing 'trending_topics' field")

            # Debug: Log the result structure
            print(f"DEBUG: Weekly summary for {topic} has {len(result.get('key_developments', []))} key developments")
            print(f"DEBUG: Weekly summary for {topic} has {len(result.get('trending_topics', []))} trending topics")
            print(f"DEBUG: Weekly summary length: {len(result.get('weekly_summary', ''))}")

            return result

        except json.JSONDecodeError as json_err:
            print(f"ERROR: Failed to parse weekly summary JSON for {topic}: {json_err}")
            print(f"Raw response: {response.text[:200]}...")  # Log part of the raw response
            return None 
