"""
Configuration settings for the news aggregator system.
All configuration variables from the original application have been moved here.
"""

import os
import sys
from pathlib import Path
from datetime import timedelta

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
TOPIC_ROTATION_FILE = DATA_DIR / 'topic_rotation.json'

# Fetch configuration
ARTICLES_PER_FEED = 20
REQUEST_DELAY = 1  # seconds
MAX_CONCURRENT_ARTICLE_FETCHES = int(os.environ.get("MAX_CONCURRENT_ARTICLE_FETCHES", 4))
REQUEST_TIMEOUT = 10  # seconds
MIN_ARTICLE_LENGTH = 200  # characters
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# Time intervals
CHECK_INTERVAL = 600  # 10 minutes between feed checks
SUMMARY_INTERVAL = 7200  # 2 hours in seconds
FAILED_URL_RETRY_INTERVAL = 86400  # 24 hours in seconds

# Aggregation loop configuration
CONTINUOUS_AGGREGATION = os.environ.get("CONTINUOUS_AGGREGATION", "true").lower() == "true"
MAX_RUN_CYCLES = int(os.environ.get("MAX_RUN_CYCLES", 6))
TOPICS_PER_CYCLE = int(os.environ.get("TOPICS_PER_CYCLE", 2))
TOPIC_COOLDOWN_SECONDS = int(os.environ.get("TOPIC_COOLDOWN_SECONDS", 90 * 60))  # 90 minutes between repeats

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
FIRESTORE_BATCH_WRITE_LIMIT = int(os.environ.get("FIRESTORE_BATCH_WRITE_LIMIT", 450))

# Gemini API configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# NewsAPI.org configuration
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY") or os.environ.get("NEWS_API_KEY", "")

# Article selection configuration
USE_NEWSAPI_FOR_DISCOVERY = True  # Toggle to use NewsAPI.org for article discovery
NEWSAPI_FALLBACK_TO_RSS = True   # Fall back to RSS if NewsAPI fails
ARTICLE_QUALITY_THRESHOLD = 50   # Minimum quality score for articles
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "")  # Secondary API key for rate limit fallback
GEMINI_BASE_DELAY = 1  # Base delay between Gemini API calls in seconds
GEMINI_MAX_RETRIES = 5
GEMINI_MAX_DELAY = 120  # Maximum delay between retries in seconds (increased for rate limits)
GEMINI_RATE_LIMIT_DELAY = 60  # Default delay for rate limit errors in seconds
SUMMARY_CHUNK_MAX_CHARS = int(os.environ.get("SUMMARY_CHUNK_MAX_CHARS", 12000))
SUMMARY_ENRICHMENT_WORKERS = int(os.environ.get("SUMMARY_ENRICHMENT_WORKERS", 4))

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

# Sports performance tuning
MAX_SPORT_FETCH_WORKERS = int(os.environ.get("MAX_SPORT_FETCH_WORKERS", 4))
SPORTS_NEWS_SUMMARY_CONCURRENCY = int(os.environ.get("SPORTS_NEWS_SUMMARY_CONCURRENCY", 3))

# ESPN sports discovery and enrichment configuration
SPORTS_DISCOVERY = {
    'enabled': os.environ.get("SPORTS_DISCOVERY_ENABLED", "true").lower() == "true",
    'sports_whitelist': os.environ.get(
        "SPORTS_DISCOVERY_SPORTS",
        "football,basketball,baseball,hockey,soccer"
    ).split(','),
    'league_blacklist': os.environ.get(
        "SPORTS_DISCOVERY_LEAGUE_BLACKLIST",
        "football/cfl,football/xfl"
    ).split(','),
    'max_leagues_per_sport': int(os.environ.get("SPORTS_DISCOVERY_MAX_LEAGUES_PER_SPORT", 8)),
    'cache_ttl_hours': int(os.environ.get("SPORTS_DISCOVERY_CACHE_TTL_HOURS", 12)),
}

SPORTS_SCOREBOARD_ENABLES = os.environ.get(
    "SPORTS_SCOREBOARD_ENABLES",
    "linescores,leaders,statistics,probabilities,gameInfo,broadcasts,odds,situation"
).split(',')

SPORTS_ENRICHMENT = {
    'enabled': os.environ.get("SPORTS_ENRICHMENT_ENABLED", "true").lower() == "true",
    'pre_event_window_hours': int(os.environ.get("SPORTS_ENRICHMENT_PRE_WINDOW", 72)),
    'post_event_window_hours': int(os.environ.get("SPORTS_ENRICHMENT_POST_WINDOW", 12)),
    'max_workers': int(os.environ.get("SPORTS_ENRICHMENT_WORKERS", 4)),
    'team_enable_params': os.environ.get(
        "SPORTS_TEAM_ENABLE_PARAMS",
        "roster,projection,stats,depthchart"
    ),
    'max_recent_plays': int(os.environ.get("SPORTS_ENRICHMENT_MAX_PLAYS", 6)),
    'max_recent_drives': int(os.environ.get("SPORTS_ENRICHMENT_MAX_DRIVES", 2)),
    'max_odds_snapshots': int(os.environ.get("SPORTS_ENRICHMENT_MAX_ODDS", 3)),
}

SPORTS_NEWS_SETTINGS = {
    'enabled': os.environ.get("SPORTS_LEAGUE_NEWS_ENABLED", "true").lower() == "true",
    'limit': int(os.environ.get("SPORTS_LEAGUE_NEWS_LIMIT", 5)),
}

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

# NewsAPI.org quota management (Free tier: 100 requests/day)
NEWSAPI_DAILY_QUOTA = 100        # Daily request limit
NEWSAPI_CACHE_DURATION = 3600    # Cache articles for 1 hour (in seconds)
NEWSAPI_PRIORITY_TOPICS = ['TOP_NEWS', 'TECHNOLOGY', 'BUSINESS']  # Priority topics for quota allocation
NEWSAPI_MAX_REQUESTS_PER_TOPIC = 1  # Max requests per topic per run (reduced from 2)
NEWSAPI_ENABLE_CACHING = True    # Enable aggressive caching
NEWSAPI_QUOTA_BUFFER = 0.8       # Use only 80% of quota to leave buffer (80 requests/day)
NEWSAPI_HEADLINES_CONTEXT = True # Use NewsAPI headlines to provide context for Gemini summary generation
NEWSAPI_MIN_QUOTA_FOR_HEADLINES = 5  # Minimum quota required before fetching headlines context

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
    print(f"Warning: Missing environment variables: {', '.join(missing_vars)}")
    print("Legacy pipelines may fail until these variables are set.")

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
    "max_output_tokens": 2048,
    "response_mime_type": "application/json",
    "response_json_schema": {
        "type": "object",
        "properties": {
            "BriefSummary": {"type": "string"},
            "BulletPoints": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["BriefSummary", "BulletPoints"],
    },
}

# Ensure data directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)
os.makedirs(COMBINED_DIR, exist_ok=True) 
