# Game Summary System

An intelligent game summary system that automatically generates pre-game and post-game summaries for games happening within the next 24 hours using Gemini Flash 2 Lite with Google Search.

## Features

- **Pre-game summaries** for games happening within 24 hours
- **Post-game summaries** for recently finished games (within 4 hours)
- Uses **Gemini Flash 2 Lite with Google Search** for up-to-date information
- **Smart deduplication** - summaries are only generated once per game phase
- **Firebase storage** with automatic cleanup of old summaries
- **Integrated with existing sports aggregator** workflow

## How It Works

### Pre-Game Summaries

The system automatically:
1. Identifies games happening within the next 24 hours
2. Checks if a pre-game summary already exists (to avoid duplicates)
3. Generates a summary focusing on:
   - Recent team performance and form
   - Key players to watch (injuries, notable performers)
   - Head-to-head matchup history or significance
   - What's at stake for both teams
   - Notable storylines or context

### Post-Game Summaries

The system automatically:
1. Identifies recently finished games (within 4 hours)
2. Checks if a post-game summary already exists
3. Generates a summary focusing on:
   - How the game unfolded and key moments
   - Standout individual performances
   - Turning points or decisive plays
   - Statistical highlights
   - Impact on teams' seasons or standings
   - Notable quotes or reactions

## Summary Format

Both pre-game and post-game summaries follow a consistent format:

### Pre-Game
```
**Pre-Game Summary:** [Concise analysis of the matchup and what to expect]

**Key Points:**
• [Key point 1]
• [Key point 2]
• [Key point 3]
```

### Post-Game
```
**Post-Game Summary:** [Concise recap of how the game played out and key takeaways]

**Key Highlights:**
• [Key highlight 1]
• [Key highlight 2]
• [Key highlight 3]
```

## Firebase Storage

Game summaries are stored in the `game_summaries` Firestore collection with the following structure:

```javascript
{
  doc_id: "game_id_summary_type_timestamp",
  game_id: "ESPN game ID",
  sport_code: "nfl|nba|mlb|nhl|ncaaf|ncaab|mls",
  home_team: "Team Name",
  away_team: "Team Name", 
  game_date: "ISO timestamp",
  summary_type: "pre_game|post_game",
  summary: "Generated summary text",
  generated_at: "ISO timestamp",
  stored_at: "ISO timestamp",
  model_used: "gemini-2.0-flash-lite",
  // Post-game only:
  final_score: "Away Team X, Home Team Y"
}
```

## Integration

The game summary processor is integrated into the main sports aggregator (`main_sports.py`) and runs automatically every time the sports aggregator runs. It processes summaries after the sports data is stored in Firebase.

### Automatic Schedule

Game summaries are generated as part of the regular sports aggregator schedule:
- **Every hour during active times** (12 PM - 7 AM UTC)
- Runs via GitHub Actions workflow

### Smart Processing

- **Pre-game summaries**: Only generated for games within 24 hours that don't already have summaries
- **Post-game summaries**: Only generated for games that finished within 4 hours and don't already have summaries
- **Deduplication**: The system checks for existing summaries before generating new ones
- **Error handling**: Continues processing other games if individual summaries fail

## Usage

### Programmatic Access

```python
from newsaggregator.processors.game_summary_processor import GameSummaryProcessor
from newsaggregator.storage.sports_storage import SportsStorage

# Initialize processor
processor = GameSummaryProcessor()

# Process all game summaries
results = processor.process_game_summaries()

# Get recent summaries
recent_summaries = SportsStorage.get_recent_game_summaries(hours=24)

# Get summaries for a specific game
game_summaries = SportsStorage.get_game_summaries(game_id="12345")

# Check if summary exists
has_summary = SportsStorage.has_game_summary(game_id="12345", summary_type="pre_game")
```

### Testing

Run the test script to verify functionality without using API calls:

```bash
python test_game_summaries.py
```

## Configuration

The game summary system uses the same configuration as the main sports aggregator:

- **API Key**: Uses `GEMINI_API_KEY` environment variable
- **Model**: Uses `gemini-2.0-flash-lite` for efficient processing
- **Firebase**: Uses existing Firebase credentials
- **Cleanup**: Automatically removes summaries older than 30 days

## Monitoring

The system provides detailed logging:

```
====== Processing Game Summaries ======
Checking for upcoming games within 24 hours...
Found 15 games within 24 hours
Generating pre-game summary for Lakers @ Warriors...
✅ Generated pre-game summary for Lakers @ Warriors
Checking for recently finished games...
Found 3 recently finished games
✅ Generated post-game summary for Celtics @ Heat

Game summary processing complete:
  Pre-game: 3 generated, 12 skipped
  Post-game: 1 generated, 2 skipped
```

## Data Access Patterns

### Recent Game Summaries
Get summaries generated in the last N hours:
```python
recent = SportsStorage.get_recent_game_summaries(hours=24)
```

### Game-Specific Summaries
Get all summaries for a specific game:
```python
summaries = SportsStorage.get_game_summaries(game_id="12345")
```

### Summary Types
- `pre_game`: Generated before the game starts
- `post_game`: Generated after the game finishes

## Performance

- **Lightweight processing**: Only processes games that need summaries
- **Efficient queries**: Uses indexed Firebase queries
- **Smart caching**: Avoids regenerating existing summaries
- **Batch cleanup**: Removes old data in batches to avoid performance issues

## Error Handling

The system is designed to be resilient:
- Individual game failures don't stop processing of other games
- API failures are logged but don't crash the system
- Firebase connection issues are handled gracefully
- Detailed error reporting for debugging

## Future Enhancements

Potential improvements:
- Push notifications for generated summaries
- Team-specific summary subscriptions
- Historical summary analysis
- Integration with mobile app
- Custom summary templates by sport 