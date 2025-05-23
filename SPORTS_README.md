# Sports Aggregator System

A reliable sports data aggregation system that fetches upcoming games for popular sports and stores them in Firebase. The system uses free APIs and web scraping, requiring no paid subscriptions.

## Features

- Fetches upcoming games for major sports: NFL, NBA, MLB, NHL, College Football, College Basketball, and MLS
- Uses ESPN's free public API for reliable data
- Stores game data in Firebase Firestore for easy access
- **Runs automatically every 30 minutes** for live score updates
- **Smart update detection** - only updates games when scores, status, or other data changes
- **Live game tracking** - identifies and prioritizes in-progress games
- Includes comprehensive game information: teams, venues, schedules, broadcasts, and odds
- Automatically cleans up old data (30+ days)
- Provides detailed statistics and summaries
- **No duplicate games** - efficiently updates existing games instead of creating duplicates

## Supported Sports

- **NFL** - National Football League
- **NBA** - National Basketball Association
- **MLB** - Major League Baseball
- **NHL** - National Hockey League
- **College Football** (NCAA FBS)
- **College Basketball** (NCAA Division I Men's)
- **MLS** - Major League Soccer

## Data Structure

Each game includes:
- **Basic Info**: Sport, date/time, status, venue
- **Teams**: Home/away teams with names, abbreviations, records, rankings
- **Scores**: Current scores (for live/completed games)
- **Broadcasts**: TV/streaming networks
- **Venue**: Stadium/arena name and location
- **Additional**: Season, week (for NFL/College Football), odds, notes

## Firebase Collections

The system stores data in two Firestore collections:

### `sports_games`
Individual game documents with unique IDs (`{sport}_{game_id}`)

### `sports_summaries`
Daily summaries with statistics and overview data

## Automated Schedule

The sports aggregator runs automatically via GitHub Actions:
- **Every 30 minutes** - Frequent updates for live games and score changes
- Optimized to focus on games happening today and tomorrow
- Smart update detection prevents duplicate entries

## Manual Execution

### Locally
```bash
python main_sports.py
```

### GitHub Actions
1. Go to the Actions tab in your GitHub repository
2. Select "Sports Aggregator Processing"
3. Click "Run workflow"

## Configuration

The sports system uses the existing Firebase configuration from the news aggregator. No additional API keys or paid services are required.

### Required Setup
1. Firebase credentials configured (same as news aggregator)
2. Python dependencies installed (`pip install -r requirements.txt`)

## Data Access

### Using the SportsStorage Class

```python
from newsaggregator.storage.sports_storage import SportsStorage

# Get upcoming games for all sports
upcoming_games = SportsStorage.get_upcoming_games(limit=20)

# Get games for a specific sport
nfl_games = SportsStorage.get_upcoming_games(sport='nfl', limit=10)

# Get games for a specific date
from datetime import datetime
today_games = SportsStorage.get_games_by_date(datetime.now())

# Get games for a specific team
team_games = SportsStorage.get_games_by_team("Los Angeles Lakers")

# Get latest summary
summary = SportsStorage.get_latest_summary()

# Get database statistics
stats = SportsStorage.get_sports_stats()

# Get live games
live_games = SportsStorage.get_live_games()

# Get recently updated games
recent_updates = SportsStorage.get_recently_updated_games(hours=2)
```

## Data Retention

- **Games**: Stored for 30 days after completion
- **Summaries**: Kept for 30 days
- **Automatic Cleanup**: Runs with each update to remove old data

## Output Files

Local data is saved to `data/sports_data/`:
- `all_games_{timestamp}.json` - Complete game data
- `summary_{timestamp}.json` - Summary statistics

These files are also uploaded as GitHub Actions artifacts with 7-day retention.

## Reliability Features

- **No Paid APIs**: Uses ESPN's free public API
- **Rate Limiting**: Respectful delays between requests
- **Error Handling**: Graceful handling of network issues
- **Duplicate Prevention**: Smart game ID management
- **Data Validation**: Ensures data quality before storage

## Monitoring

The system provides detailed logging including:
- Number of games fetched per sport
- Firebase storage success/failure
- Data cleanup operations
- Performance metrics

## Example Use Cases

- **Mobile App**: Fetch upcoming games for a sports app
- **Website**: Display today's games or team schedules
- **Notifications**: Alert users about upcoming games
- **Analytics**: Track scheduling patterns and trends
- **Fantasy Sports**: Get game schedules for roster decisions

## Troubleshooting

### Common Issues

1. **No games found**: Check if it's off-season for specific sports
2. **Firebase errors**: Verify credentials and permissions
3. **Network timeouts**: ESPN API may be temporarily unavailable

### Logs
Check GitHub Actions logs for detailed error information and execution statistics.

## Future Enhancements

Potential additions:
- Live score updates during games
- Player statistics and injury reports
- Weather conditions for outdoor games
- Playoff brackets and tournament trees
- International sports leagues
- Push notifications for game reminders 