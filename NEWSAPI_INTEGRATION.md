# Enhanced Article Selection with NewsAPI.org Integration

This document describes the improved article selection system that integrates NewsAPI.org for more robust and intelligent article discovery and ranking.

## Overview

The enhanced system replaces the simple RSS-only approach with a sophisticated multi-source article selection process that:

- **Combines multiple sources**: NewsAPI.org + RSS feeds for comprehensive coverage
- **Intelligent ranking**: Advanced scoring algorithm based on source reliability, recency, content quality
- **Quality filtering**: Automatic filtering of low-quality articles and clickbait
- **Source diversity**: Ensures balanced representation from different news sources
- **Fallback support**: Graceful degradation to RSS-only if NewsAPI.org is unavailable

## Key Components

### 1. NewsAPIFetcher (`newsaggregator/fetchers/newsapi_fetcher.py`)

The core NewsAPI.org integration that provides:

- **Source ranking system**: Tier-based reliability scoring (Reuters=100, BBC=90, etc.)
- **Comprehensive scoring**: Combines source authority, recency, title quality, content depth
- **Multiple endpoints**: Top headlines + Everything API for maximum coverage
- **Smart topic mapping**: Maps internal topics to NewsAPI categories and search terms

```python
# Example usage
fetcher = NewsAPIFetcher(api_key="your-key")
articles = fetcher.get_curated_articles_for_topic("TECHNOLOGY", max_articles=20)
```

### 2. ArticleSelector (`newsaggregator/selectors/article_selector.py`)

The intelligent article selection orchestrator that:

- **Merges sources**: Combines NewsAPI.org and RSS articles with deduplication
- **Enhanced scoring**: Multi-factor quality assessment
- **Quality validation**: Filters out invalid or low-quality articles
- **Diversity reporting**: Tracks source distribution for balanced coverage

```python
# Example usage
selector = ArticleSelector()
articles = selector.select_best_articles_for_topic("BUSINESS", max_articles=15)
diversity = selector.get_source_diversity_report(articles)
```

### 3. Enhanced Aggregator Integration

The main aggregator (`newsaggregator/core/aggregator.py`) now uses the enhanced selection:

- **Configurable**: Can toggle between enhanced and traditional RSS-only modes
- **Extended topics**: Supports additional NewsAPI topics (Science, Health, Sports, Entertainment)
- **Quality metrics**: Reports average quality scores and source diversity
- **Graceful fallback**: Automatically falls back to RSS if NewsAPI fails

## Configuration

### Environment Variables

```bash
# Required for NewsAPI.org integration
export NEWSAPI_KEY="your-newsapi-org-api-key"

# Optional: Gemini API keys (existing)
export GEMINI_API_KEY="your-gemini-key"
```

### Settings (`newsaggregator/config/settings.py`)

```python
# NewsAPI.org configuration
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

# Article selection configuration
USE_NEWSAPI_FOR_DISCOVERY = True  # Enable enhanced selection
NEWSAPI_FALLBACK_TO_RSS = True   # Fall back to RSS if NewsAPI fails
ARTICLE_QUALITY_THRESHOLD = 50   # Minimum quality score (0-100)
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install newsapi-python
# or update your existing installation
pip install -r requirements.txt
```

### 2. Get NewsAPI.org API Key

1. Visit [NewsAPI.org](https://newsapi.org/)
2. Sign up for a free account
3. Get your API key from the dashboard
4. Free tier provides 1,000 requests/day

### 3. Configure Environment

```bash
# Set environment variable
export NEWSAPI_KEY="your-api-key-here"

# Or add to .env file
echo "NEWSAPI_KEY=your-api-key-here" >> .env
```

### 4. Test Setup

Run the setup verification script:

```bash
python setup_newsapi.py
```

This will:
- Check for API key configuration
- Test NewsAPI.org connection
- Verify enhanced article selector functionality
- Report any configuration issues

## Article Scoring Algorithm

The enhanced scoring system evaluates articles across multiple dimensions:

### Source Reliability (40% weight)
- **Tier 1 (90-100)**: Reuters, AP News, BBC
- **Tier 2 (80-89)**: CNN, NYT, Washington Post, WSJ, The Guardian
- **Tier 3 (70-79)**: TechCrunch, Axios, Politico, Bloomberg
- **Tier 4 (60-69)**: Forbes, CNBC, MarketWatch
- **Default (50)**: Unknown sources

### Recency (25% weight)
- Fresh articles (< 6 hours): Full points
- Recent articles (6-24 hours): Graduated decay
- Older articles (> 24 hours): Reduced score

### Content Quality (30% weight)
- **Title quality (20%)**: Length, descriptiveness, clickbait detection
- **Description quality (10%)**: Presence and length of article description

### Additional Factors (5% weight)
- Author attribution: Bonus for named authors
- Image presence: Bonus for articles with images
- Source type: Bonus for NewsAPI articles (higher curation)

### Quality Filters
- Removes articles with suspicious domains (blogspot, wordpress, etc.)
- Filters out placeholder content
- Validates URL schemes
- Enforces minimum content requirements

## Topic Mapping

The system intelligently maps internal topics to NewsAPI categories:

| Internal Topic | NewsAPI Category | Search Query |
|----------------|------------------|--------------|
| TOP_NEWS | general | None |
| WORLD | None | "world news international" |
| BUSINESS | business | "business economy finance" |
| TECHNOLOGY | technology | "technology tech innovation" |
| SCIENCE | science | "science research discovery" |
| HEALTH | health | "health medical healthcare" |
| SPORTS | sports | "sports" |
| ENTERTAINMENT | entertainment | "entertainment" |

## Usage Examples

### Basic Usage

```python
from newsaggregator.core.aggregator import NewsAggregator

# Initialize with enhanced selection
aggregator = NewsAggregator()

# Process all topics with enhanced selection
articles_by_topic = aggregator.process_feeds()

# Generate summaries as usual
summaries = aggregator.generate_summaries()
```

### Advanced Usage

```python
from newsaggregator.selectors.article_selector import ArticleSelector

# Direct article selection
selector = ArticleSelector()

# Get high-quality technology articles
tech_articles = selector.select_best_articles_for_topic("TECHNOLOGY", max_articles=25)

# Analyze source diversity
diversity = selector.get_source_diversity_report(tech_articles)
print(f"Technology articles from {len(diversity)} different sources")

# Validate individual articles
for article in tech_articles:
    is_valid, issues = selector.validate_article_quality(article)
    if not is_valid:
        print(f"Quality issues: {issues}")
```

## Benefits of Enhanced Selection

### 1. **Higher Quality Articles**
- Authority-based source ranking ensures reliable information
- Multi-factor scoring eliminates low-quality content
- Automated clickbait detection

### 2. **Better Coverage**
- Combines NewsAPI.org's 150,000+ sources with RSS feeds
- Access to breaking news and trending topics
- Geographic and topical diversity

### 3. **Intelligent Curation**
- Recency weighting favors fresh content
- Source diversity prevents echo chambers
- Quality thresholds maintain standards

### 4. **Robust Operation**
- Graceful fallback to RSS if NewsAPI fails
- Configurable quality thresholds
- Comprehensive error handling

### 5. **Enhanced Topics**
- Supports additional categories (Science, Health, Sports, Entertainment)
- Topic-specific source recommendations
- Flexible topic mapping system

## Monitoring and Debugging

### Quality Metrics

The system provides detailed quality reporting:

```python
# Example output during processing
Selected 18 high-quality articles for TECHNOLOGY
Average quality score: 73.2
Source diversity for TECHNOLOGY: {'Reuters': 3, 'TechCrunch': 2, 'BBC': 2, 'CNN': 2, 'Wired': 1}
```

### Common Issues

1. **API Key Issues**
   - Verify NEWSAPI_KEY environment variable
   - Check API key validity at newsapi.org
   - Ensure sufficient API quota

2. **Low Article Counts**
   - Adjust ARTICLE_QUALITY_THRESHOLD (lower for more articles)
   - Check topic mapping in NewsAPIFetcher
   - Verify source availability for topic

3. **Source Diversity Issues**
   - Review source rankings in NewsAPIFetcher
   - Adjust scoring algorithm weights
   - Check NewsAPI source availability

## Migration from RSS-Only

To migrate from the existing RSS-only system:

1. **Set up NewsAPI.org**: Get API key and configure environment
2. **Test gradually**: Start with `USE_NEWSAPI_FOR_DISCOVERY = True` and `NEWSAPI_FALLBACK_TO_RSS = True`
3. **Monitor quality**: Check output quality and adjust thresholds
4. **Full migration**: Once satisfied, can optionally disable RSS fallback

The system is designed for seamless migration with no breaking changes to existing workflows.

## Future Enhancements

Potential improvements to consider:

1. **Machine Learning Scoring**: Train models on user engagement data
2. **Custom Source Lists**: User-defined source preferences
3. **Geographic Filtering**: Location-based article selection
4. **Sentiment Analysis**: Content sentiment scoring
5. **Cache Optimization**: Smart caching for API efficiency
6. **Real-time Updates**: WebSocket integration for live updates

## Support

For issues or questions:

1. Run `python setup_newsapi.py` for diagnostics
2. Check configuration in `newsaggregator/config/settings.py`
3. Review logs for error messages
4. Verify NewsAPI.org quota and limits

The enhanced article selection system provides a significant upgrade in content quality and discovery capabilities while maintaining compatibility with existing workflows. 