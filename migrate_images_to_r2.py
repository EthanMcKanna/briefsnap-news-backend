#!/usr/bin/env python3
"""
Migration script to upload existing external images to Cloudflare R2.
This script scans all articles in Firebase and uploads any external images to R2.
"""

import os
import sys
from pathlib import Path
import time

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables if .env file exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed, skipping .env file loading")

from newsaggregator.storage.firebase_storage import FirebaseStorage
from newsaggregator.utils.r2_storage import r2_storage
from newsaggregator.config.settings import FIRESTORE_ARTICLES_COLLECTION, IMAGE_OPTIMIZATION
from datetime import datetime, timezone

def main():
    """Main migration function."""
    print("🔄 Briefsnap Image Migration to R2 with Optimization")
    print("=" * 50)
    
    # Check if R2 is enabled
    if not r2_storage.enabled:
        print("❌ R2 storage is not enabled!")
        print("Please set the following environment variables:")
        print("- R2_ACCOUNT_ID")
        print("- R2_ACCESS_KEY_ID") 
        print("- R2_SECRET_ACCESS_KEY")
        return False
    
    print("✅ R2 storage is enabled")
    
    # Show optimization settings
    print(f"📝 Image Optimization Settings:")
    print(f"   - Enabled: {IMAGE_OPTIMIZATION['enabled']}")
    print(f"   - Convert to WebP: {IMAGE_OPTIMIZATION['convert_to_webp']}")
    print(f"   - Max dimensions: {IMAGE_OPTIMIZATION['max_width']}x{IMAGE_OPTIMIZATION['max_height']}")
    print(f"   - WebP quality: {IMAGE_OPTIMIZATION['webp_quality']}%")
    print(f"   - Max file size: {IMAGE_OPTIMIZATION['max_file_size'] / (1024*1024):.1f}MB")
    
    # Test R2 connection
    if not r2_storage.check_r2_connection():
        print("❌ R2 connection failed!")
        return False
    
    # Configure bucket for optimal Cloudflare integration
    print("\n🔧 Configuring bucket for Cloudflare...")
    try:
        config_success = r2_storage.configure_bucket_for_cloudflare()
        if config_success:
            print("✅ Bucket configured successfully")
        else:
            print("⚠️  Bucket configuration had some issues, but continuing...")
    except Exception as e:
        print(f"⚠️  Bucket configuration error: {e}, but continuing...")
    
    # Initialize Firebase
    FirebaseStorage.initialize()
    db = FirebaseStorage.get_db()
    if not db:
        print("❌ Failed to connect to Firestore")
        return False
    
    print("✅ Connected to Firestore")
    
    # Get all articles
    print("\n📄 Fetching articles from Firestore...")
    articles_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION)
    articles = articles_ref.stream()
    
    # Convert to list for processing
    articles_list = []
    for article in articles:
        article_data = article.to_dict()
        article_data['doc_id'] = article.id
        articles_list.append(article_data)
    
    print(f"Found {len(articles_list)} articles")
    
    # Filter articles with external images
    external_images = []
    for article in articles_list:
        img_url = article.get('img_url')
        if img_url and 'images.briefsnap.com' not in img_url:
            external_images.append(article)
    
    print(f"Found {len(external_images)} articles with external images")
    
    if not external_images:
        print("🎉 No external images found! All images are already hosted on R2.")
        return True
    
    # Ask for confirmation
    print(f"\n⚠️  This will download, optimize, and upload {len(external_images)} images to R2.")
    print("Images will be optimized (WebP conversion, resizing, compression) before upload.")
    print("This process may take several minutes depending on image sizes and optimization.")
    
    if input("Continue? (y/N): ").lower() != 'y':
        print("Migration cancelled.")
        return False
    
    # Process each article
    processed = 0
    failed = 0
    skipped = 0
    
    print(f"\n🚀 Starting migration of {len(external_images)} images...")
    print("-" * 50)
    
    for i, article in enumerate(external_images, 1):
        doc_id = article['doc_id']
        title = article.get('title', 'Unknown title')
        img_url = article.get('img_url')
        
        print(f"[{i}/{len(external_images)}] Processing: {title[:50]}...")
        
        try:
            # Upload image to R2
            r2_url = r2_storage.upload_image_from_url(img_url, title)
            
            if r2_url:
                # Update the article in Firestore
                article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
                article_ref.update({
                    'img_url': r2_url,
                    'updated_at': datetime.now(timezone.utc),
                    'migrated_to_r2': True,
                    'original_img_url': img_url
                })
                
                print(f"  ✅ Uploaded to: {r2_url}")
                processed += 1
            else:
                print(f"  ❌ Failed to upload image")
                failed += 1
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            failed += 1
        
        # Add a small delay to be respectful to external servers
        time.sleep(1)
    
    # Print summary
    print("-" * 50)
    print(f"📊 Migration Summary:")
    print(f"  ✅ Successfully migrated: {processed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📋 Total processed: {processed + failed}")
    
    if processed > 0:
        print(f"\n🎉 Migration completed! {processed} images are now hosted on R2.")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 