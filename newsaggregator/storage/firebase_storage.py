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
            # Add topic to summary document
            summary_ref = db.collection(FIRESTORE_COLLECTION).add({
                'summary': summary_data.get('Summary', ''),
                'topic': topic,
                'timestamp': datetime.now(timezone.utc),
                'created_at': firestore.SERVER_TIMESTAMP
            })

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