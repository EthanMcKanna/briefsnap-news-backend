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