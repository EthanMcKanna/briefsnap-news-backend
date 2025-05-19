# Briefsnap News Backend

A modular and efficient system for aggregating, processing, and summarizing news articles from various sources.

## Features

- Fetches news from multiple RSS feeds by topic
- Extracts content using newspaper3k
- Generates summaries using Google's Gemini AI
- Stores articles locally in files and remotely in Firestore
- Detects duplicate content using similarity metrics
- Enriches articles with additional content from Exa API
- Sends notifications via Firebase Cloud Messaging
- Automated processing via GitHub Actions twice daily (7am and 5pm Central Time)

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
   - `EXA_API_KEY`: Your Exa API key

## Running the News Aggregator

### Locally
Run the news aggregator manually:
```
python main.py
```

### GitHub Actions
The system automatically runs twice daily via GitHub Actions:
- 7:00 AM Central Time (13:00 UTC)
- 5:00 PM Central Time (23:00 UTC)

You can also trigger a manual run through the GitHub Actions interface by selecting the "News Aggregator Processing" workflow and clicking "Run workflow".

## Configuration

All configuration is stored in `newsaggregator/config/settings.py`. You can modify:

- RSS feed sources by topic
- Time intervals for checking and summarizing
- API keys and parameters
- Storage paths and file formats
- Similarity thresholds for duplicate detection

## Data Storage

The system stores data in the following locations:

- `data/latest_news_articles`: Individual article files
- `data/combined_articles`: Combined articles by topic and date
- `data/news_summaries`: Generated news summaries
- Firestore collections: `news_summaries` and `articles`

When running via GitHub Actions, the data directory is uploaded as an artifact at the end of each successful run.

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