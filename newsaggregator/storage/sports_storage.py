"""Firebase storage for sports data."""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from firebase_admin import firestore
from newsaggregator.storage.firebase_storage import FirebaseStorage

class SportsStorage:
    """Class for managing sports data in Firebase/Firestore."""
    
    # Collection names
    SPORTS_GAMES_COLLECTION = 'sports_games'
    SPORTS_SUMMARIES_COLLECTION = 'sports_summaries'
    SPORTS_NEWS_SUMMARIES_COLLECTION = 'sports_news_summaries'
    GAME_SUMMARIES_COLLECTION = 'game_summaries'
    
    @classmethod
    def store_games(cls, all_games: Dict[str, List[Dict]], summary: Dict) -> bool:
        """Store sports games and summary in Firestore.
        
        Args:
            all_games: Dictionary of games by sport
            summary: Summary of all games
            
        Returns:
            True if successful, False otherwise
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return False
        
        try:
            timestamp = datetime.now(timezone.utc)
            
            # Store individual games with update detection
            games_stored = 0
            games_updated = 0
            
            for sport, games in all_games.items():
                for game in games:
                    if not game.get('id'):
                        continue
                    
                    # Create document with composite key
                    doc_id = f"{sport}_{game['id']}"
                    doc_ref = db.collection(cls.SPORTS_GAMES_COLLECTION).document(doc_id)
                    
                    # Check if game already exists
                    existing_doc = doc_ref.get()
                    
                    # Prepare game data
                    game_data = game.copy()
                    game_data.update({
                        'last_updated': timestamp,
                        'doc_id': doc_id,
                    })
                    
                    if existing_doc.exists:
                        # Game exists, check if we need to update
                        existing_data = existing_doc.to_dict()
                        
                        # Check for significant changes
                        needs_update = cls._needs_update(existing_data, game_data)
                        
                        if needs_update:
                            # Preserve original creation time
                            if 'first_seen' in existing_data:
                                game_data['first_seen'] = existing_data['first_seen']
                            
                            # Track update count
                            game_data['update_count'] = existing_data.get('update_count', 0) + 1
                            
                            # Store what changed
                            changes = cls._detect_changes(existing_data, game_data)
                            if changes:
                                game_data['last_changes'] = changes
                            
                            doc_ref.set(game_data, merge=True)
                            games_updated += 1
                            
                            if changes:
                                print(f"Updated {sport.upper()} game {game.get('away_team', {}).get('abbreviation', 'TBD')} @ {game.get('home_team', {}).get('abbreviation', 'TBD')}: {', '.join(changes)}")
                    else:
                        # New game
                        game_data['first_seen'] = timestamp
                        game_data['update_count'] = 0
                        doc_ref.set(game_data)
                        games_stored += 1
            
            # Store summary
            summary_doc_id = timestamp.strftime('%Y%m%d_%H%M%S')
            summary_ref = db.collection(cls.SPORTS_SUMMARIES_COLLECTION).document(summary_doc_id)
            
            summary_data = summary.copy()
            summary_data.update({
                'timestamp': timestamp,
                'doc_id': summary_doc_id,
                'games_stored': games_stored,
                'games_updated': games_updated,
            })
            
            summary_ref.set(summary_data)
            
            print(f"Successfully processed games: {games_stored} new, {games_updated} updated")
            
            # Clean up old data less frequently (only every 6 hours)
            if timestamp.hour % 6 == 0 and timestamp.minute < 30:
                cls._cleanup_old_data()
            
            return True
            
        except Exception as e:
            print(f"Error storing sports data in Firestore: {e}")
            return False
    
    @classmethod
    def get_upcoming_games(cls, sport: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get upcoming games from Firestore.
        
        Args:
            sport: Optional sport filter
            limit: Maximum number of games to return
            
        Returns:
            List of upcoming games
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            query = db.collection(cls.SPORTS_GAMES_COLLECTION)
            
            # Filter by sport if specified
            if sport:
                query = query.where('sport_code', '==', sport)
            
            # Only get future games
            now = datetime.now(timezone.utc)
            query = query.where('timestamp', '>', now.timestamp())
            
            # Order by date
            query = query.order_by('timestamp').limit(limit)
            
            games = []
            for doc in query.stream():
                game_data = doc.to_dict()
                games.append(game_data)
            
            return games
            
        except Exception as e:
            print(f"Error fetching upcoming games: {e}")
            return []
    
    @classmethod
    def get_games_by_date(cls, date: datetime, sport: Optional[str] = None) -> List[Dict]:
        """Get games for a specific date.
        
        Args:
            date: Date to fetch games for
            sport: Optional sport filter
            
        Returns:
            List of games for the specified date
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            # Date range for the entire day
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            query = db.collection(cls.SPORTS_GAMES_COLLECTION)
            
            if sport:
                query = query.where('sport_code', '==', sport)
            
            query = query.where('timestamp', '>=', start_of_day.timestamp())
            query = query.where('timestamp', '<=', end_of_day.timestamp())
            query = query.order_by('timestamp')
            
            games = []
            for doc in query.stream():
                game_data = doc.to_dict()
                games.append(game_data)
            
            return games
            
        except Exception as e:
            print(f"Error fetching games by date: {e}")
            return []
    
    @classmethod
    def get_latest_summary(cls) -> Optional[Dict]:
        """Get the most recent sports summary.
        
        Returns:
            Latest summary dictionary or None
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return None
        
        try:
            query = db.collection(cls.SPORTS_SUMMARIES_COLLECTION)\
                .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                .limit(1)
            
            docs = list(query.stream())
            if docs:
                return docs[0].to_dict()
            
            return None
            
        except Exception as e:
            print(f"Error fetching latest summary: {e}")
            return None
    
    @classmethod
    def get_games_by_team(cls, team_name: str, limit: int = 20) -> List[Dict]:
        """Get games for a specific team.
        
        Args:
            team_name: Team name to search for
            limit: Maximum number of games to return
            
        Returns:
            List of games for the specified team
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            # Search in both home and away team names
            games = []
            
            # Query for home team
            home_query = db.collection(cls.SPORTS_GAMES_COLLECTION)\
                .where('home_team.name', '==', team_name)\
                .order_by('timestamp')\
                .limit(limit // 2)
            
            for doc in home_query.stream():
                games.append(doc.to_dict())
            
            # Query for away team
            away_query = db.collection(cls.SPORTS_GAMES_COLLECTION)\
                .where('away_team.name', '==', team_name)\
                .order_by('timestamp')\
                .limit(limit // 2)
            
            for doc in away_query.stream():
                games.append(doc.to_dict())
            
            # Sort by timestamp and remove duplicates
            games = list({game['doc_id']: game for game in games}.values())
            games.sort(key=lambda x: x.get('timestamp', 0))
            
            return games[:limit]
            
        except Exception as e:
            print(f"Error fetching games by team: {e}")
            return []
    
    @classmethod
    def _needs_update(cls, existing_data: Dict, new_data: Dict) -> bool:
        """Check if a game needs to be updated based on significant changes.
        
        Args:
            existing_data: Current game data in database
            new_data: New game data from API
            
        Returns:
            True if update is needed, False otherwise
        """
        # Always update if more than 30 minutes have passed
        if existing_data.get('last_updated'):
            time_diff = new_data['last_updated'] - existing_data['last_updated']
            if time_diff.total_seconds() > 1800:  # 30 minutes
                return True
        
        # Check for status changes
        if existing_data.get('status') != new_data.get('status'):
            return True
        
        # Check for score changes
        if (existing_data.get('home_score') != new_data.get('home_score') or
            existing_data.get('away_score') != new_data.get('away_score')):
            return True
        
        # Check for time remaining changes (for live games)
        if existing_data.get('time_remaining') != new_data.get('time_remaining'):
            return True
        
        # Check for broadcast changes
        existing_broadcasts = existing_data.get('broadcasts', [])
        new_broadcasts = new_data.get('broadcasts', [])
        if len(existing_broadcasts) != len(new_broadcasts):
            return True
        
        # Check for venue changes (rare but possible)
        if existing_data.get('venue') != new_data.get('venue'):
            return True
        
        return False
    
    @classmethod
    def _detect_changes(cls, existing_data: Dict, new_data: Dict) -> List[str]:
        """Detect what specific fields have changed.
        
        Args:
            existing_data: Current game data in database
            new_data: New game data from API
            
        Returns:
            List of change descriptions
        """
        changes = []
        
        # Status changes
        if existing_data.get('status') != new_data.get('status'):
            changes.append(f"status: {existing_data.get('status')} → {new_data.get('status')}")
        
        # Score changes
        old_home = existing_data.get('home_score')
        new_home = new_data.get('home_score')
        old_away = existing_data.get('away_score')
        new_away = new_data.get('away_score')
        
        if old_home != new_home or old_away != new_away:
            old_score = f"{old_away or 0}-{old_home or 0}"
            new_score = f"{new_away or 0}-{new_home or 0}"
            changes.append(f"score: {old_score} → {new_score}")
        
        # Time remaining changes
        if existing_data.get('time_remaining') != new_data.get('time_remaining'):
            changes.append(f"time: {existing_data.get('time_remaining')} → {new_data.get('time_remaining')}")
        
        # Broadcast changes
        existing_broadcasts = [b.get('network') for b in existing_data.get('broadcasts', []) if b.get('network')]
        new_broadcasts = [b.get('network') for b in new_data.get('broadcasts', []) if b.get('network')]
        
        if set(existing_broadcasts) != set(new_broadcasts):
            changes.append(f"broadcasts updated")
        
        return changes
    
    @classmethod
    def _cleanup_old_data(cls):
        """Clean up old sports data (older than 30 days)."""
        db = FirebaseStorage.get_db()
        if not db:
            return
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            
            # Clean up old games
            old_games_query = db.collection(cls.SPORTS_GAMES_COLLECTION)\
                .where('last_updated', '<', cutoff_date)\
                .limit(100)  # Process in batches
            
            old_games = list(old_games_query.stream())
            if old_games:
                batch = db.batch()
                for doc in old_games:
                    batch.delete(doc.reference)
                batch.commit()
                print(f"Cleaned up {len(old_games)} old games")
            
            # Clean up old summaries (keep only last 30 days)
            old_summaries_query = db.collection(cls.SPORTS_SUMMARIES_COLLECTION)\
                .where('timestamp', '<', cutoff_date)\
                .limit(50)
            
            old_summaries = list(old_summaries_query.stream())
            if old_summaries:
                batch = db.batch()
                for doc in old_summaries:
                    batch.delete(doc.reference)
                batch.commit()
                print(f"Cleaned up {len(old_summaries)} old summaries")
            
            # Clean up old game summaries
            cls.cleanup_old_game_summaries(days=30)
                
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    @classmethod
    def get_live_games(cls, sport: Optional[str] = None) -> List[Dict]:
        """Get currently live/in-progress games.
        
        Args:
            sport: Optional sport filter
            
        Returns:
            List of live games
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            query = db.collection(cls.SPORTS_GAMES_COLLECTION)
            
            # Filter by sport if specified
            if sport:
                query = query.where('sport_code', '==', sport)
            
            # Get all games and filter for live ones
            all_games = query.stream()
            live_games = []
            
            for doc in all_games:
                game_data = doc.to_dict()
                status = game_data.get('status', '').lower()
                
                # Check if game is currently live/in-progress
                if any(keyword in status for keyword in ['live', 'in progress', 'active', '1st', '2nd', '3rd', '4th', 'quarter', 'period', 'inning', 'half']):
                    live_games.append(game_data)
            
            # Sort by last_updated (most recently updated first)
            live_games.sort(key=lambda x: x.get('last_updated', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            
            return live_games
            
        except Exception as e:
            print(f"Error fetching live games: {e}")
            return []
    
    @classmethod 
    def get_recently_updated_games(cls, hours: int = 2, sport: Optional[str] = None) -> List[Dict]:
        """Get games that have been updated recently.
        
        Args:
            hours: How many hours back to look for updates
            sport: Optional sport filter
            
        Returns:
            List of recently updated games
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            query = db.collection(cls.SPORTS_GAMES_COLLECTION)
            
            if sport:
                query = query.where('sport_code', '==', sport)
            
            query = query.where('last_updated', '>=', cutoff_time)
            query = query.order_by('last_updated', direction=firestore.Query.DESCENDING)
            
            games = []
            for doc in query.stream():
                game_data = doc.to_dict()
                # Only include games that have been updated (not just created)
                if game_data.get('update_count', 0) > 0:
                    games.append(game_data)
            
            return games
            
        except Exception as e:
            print(f"Error fetching recently updated games: {e}")
            return []
    
    @classmethod
    def get_sports_stats(cls) -> Dict:
        """Get statistics about stored sports data.
        
        Returns:
            Statistics dictionary
        """
        db = FirebaseStorage.get_db()
        if not db:
            return {}
        
        try:
            stats = {
                'total_games': 0,
                'by_sport': {},
                'upcoming_games': 0,
                'last_update': None,
            }
            
            # Count total games
            all_games = db.collection(cls.SPORTS_GAMES_COLLECTION).stream()
            now = datetime.now(timezone.utc).timestamp()
            
            for doc in all_games:
                game = doc.to_dict()
                stats['total_games'] += 1
                
                sport = game.get('sport_code', 'unknown')
                if sport not in stats['by_sport']:
                    stats['by_sport'][sport] = {
                        'total': 0,
                        'upcoming': 0,
                        'sport_name': game.get('sport', sport.upper())
                    }
                
                stats['by_sport'][sport]['total'] += 1
                
                if game.get('timestamp', 0) > now:
                    stats['upcoming_games'] += 1
                    stats['by_sport'][sport]['upcoming'] += 1
                
                # Track latest update
                last_updated = game.get('last_updated')
                if last_updated and (not stats['last_update'] or last_updated > stats['last_update']):
                    stats['last_update'] = last_updated
            
            return stats
            
        except Exception as e:
            print(f"Error getting sports stats: {e}")
            return {}
    
    @classmethod
    def store_news_summaries(cls, news_summaries: Dict[str, Dict]) -> bool:
        """Store sports news summaries in Firestore.
        
        Args:
            news_summaries: Dictionary of news summaries by sport code
            
        Returns:
            True if successful, False otherwise
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return False
        
        try:
            timestamp = datetime.now(timezone.utc)
            
            for sport_code, summary_data in news_summaries.items():
                # Create document with timestamp and sport
                doc_id = f"{sport_code}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
                doc_ref = db.collection(cls.SPORTS_NEWS_SUMMARIES_COLLECTION).document(doc_id)
                
                # Add metadata
                summary_data.update({
                    'doc_id': doc_id,
                    'timestamp': timestamp,
                })
                
                doc_ref.set(summary_data)
            
            print(f"Successfully stored {len(news_summaries)} sports news summaries")
            
            # Clean up old news summaries (older than 7 days)
            cls._cleanup_old_news_summaries()
            
            return True
            
        except Exception as e:
            print(f"Error storing sports news summaries: {e}")
            return False
    
    @classmethod
    def get_latest_news_summaries(cls) -> Dict[str, Dict]:
        """Get the latest news summaries for all sports.
        
        Returns:
            Dictionary of latest news summaries by sport code
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return {}
        
        try:
            summaries = {}
            
            # Get latest summary for each sport
            for sport_code in ['nfl', 'nba', 'mlb', 'nhl', 'ncaaf', 'ncaab', 'mls']:
                query = db.collection(cls.SPORTS_NEWS_SUMMARIES_COLLECTION)\
                    .where('sport_code', '==', sport_code)\
                    .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                    .limit(1)
                
                docs = list(query.stream())
                if docs:
                    summaries[sport_code] = docs[0].to_dict()
            
            return summaries
            
        except Exception as e:
            print(f"Error fetching latest news summaries: {e}")
            return {}
    
    @classmethod
    def get_news_summary_by_sport(cls, sport_code: str, limit: int = 5) -> List[Dict]:
        """Get recent news summaries for a specific sport.
        
        Args:
            sport_code: Sport code to fetch summaries for
            limit: Maximum number of summaries to return
            
        Returns:
            List of news summaries for the sport
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            query = db.collection(cls.SPORTS_NEWS_SUMMARIES_COLLECTION)\
                .where('sport_code', '==', sport_code)\
                .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                .limit(limit)
            
            summaries = []
            for doc in query.stream():
                summaries.append(doc.to_dict())
            
            return summaries
            
        except Exception as e:
            print(f"Error fetching news summaries for {sport_code}: {e}")
            return []
    
    @classmethod
    def _cleanup_old_news_summaries(cls):
        """Clean up news summaries older than 7 days."""
        db = FirebaseStorage.get_db()
        if not db:
            return
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            
            query = db.collection(cls.SPORTS_NEWS_SUMMARIES_COLLECTION)\
                .where('timestamp', '<', cutoff_date)
            
            docs = list(query.stream())
            
            for doc in docs:
                doc.reference.delete()
            
            if docs:
                print(f"Cleaned up {len(docs)} old news summaries")
                
        except Exception as e:
            print(f"Error cleaning up old news summaries: {e}")
    
    @classmethod
    def update_live_games_only(cls, live_games: Dict[str, List[Dict]]) -> Dict:
        """Update only live games with current scores and time.
        
        This is a lightweight update method that only touches games that:
        1. Already exist in the database
        2. Are currently live/in-progress
        3. Have actual changes in score, status, or time
        
        Args:
            live_games: Dictionary of live games by sport
            
        Returns:
            Dictionary with update statistics
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return {'success': False, 'error': 'No database connection'}
        
        try:
            timestamp = datetime.now(timezone.utc)
            
            update_stats = {
                'success': True,
                'total_processed': 0,
                'games_updated': 0,
                'games_skipped': 0,
                'games_not_found': 0,
                'by_sport': {},
                'live_games_found': [],
                'updates_made': []
            }
            
            for sport, games in live_games.items():
                sport_stats = {
                    'processed': 0,
                    'updated': 0,
                    'skipped': 0,
                    'not_found': 0
                }
                
                for game in games:
                    if not game.get('id'):
                        continue
                    
                    update_stats['total_processed'] += 1
                    sport_stats['processed'] += 1
                    
                    # Create document ID
                    doc_id = f"{sport}_{game['id']}"
                    doc_ref = db.collection(cls.SPORTS_GAMES_COLLECTION).document(doc_id)
                    
                    # Check if game exists
                    existing_doc = doc_ref.get()
                    
                    if not existing_doc.exists:
                        # Game doesn't exist in database, skip live update
                        update_stats['games_not_found'] += 1
                        sport_stats['not_found'] += 1
                        print(f"Skipping {sport.upper()} game {game.get('away_team', {}).get('abbreviation', 'TBD')} @ {game.get('home_team', {}).get('abbreviation', 'TBD')} - not in database")
                        continue
                    
                    existing_data = existing_doc.to_dict()
                    
                    # Prepare minimal update data focused on live changes
                    update_data = {
                        'status': game.get('status'),
                        'home_score': game.get('home_score'),
                        'away_score': game.get('away_score'),
                        'time_remaining': game.get('time_remaining'),
                        'last_updated': timestamp,
                    }
                    
                    # Update team scores if available
                    if game.get('home_team', {}).get('score') is not None:
                        update_data['home_team.score'] = game['home_team']['score']
                    if game.get('away_team', {}).get('score') is not None:
                        update_data['away_team.score'] = game['away_team']['score']
                    
                    # Check if update is needed using focused live game criteria
                    needs_update = cls._needs_live_update(existing_data, update_data)
                    
                    if needs_update:
                        # Detect what changed
                        changes = cls._detect_live_changes(existing_data, update_data)
                        
                        if changes:
                            # Update only the changed fields
                            update_data['update_count'] = existing_data.get('update_count', 0) + 1
                            update_data['last_changes'] = changes
                            update_data['live_update'] = True  # Flag to indicate this was a live update
                            
                            # Use merge=True to only update specified fields
                            doc_ref.set(update_data, merge=True)
                            
                            update_stats['games_updated'] += 1
                            sport_stats['updated'] += 1
                            
                            # Track the update for logging
                            game_info = {
                                'sport': sport.upper(),
                                'away_team': game.get('away_team', {}).get('abbreviation', 'TBD'),
                                'home_team': game.get('home_team', {}).get('abbreviation', 'TBD'),
                                'changes': changes,
                                'score': f"{game.get('away_score', 0)}-{game.get('home_score', 0)}",
                                'status': game.get('status'),
                                'time_remaining': game.get('time_remaining', '')
                            }
                            update_stats['updates_made'].append(game_info)
                            update_stats['live_games_found'].append(game_info)
                            
                            print(f"🔴 Updated live {sport.upper()} game: {game_info['away_team']} {game.get('away_score', 0)} - {game.get('home_score', 0)} {game_info['home_team']} ({', '.join(changes)})")
                        else:
                            update_stats['games_skipped'] += 1
                            sport_stats['skipped'] += 1
                    else:
                        update_stats['games_skipped'] += 1
                        sport_stats['skipped'] += 1
                
                if sport_stats['processed'] > 0:
                    update_stats['by_sport'][sport] = sport_stats
            
            print(f"Live games update complete: {update_stats['games_updated']} updated, {update_stats['games_skipped']} skipped, {update_stats['games_not_found']} not found in database")
            
            return update_stats
            
        except Exception as e:
            print(f"Error updating live games: {e}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _needs_live_update(cls, existing_data: Dict, update_data: Dict) -> bool:
        """Check if a live game needs updating - more aggressive than regular updates.
        
        Args:
            existing_data: Current game data in database
            update_data: New live game data
            
        Returns:
            True if update is needed, False otherwise
        """
        # Always update if more than 2 minutes have passed (live games change frequently)
        if existing_data.get('last_updated'):
            time_diff = update_data['last_updated'] - existing_data['last_updated']
            if time_diff.total_seconds() > 120:  # 2 minutes
                return True
        
        # Check for any score changes
        if (existing_data.get('home_score') != update_data.get('home_score') or
            existing_data.get('away_score') != update_data.get('away_score')):
            return True
        
        # Check for status changes
        if existing_data.get('status') != update_data.get('status'):
            return True
        
        # Check for time remaining changes
        if existing_data.get('time_remaining') != update_data.get('time_remaining'):
            return True
        
        return False
    
    @classmethod
    def _detect_live_changes(cls, existing_data: Dict, update_data: Dict) -> List[str]:
        """Detect changes in live game data.
        
        Args:
            existing_data: Current game data in database
            update_data: New live game data
            
        Returns:
            List of change descriptions
        """
        changes = []
        
        # Score changes
        old_home = existing_data.get('home_score')
        new_home = update_data.get('home_score')
        old_away = existing_data.get('away_score')
        new_away = update_data.get('away_score')
        
        if old_home != new_home or old_away != new_away:
            old_score = f"{old_away or 0}-{old_home or 0}"
            new_score = f"{new_away or 0}-{new_home or 0}"
            changes.append(f"score: {old_score} → {new_score}")
        
        # Status changes
        if existing_data.get('status') != update_data.get('status'):
            changes.append(f"status: {existing_data.get('status')} → {update_data.get('status')}")
        
        # Time remaining changes
        if existing_data.get('time_remaining') != update_data.get('time_remaining'):
            old_time = existing_data.get('time_remaining') or 'No time'
            new_time = update_data.get('time_remaining') or 'No time'
            changes.append(f"time: {old_time} → {new_time}")
        
        return changes
    
    @classmethod
    def store_game_summary(cls, summary_data: Dict) -> bool:
        """Store a game summary in Firestore.
        
        Args:
            summary_data: Dictionary containing game summary data
            
        Returns:
            True if successful, False otherwise
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return False
        
        try:
            # Create unique document ID
            game_id = summary_data.get('game_id')
            summary_type = summary_data.get('summary_type')  # 'pre_game' or 'post_game'
            timestamp = summary_data.get('generated_at', datetime.now(timezone.utc))
            
            doc_id = f"{game_id}_{summary_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            doc_ref = db.collection(cls.GAME_SUMMARIES_COLLECTION).document(doc_id)
            
            # Add metadata
            summary_data.update({
                'doc_id': doc_id,
                'stored_at': datetime.now(timezone.utc),
            })
            
            doc_ref.set(summary_data)
            print(f"Stored {summary_type} summary for game {game_id}")
            return True
            
        except Exception as e:
            print(f"Error storing game summary: {e}")
            return False
    
    @classmethod
    def has_game_summary(cls, game_id: str, summary_type: str) -> bool:
        """Check if a game summary already exists.
        
        Args:
            game_id: Game ID
            summary_type: 'pre_game' or 'post_game'
            
        Returns:
            True if summary exists, False otherwise
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return False
        
        try:
            # Query for existing summaries
            query = db.collection(cls.GAME_SUMMARIES_COLLECTION)\
                .where('game_id', '==', game_id)\
                .where('summary_type', '==', summary_type)\
                .limit(1)
            
            docs = list(query.stream())
            return len(docs) > 0
            
        except Exception as e:
            print(f"Error checking existing game summary: {e}")
            return False
    
    @classmethod
    def get_game_summaries(cls, game_id: str) -> List[Dict]:
        """Get all summaries for a specific game.
        
        Args:
            game_id: Game ID
            
        Returns:
            List of game summaries
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            query = db.collection(cls.GAME_SUMMARIES_COLLECTION)\
                .where('game_id', '==', game_id)\
                .order_by('generated_at')
            
            summaries = []
            for doc in query.stream():
                summary_data = doc.to_dict()
                summaries.append(summary_data)
            
            return summaries
            
        except Exception as e:
            print(f"Error fetching game summaries: {e}")
            return []
    
    @classmethod
    def get_recent_game_summaries(cls, hours: int = 24) -> List[Dict]:
        """Get recently generated game summaries.
        
        Args:
            hours: How many hours back to look
            
        Returns:
            List of recent game summaries
        """
        db = FirebaseStorage.get_db()
        if not db:
            print("No Firestore connection available")
            return []
        
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            query = db.collection(cls.GAME_SUMMARIES_COLLECTION)\
                .where('generated_at', '>=', cutoff_time)\
                .order_by('generated_at', direction=firestore.Query.DESCENDING)
            
            summaries = []
            for doc in query.stream():
                summary_data = doc.to_dict()
                summaries.append(summary_data)
            
            return summaries
            
        except Exception as e:
            print(f"Error fetching recent game summaries: {e}")
            return []
    
    @classmethod
    def cleanup_old_game_summaries(cls, days: int = 30):
        """Clean up old game summaries.
        
        Args:
            days: Delete summaries older than this many days
        """
        db = FirebaseStorage.get_db()
        if not db:
            return
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Clean up old game summaries
            old_summaries_query = db.collection(cls.GAME_SUMMARIES_COLLECTION)\
                .where('generated_at', '<', cutoff_date)\
                .limit(100)  # Process in batches
            
            old_summaries = list(old_summaries_query.stream())
            if old_summaries:
                batch = db.batch()
                for doc in old_summaries:
                    batch.delete(doc.reference)
                batch.commit()
                print(f"Cleaned up {len(old_summaries)} old game summaries")
                
        except Exception as e:
            print(f"Error cleaning up old game summaries: {e}") 