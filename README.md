# Briefsnap News Backend

A modular and efficient system for aggregating, processing, and summarizing news articles from various sources.

## Features

### News Aggregation
- Fetches news from multiple RSS feeds by topic
- Extracts content using newspaper3k
- Generates summaries using Google's Gemini AI
- Stores articles locally in files and remotely in Firestore
- Detects duplicate content using similarity metrics
- Enriches articles with additional content from Exa API
- Sends notifications via Firebase Cloud Messaging
- Automated processing via GitHub Actions twice daily (7am and 5pm Central Time)

### Smart Rate Limit Handling
- Intelligent retry logic that respects Gemini API rate limits
- Automatic parsing of retry delays from API error responses
- Support for multiple Gemini API keys with automatic failover
- Smart backoff strategies for different types of API errors
- Real-time API key switching when rate limits are reached
- Enhanced error logging with detailed retry information

### Sports Data Aggregation
- Fetches upcoming games for major sports (NFL, NBA, MLB, NHL, College Football, College Basketball, MLS)
- Uses ESPN's free public API - no paid subscriptions required
- Stores comprehensive game data in Firebase Firestore
- Includes team info, schedules, venues, broadcasts, and odds
- **Automated updates every 30 minutes** for live score tracking
- Smart update detection prevents duplicates and tracks changes
- Live game identification and recently updated game tracking
- Automatic data cleanup and statistics tracking

## Architecture

The system has been refactored into a modular structure:

- `config`: Configuration settings
- `core`: Core orchestration logic
- `fetchers`: Components for fetching news from sources
- `processors`: Components for processing news content
- `storage`: Storage mechanisms (file-based and Firebase)
- `utils`: Utility functions and helpers

## Setup

1. Clone the repository
2. Install dependencies
   ```
   pip install -r requirements.txt
   ```
3. Place your Firebase credentials in `firebase-credentials.json` at the root of the project
4. Configure GitHub repository secrets:
   - `GEMINI_API_KEY`: Your Google Gemini API key
   - `GEMINI_API_KEY_2`: (Optional) Secondary Gemini API key for rate limit fallback
   - `EXA_API_KEY`: Your Exa API key
   - `FIREBASE_CREDENTIALS`: The entire contents of your firebase-credentials.json file

## Running the System

### News Aggregator

#### Locally
```bash
python main.py
```

#### GitHub Actions
The news aggregator automatically runs twice daily:
- 7:00 AM Central Time (13:00 UTC)
- 5:00 PM Central Time (23:00 UTC)

### Sports Aggregator

#### Locally
```bash
python main_sports.py
```

#### GitHub Actions
The sports aggregator runs automatically every 30 minutes for live updates and score tracking.

Both systems can also be triggered manually through the GitHub Actions interface.

## Configuration

All configuration is stored in `newsaggregator/config/settings.py`. You can modify:

- RSS feed sources by topic
- Time intervals for checking and summarizing
- API keys and parameters
- Storage paths and file formats
- Similarity thresholds for duplicate detection

## Data Storage

### News Data
- `data/latest_news_articles`: Individual article files
- `data/combined_articles`: Combined articles by topic and date
- `data/news_summaries`: Generated news summaries
- Firestore collections: `news_summaries` and `articles`

### Sports Data
- `data/sports_data`: Sports game data and summaries
- Firestore collections: `sports_games` and `sports_summaries`

When running via GitHub Actions, the data directories are uploaded as artifacts at the end of each successful run.

For detailed sports system documentation, see [SPORTS_README.md](SPORTS_README.md).

## Dependencies

- `requests`: HTTP requests
- `feedparser`: RSS feed parsing
- `newspaper3k`: Article extraction
- `google-generativeai`: Gemini AI integration
- `firebase-admin`: Firebase/Firestore integration
- `beautifulsoup4`: HTML parsing
- `exa-py`: Exa API integration
- `googlenewsdecoder`: Google News URL decoder
- `python-dotenv`: Environment variable management