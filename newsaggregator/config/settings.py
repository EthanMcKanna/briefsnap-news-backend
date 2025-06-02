"""
Configuration settings for the news aggregator system.
All configuration variables from the original application have been moved here.
"""

import os
import sys
from pathlib import Path
from datetime import timedelta
from google.ai.generativelanguage_v1beta.types import content

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

# RSS Feed configuration
RSS_FEEDS = {
    'TOP_NEWS': 'https://news.google.com/rss',
    'WORLD': 'https://news.google.com/news/rss/headlines/section/topic/WORLD',
    'BUSINESS': 'https://news.google.com/news/rss/headlines/section/topic/BUSINESS',
    'TECHNOLOGY': 'https://news.google.com/news/rss/headlines/section/topic/TECHNOLOGY',
}

# Directory settings
OUTPUT_DIR = DATA_DIR / 'latest_news_articles'
SUMMARY_DIR = DATA_DIR / 'news_summaries'
COMBINED_DIR = DATA_DIR / 'combined_articles'

# File paths for persistent data
PROCESSED_ARTICLES_FILE = DATA_DIR / 'processed_articles.json'
FAILED_URLS_FILE = DATA_DIR / 'failed_urls.json'
LAST_SUMMARY_FILE = DATA_DIR / 'last_summary_time.txt'

# Fetch configuration
ARTICLES_PER_FEED = 20
REQUEST_DELAY = 1  # seconds
REQUEST_TIMEOUT = 10  # seconds
MIN_ARTICLE_LENGTH = 200  # characters
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# Time intervals
CHECK_INTERVAL = 600  # 10 minutes between feed checks
SUMMARY_INTERVAL = 7200  # 2 hours in seconds
FAILED_URL_RETRY_INTERVAL = 86400  # 24 hours in seconds

# Similarity thresholds for duplicate detection
SIMILARITY_THRESHOLD = 0.6
TITLE_SIMILARITY_THRESHOLD = 0.4
CONTENT_SIMILARITY_THRESHOLD = 0.5
MINIMUM_TITLE_LENGTH = 20
LOOKBACK_PERIOD = 24 * 60 * 60  # 24 hour lookback

# Firebase configuration
FIREBASE_CREDS_PATH = BASE_DIR / 'firebase-credentials.json'
FIRESTORE_COLLECTION = 'news_summaries'
FIRESTORE_ARTICLES_COLLECTION = 'articles'

# Gemini API configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "")  # Secondary API key for rate limit fallback
GEMINI_BASE_DELAY = 1  # Base delay between Gemini API calls in seconds
GEMINI_MAX_RETRIES = 5
GEMINI_MAX_DELAY = 120  # Maximum delay between retries in seconds (increased for rate limits)
GEMINI_RATE_LIMIT_DELAY = 60  # Default delay for rate limit errors in seconds

# Exa API configuration
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
EXA_SEARCH_LIMIT = 5
EXA_LOOKBACK_DAYS = 7

# Cloudflare R2 configuration
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = "briefsnap-images"
R2_CUSTOM_DOMAIN = "images.briefsnap.com"
R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Image optimization configuration
IMAGE_OPTIMIZATION = {
    'enabled': True,  # Set to False to disable optimization
    'convert_to_webp': True,  # Convert all images to WebP format
    'max_width': 1200,  # Maximum width in pixels
    'max_height': 800,  # Maximum height in pixels
    'webp_quality': 85,  # WebP quality (0-100)
    'jpeg_quality': 90,  # JPEG quality if WebP conversion fails (0-100)
    'png_optimization': True,  # Optimize PNG files when not converting to WebP
    'preserve_transparency': True,  # Preserve transparency in PNG/GIF files
    'max_file_size': 2 * 1024 * 1024,  # Maximum file size (2MB)
    'min_file_size': 1024,  # Minimum file size (1KB)
}

# Validate required environment variables
missing_vars = []
if not GEMINI_API_KEY:
    missing_vars.append("GEMINI_API_KEY")
if not EXA_API_KEY:
    missing_vars.append("EXA_API_KEY")

# Warn about missing secondary API key
if not GEMINI_API_KEY_2:
    print("Warning: GEMINI_API_KEY_2 is not set. Rate limit fallback will not be available.")
    print("For better rate limit handling, consider setting a second Gemini API key.")

# R2 credentials are optional for basic functionality but recommended
r2_missing_vars = []
if not R2_ACCOUNT_ID:
    r2_missing_vars.append("R2_ACCOUNT_ID")
if not R2_ACCESS_KEY_ID:
    r2_missing_vars.append("R2_ACCESS_KEY_ID")
if not R2_SECRET_ACCESS_KEY:
    r2_missing_vars.append("R2_SECRET_ACCESS_KEY")

if missing_vars:
    print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
    print("Please set these environment variables before running the application.")
    sys.exit(1)

if r2_missing_vars:
    print(f"Warning: Missing R2 environment variables: {', '.join(r2_missing_vars)}")
    print("R2 image uploading will not be available. Images will use original URLs.")

# Gemini prompt templates by topic
TOPIC_PROMPTS = {
    'TOP_NEWS': """Analyze these news articles and provide:
        1. A "Summary" field with a single cohesive, engaging, and concise paragraph summarizing the most important news of the day so that a reader will walk away feeling informed without being overwhelmed. Focus on interesting and relevant news happening in the US and disregard international stories.
        2. A "Stories" array containing 5-10 of the most essential, important, and relevant stories for Americans beginning with the most significant, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of the story.""",
    
    'WORLD': """Analyze these international news articles and provide:
        1. A "Summary" field with a single cohesive, engaging, and concise paragraph summarizing the most significant global developments. Focus on major international events and their potential global impact.
        2. A "Stories" array containing 5-10 of the most critical international stories beginning with the most significant, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description highlighting global implications.""",
    
    'NATION': """Analyze these national news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting the most significant developments affecting the United States. Focus on domestic policy, politics, social issues, and national events.
        2. A "Stories" array containing 5-10 of the most impactful national stories beginning with the most significant, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description emphasizing national importance.""",
    
    'BUSINESS': """Analyze these business news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting key market movements, corporate developments, and economic trends. Focus on information relevant to investors and business leaders.
        2. A "Stories" array containing 5-10 of the most significant business stories beginning with the most impactful, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of business implications.""",
    
    'TECHNOLOGY': """Analyze these technology news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting the day's most impactful technological developments, innovations, and industry news.
        2. A "Stories" array containing 5-10 of the most significant tech stories beginning with the most impactful, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of the technological advancement or industry development.""",
    
    'ENTERTAINMENT': """Analyze these entertainment news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting the most notable developments in entertainment, including film, television, music, and celebrity news.
        2. A "Stories" array containing 5-10 of the most engaging entertainment stories beginning with the most significant, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of the entertainment news.""",
    
    'SPORTS': """Analyze these sports news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting major sporting events, results, and developments across all major sports.
        2. A "Stories" array containing 5-10 of the most significant sports stories beginning with the most impactful, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of the sporting event or development.""",
    
    'SCIENCE': """Analyze these science news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting breakthrough discoveries, research developments, and scientific achievements.
        2. A "Stories" array containing 5-10 of the most significant scientific stories beginning with the most groundbreaking, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description explaining the scientific significance.""",
    
    'HEALTH': """Analyze these health news articles and provide:
        1. A "Summary" field with a single cohesive paragraph highlighting important medical research, public health developments, and healthcare news.
        2. A "Stories" array containing 5-10 of the most significant health stories beginning with the most impactful, each with:
           - "StoryTitle": A clear, concise headline.
           - "StoryDescription": A 2-3 sentence description of health implications."""
}

# Default prompt for topics without specific templates
DEFAULT_PROMPT = """Analyze these news articles and provide:
    1. A "Summary" field with a single cohesive, engaging, and concise paragraph summarizing the most important developments in this category.
    2. A "Stories" array containing 5-10 of the most essential stories beginning with the most significant, each with:
       - "StoryTitle": A clear, concise headline.
       - "StoryDescription": A 2-3 sentence description of the story."""

# Gemini brief generation config
BRIEF_GENERATION_CONFIG = {
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 40,
    "max_output_tokens": 2048,
    "response_schema": content.Schema(
        type=content.Type.OBJECT,
        required=["BriefSummary", "BulletPoints"],
        properties={
            "BriefSummary": content.Schema(
                type=content.Type.STRING,
                description="1-2 sentence summary of the most crucial points"
            ),
            "BulletPoints": content.Schema(
                type=content.Type.ARRAY,
                items=content.Schema(
                    type=content.Type.STRING,
                    description="Short, concise bullet point"
                ),
                min_items=3,
                max_items=5,
            ),
        },
    ),
    "response_mime_type": "application/json",
}

# Ensure data directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)
os.makedirs(COMBINED_DIR, exist_ok=True) 