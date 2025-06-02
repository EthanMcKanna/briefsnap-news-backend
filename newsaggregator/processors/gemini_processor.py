"""Gemini API processor for generating summaries and articles."""

import json
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content

from newsaggregator.utils.retry import smart_retry_with_backoff, api_manager
from newsaggregator.config.settings import (
    TOPIC_PROMPTS, DEFAULT_PROMPT,
    BRIEF_GENERATION_CONFIG
)

class GeminiProcessor:
    """Class for processing news data with Google's Gemini API."""
    
    def __init__(self):
        """Initialize the Gemini API client."""
        self.configure_gemini()
        self.chat_session = None
        self.brief_chat_session = None
        self.weekly_chat_session = None
        
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
        
        try:
            # Get topic-specific prompt or fall back to default
            prompt_template = TOPIC_PROMPTS.get(topic, DEFAULT_PROMPT)
            
            # Escape any problematic characters in the content
            content_escaped = json.dumps(content_text)
            
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
            
        except Exception as e:
            print(f"Error generating summary: {e}")
            return None
    
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

        try:
            # Initialize brief chat session if needed
            brief_chat = self.setup_brief_gemini()
            
            response = brief_chat.send_message(prompt)
            return json.loads(response.text)
        except Exception as e:
            print(f"[ERROR] Failed to generate brief summary: {e}")
            return None
    
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
        
        try:
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
            
        except Exception as e:
            print(f"ERROR: Failed to generate weekly summary for {topic}: {str(e)}")
            return None 