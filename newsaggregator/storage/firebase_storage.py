"""Firebase/Firestore storage for news articles and summaries."""

import re
import uuid
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore, messaging

from newsaggregator.config.settings import (
    FIREBASE_CREDS_PATH, FIRESTORE_COLLECTION, FIRESTORE_ARTICLES_COLLECTION,
    MINIMUM_TITLE_LENGTH, SIMILARITY_THRESHOLD, TITLE_SIMILARITY_THRESHOLD,
    CONTENT_SIMILARITY_THRESHOLD, LOOKBACK_PERIOD
)
from newsaggregator.utils.similarity import calculate_similarity, clean_text_for_comparison

class FirebaseStorage:
    """Class for Firebase/Firestore storage operations."""
    
    _db = None
    _initialized = False
    
    # Constants for collection names
    WEEKLY_SUMMARIES_COLLECTION = 'weekly_summaries'
    
    @classmethod
    def initialize(cls):
        """Initialize Firebase Admin SDK.
        
        Returns:
            Firestore database client or None if initialization fails
        """
        if cls._initialized:
            return cls._db
            
        try:
            # Check if any Firebase apps are already initialized
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_CREDS_PATH)
                firebase_admin.initialize_app(cred)
                
            # Get the default app's Firestore client
            cls._db = firestore.client()
            cls._initialized = True
            return cls._db
        except Exception as e:
            print(f"Failed to initialize Firebase: {e}")
            cls._initialized = False
            cls._db = None
            return None
    
    @classmethod
    def get_db(cls):
        """Get the Firestore database client.
        
        Returns:
            Firestore database client or None if not initialized
        """
        if not cls._initialized:
            return cls.initialize()
        return cls._db
    
    @staticmethod
    def generate_story_id():
        """Generate a unique ID for a story.
        
        Returns:
            Unique UUID string
        """
        return str(uuid.uuid4())
    
    @staticmethod
    def generate_slug(title):
        """Generate a URL-friendly slug from a title.
        
        Args:
            title: Article title
            
        Returns:
            URL-friendly slug
        """
        # Convert to lowercase and replace non-alphanumeric chars with hyphens
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower())
        # Remove leading/trailing hyphens
        slug = re.sub(r'(^-|-$)', '', slug)
        # Limit length to 100 chars
        return slug[:100]
    
    @classmethod
    def is_duplicate_article(cls, story_title, story_description):
        """Enhanced duplicate detection using multiple similarity checks.
        
        Args:
            story_title: Title of the story to check
            story_description: Description of the story to check
            
        Returns:
            True if duplicate, False otherwise
        """
        db = cls.get_db()
        if not db:
            print("No Firestore connection available for duplicate detection")
            return False
            
        try:
            if len(clean_text_for_comparison(story_title)) < MINIMUM_TITLE_LENGTH:
                print(f"Title too short for reliable comparison: {story_title}")
                return False

            time_threshold = datetime.now(timezone.utc) - timedelta(seconds=LOOKBACK_PERIOD)
            recent_articles = db.collection(FIRESTORE_ARTICLES_COLLECTION)\
                .where('timestamp', '>=', time_threshold)\
                .stream()

            # Clean and normalize the new article text
            clean_new_title = clean_text_for_comparison(story_title)
            clean_new_desc = clean_text_for_comparison(story_description)

            for article in recent_articles:
                article_data = article.to_dict()
                
                # Clean and normalize existing article text
                clean_existing_title = clean_text_for_comparison(article_data.get('title', ''))
                clean_existing_desc = clean_text_for_comparison(article_data.get('description', ''))

                # Calculate various similarity scores
                title_similarity = calculate_similarity(clean_new_title, clean_existing_title)
                
                # Check for exact title matches first
                if clean_new_title == clean_existing_title:
                    print(f"Exact title match found: {story_title}")
                    return True

                # Check if title is very similar
                if title_similarity > TITLE_SIMILARITY_THRESHOLD:
                    print(f"High title similarity ({title_similarity:.2f}): {story_title}")
                    return True

                # If titles are somewhat similar, check description
                if title_similarity > SIMILARITY_THRESHOLD:
                    desc_similarity = calculate_similarity(clean_new_desc, clean_existing_desc)
                    
                    if desc_similarity > CONTENT_SIMILARITY_THRESHOLD:
                        print(f"Similar content found for: {story_title}")
                        print(f"Title similarity: {title_similarity:.2f}")
                        print(f"Description similarity: {desc_similarity:.2f}")
                        return True

                # Check for substring containment
                if (clean_new_title in clean_existing_title or 
                    clean_existing_title in clean_new_title):
                    print(f"Title substring match found: {story_title}")
                    return True

            return False
            
        except Exception as e:
            print(f"Error checking for duplicate article: {e}")
            return False
    
    @classmethod
    def send_fcm_notification(cls, topic, title, body, data):
        """Send FCM notification to a specific topic for iOS devices.
        
        Args:
            topic: FCM topic to send to
            title: Notification title
            body: Notification body
            data: Additional notification data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create the notification
            notification = messaging.Notification(
                title=title,
                body=body,
            )
            
            # Create the APNS config specifically for iOS
            apns_config = messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                        badge=0,
                        content_available=True  # Enable background delivery
                    )
                ),
                headers={
                    'apns-priority': '10',  # High priority
                    'apns-push-type': 'alert'
                }
            )
            
            # Create the message without Android config
            message = messaging.Message(
                notification=notification,
                data=data,
                topic=topic,
                apns=apns_config
            )
            
            # Send message
            response = messaging.send(message)
            print(f'Successfully sent notification to topic {topic}: {response}')
            return True
        except Exception as e:
            print(f'Error sending notification: {e}')
            return False
    
    @classmethod
    def upload_to_firestore(cls, summary_data, topic='TOP_NEWS'):
        """Upload summary and stories to Firestore with topic information.
        
        Args:
            summary_data: Dictionary containing Summary and Stories fields
            topic: Topic of the summary
            
        Returns:
            True if successful, False otherwise
        """
        db = cls.get_db()
        if not db:
            print("Firestore client not initialized")
            return False
        
        try:
            # Add topic to summary document with brief summary and bullet points if available
            summary_doc = {
                'summary': summary_data.get('Summary', ''),
                'topic': topic,
                'timestamp': datetime.now(timezone.utc),
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            # Add brief summary and bullet points if available
            if 'brief_summary' in summary_data:
                summary_doc['brief_summary'] = summary_data.get('brief_summary', '')
                summary_doc['brief_updated_at'] = datetime.now(timezone.utc)
            
            if 'bullet_points' in summary_data:
                summary_doc['bullet_points'] = summary_data.get('bullet_points', [])
            
            # Add to Firestore
            summary_ref = db.collection(FIRESTORE_COLLECTION).add(summary_doc)
            
            print(f"Summary uploaded with fields: {', '.join(summary_doc.keys())}")

            # Add topic to article data and send notifications
            for story in summary_data.get('Stories', []):
                title = story.get('StoryTitle', '')
                description = story.get('StoryDescription', '')
                
                # Prevent publishing articles with no actual text
                if not description or not description.strip():
                    print(f"[WARNING] Skipping article with empty text: {title}")
                    continue
                
                # Generate base slug
                base_slug = cls.generate_slug(title)
                slug = base_slug
                counter = 1
                
                # Check for duplicate slugs
                while True:
                    duplicate_check = db.collection(FIRESTORE_ARTICLES_COLLECTION)\
                        .where('slug', '==', slug)\
                        .limit(1)\
                        .stream()
                    
                    if not any(duplicate_check):
                        break
                        
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                article_data = {
                    'id': story.get('id', cls.generate_story_id()),
                    'title': title,
                    'slug': slug,
                    'description': description,
                    'full_article': story.get('FullArticle', ''),
                    'citations': story.get('Citations', []),
                    'img_url': story.get('img_url'),
                    'topic': topic,
                    'summary_ref': summary_ref[1],
                    'timestamp': datetime.now(timezone.utc),
                    'created_at': firestore.SERVER_TIMESTAMP
                }
                
                # Add summary and key points if available
                if 'summary' in story:
                    article_data['summary'] = story.get('summary', '')
                    article_data['summaryGeneratedAt'] = firestore.SERVER_TIMESTAMP
                    
                if 'keyPoints' in story:
                    article_data['keyPoints'] = story.get('keyPoints', [])
                    article_data['keyPointsGeneratedAt'] = firestore.SERVER_TIMESTAMP
                
                # Add article to Firestore
                db.collection(FIRESTORE_ARTICLES_COLLECTION).add(article_data)
                print(f"Added new article with slug: {slug}")

                # Send FCM notification
                notification_data = {
                    'type': 'article',
                    'slug': slug
                }
                
                # Send to topic specific category
                topic_name = f"category_{topic.lower()}"
                cls.send_fcm_notification(
                    topic=topic_name,
                    title=title,
                    body=description[:150] + "..." if len(description) > 150 else description,
                    data=notification_data
                )

            print(f"Successfully uploaded {topic} summary and unique articles to Firestore")
            return True
        except Exception as e:
            print(f"Failed to upload to Firestore: {e}")
            return False 
    
    @classmethod
    def get_summaries_in_timeframe(cls, start_time, end_time):
        """Retrieve summaries from Firestore within a specific timeframe.
        
        Args:
            start_time: Start time for retrieval
            end_time: End time for retrieval
            
        Returns:
            Dictionary of summaries by topic
        """
        db = cls.get_db()
        if not db:
            print("Firestore client not initialized")
            return {}
            
        try:
            print(f"DEBUG: Retrieving summaries from {start_time.isoformat()} to {end_time.isoformat()}")
            
            # Query summaries in the specified timeframe
            summaries_by_topic = {}
            
            summary_refs = db.collection(FIRESTORE_COLLECTION)\
                .where('timestamp', '>=', start_time)\
                .where('timestamp', '<=', end_time)\
                .stream()
            
            summary_count = 0
            for summary_ref in summary_refs:
                summary_count += 1
                summary_data = summary_ref.to_dict()
                topic = summary_data.get('topic', 'TOP_NEWS')
                
                # Initialize list for this topic if not exists
                if topic not in summaries_by_topic:
                    summaries_by_topic[topic] = []
                    
                # Get articles for this summary
                articles = []
                articles_refs = db.collection(FIRESTORE_ARTICLES_COLLECTION)\
                    .where('summary_ref', '==', summary_ref.id)\
                    .stream()
                
                article_count = 0
                for article_ref in articles_refs:
                    article_count += 1
                    article_data = article_ref.to_dict()
                    articles.append({
                        'title': article_data.get('title', ''),
                        'content': article_data.get('description', ''),
                        'id': article_data.get('id', '')
                    })
                
                print(f"DEBUG: Found {article_count} articles for summary dated {summary_data.get('created_at', 'unknown date')} for topic {topic}")
                    
                # Add articles to summary data
                summary_data['Stories'] = articles
                
                # Add summary to list for this topic
                summaries_by_topic[topic].append(summary_data)
            
            print(f"DEBUG: Found a total of {summary_count} summaries from Firestore")
            print(f"DEBUG: Retrieved {sum(len(summaries) for summaries in summaries_by_topic.values())} summaries across {len(summaries_by_topic)} topics")
            
            # Log topics and counts
            for topic, summaries in summaries_by_topic.items():
                print(f"DEBUG: Topic {topic}: {len(summaries)} summaries")
            
            return summaries_by_topic
            
        except Exception as e:
            print(f"Error retrieving summaries from Firestore: {e}")
            return {}
    
    @classmethod
    def upload_weekly_summary(cls, weekly_summary):
        """Upload weekly summary to Firestore.
        
        Args:
            weekly_summary: Weekly summary data
            
        Returns:
            True if successful, False otherwise
        """
        db = cls.get_db()
        if not db:
            print("Firestore client not initialized")
            return False
            
        try:
            # Add weekly summary to Firestore
            db.collection(cls.WEEKLY_SUMMARIES_COLLECTION).add(weekly_summary)
            
            print(f"Successfully uploaded weekly summary for {weekly_summary.get('topic', 'unknown topic')}")
            
            # Only send notification for TOP_NEWS category
            if weekly_summary.get('topic', '') == 'TOP_NEWS':
                notification_data = {
                    'type': 'weekly_summary',
                    'topic': 'TOP_NEWS',
                    'title': "Your Weekly News Brief",
                    'body': "Your weekly news summary is ready",
                    'sound': "default",
                    'badge': "0"
                }
                
                # Send to specific topic channel
                topic_name = "weekly_top_news"
                
                cls.send_fcm_notification(
                    topic=topic_name,
                    title="Your Weekly News Brief",
                    body="Your weekly news summary is ready",
                    data=notification_data
                )
            
            return True
            
        except Exception as e:
            print(f"Error uploading weekly summary to Firestore: {e}")
            return False
            
    @classmethod
    def get_latest_weekly_summary(cls, topic):
        """Get the latest weekly summary for a topic.
        
        Args:
            topic: Topic to get summary for
            
        Returns:
            Latest weekly summary or None if not found
        """
        db = cls.get_db()
        if not db:
            print("Firestore client not initialized")
            return None
            
        try:
            # Query for the latest weekly summary for this topic
            summaries = db.collection(cls.WEEKLY_SUMMARIES_COLLECTION)\
                .where('topic', '==', topic)\
                .order_by('created_at', direction=firestore.Query.DESCENDING)\
                .limit(1)\
                .stream()
                
            for summary in summaries:
                return summary.to_dict()
                
            return None
            
        except Exception as e:
            print(f"Error getting latest weekly summary: {e}")
            return None 