# Briefsnap News Backend

A modern, lightweight system for gathering current news and publishing one polished BriefSnap daily brief.

## Features

### News Aggregation
- Fetches a compact, source-diverse packet from Google News RSS, topical RSS queries, and optional NewsAPI
- Extracts useful article text using the existing newspaper3k extractor
- Generates one structured daily brief using `google-genai` and current Gemini 3.x models
- Uses Google Search and URL context grounding during brief generation
- Writes local JSON artifacts and publishes to Firestore collections consumed by the iOS app
- Keeps the legacy rotating pipeline available behind `BRIEFSNAP_LEGACY_PIPELINE=true`

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
The sports aggregator runs automatically every hour during active times for live updates and score tracking.

**New Feature**: The sports aggregator now includes **automatic game summaries** that generate:
- **Pre-game summaries** for games happening within 24 hours
- **Post-game summaries** for recently finished games
- Uses current Gemini 3 Flash models with Google Search for real-time analysis
- Smart deduplication ensures summaries are only generated once per game

Both systems can also be triggered manually through the GitHub Actions interface.

## Configuration

All configuration is stored in `newsaggregator/config/settings.py`. You can modify:

- RSS feed sources by topic
- Time intervals for checking and summarizing
- API keys and parameters
- Storage paths and file formats
- Similarity thresholds for duplicate detection
- Continuous aggregation controls:
  - `CONTINUOUS_AGGREGATION` toggles multi-cycle runs per invocation (default: true)
  - `MAX_RUN_CYCLES` caps how many cycles run before exiting (default: 6)
  - `TOPICS_PER_CYCLE` limits how many topics are sampled per cycle (default: 2)
  - `TOPIC_COOLDOWN_SECONDS` forces a cooldown before the same topic is reprocessed (default: 90 minutes)

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
- `google-genai`: Gemini API integration
- `firebase-admin`: Firebase/Firestore integration
- `beautifulsoup4`: HTML parsing
- `exa-py`: Exa API integration
- `googlenewsdecoder`: Google News URL decoder
- `python-dotenv`: Environment variable management
