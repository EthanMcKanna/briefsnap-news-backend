#!/usr/bin/env python3
"""
Migration script to upload and optimize images for Cloudflare R2.

This script scans all articles in Firebase and:
1. Uploads external images to R2 with optimization
2. Re-processes existing R2 images that need optimization (WebP conversion, compression)

Usage:
  python migrate_images_to_r2.py                 # Process images that need optimization
  python migrate_images_to_r2.py --force-reoptimize  # Re-process ALL R2 images
  python migrate_images_to_r2.py --help          # Show this help

The script automatically applies:
- WebP conversion for optimal compression
- Resolution capping (1200x800 max)
- EXIF orientation correction
- Quality optimization based on content type
- Proper caching headers for Cloudflare CDN
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
    
    # Check for command line arguments
    force_reoptimize = False
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help' or sys.argv[1] == '-h':
            print(__doc__)
            return True
        elif sys.argv[1] == '--force-reoptimize':
            force_reoptimize = True
            print("🔧 Force re-optimization mode enabled - will re-process ALL R2 images")
            print()
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use --help for usage information")
            return False
    
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
    
    # Filter articles with images that need processing
    images_to_process = []
    external_images = []
    r2_images_needing_optimization = []
    
    for article in articles_list:
        img_url = article.get('img_url')
        if not img_url:
            continue
            
        if 'images.briefsnap.com' not in img_url:
            # External image - needs migration
            external_images.append(article)
            images_to_process.append({
                'article': article,
                'type': 'external',
                'reason': 'External image needs migration to R2'
            })
        else:
            # Already on R2 - check if it needs optimization
            needs_optimization = False
            reason = ""
            
            if force_reoptimize:
                needs_optimization = True
                reason = 'Force re-optimization requested'
            elif not img_url.endswith('.webp'):
                needs_optimization = True
                reason = 'Non-WebP format needs conversion'
            elif not article.get('optimized', False):
                needs_optimization = True
                reason = 'Missing optimization flag'
            elif not article.get('optimization_applied_at'):
                needs_optimization = True
                reason = 'No optimization timestamp found'
                
            if needs_optimization:
                r2_images_needing_optimization.append(article)
                images_to_process.append({
                    'article': article,
                    'type': 'r2_optimization',
                    'reason': reason
                })
    
    print(f"Found {len(external_images)} articles with external images")
    print(f"Found {len(r2_images_needing_optimization)} R2 images needing optimization")
    print(f"Total images to process: {len(images_to_process)}")
    
    if not images_to_process:
        print("🎉 No images need processing! All images are optimized and hosted on R2.")
        return True
    
    # Ask for confirmation
    print(f"\n⚠️  This will process {len(images_to_process)} images:")
    print(f"   - {len(external_images)} external images will be migrated to R2")
    print(f"   - {len(r2_images_needing_optimization)} R2 images will be re-optimized")
    print()
    print("All images will be optimized (WebP conversion, resizing, compression) before upload.")
    print("This process may take several minutes depending on image sizes and optimization.")
    
    if input("Continue? (y/N): ").lower() != 'y':
        print("Migration cancelled.")
        return False
    
    # Process each image
    processed = 0
    failed = 0
    skipped = 0
    
    print(f"\n🚀 Starting processing of {len(images_to_process)} images...")
    print("-" * 60)
    
    for i, image_item in enumerate(images_to_process, 1):
        article = image_item['article']
        process_type = image_item['type']
        reason = image_item['reason']
        
        doc_id = article['doc_id']
        title = article.get('title', 'Unknown title')
        img_url = article.get('img_url')
        
        print(f"[{i}/{len(images_to_process)}] Processing: {title[:50]}...")
        print(f"  Type: {process_type}")
        print(f"  Reason: {reason}")
        print(f"  Current URL: {img_url}")
        
        try:
            # Upload/re-process image to R2 with optimization
            r2_url = r2_storage.upload_image_from_url(img_url, title)
            
            if r2_url:
                # Prepare update data
                update_data = {
                    'img_url': r2_url,
                    'updated_at': datetime.now(timezone.utc),
                    'optimized': True,
                    'optimization_applied_at': datetime.now(timezone.utc)
                }
                
                # For external images, preserve original URL
                if process_type == 'external':
                    update_data['migrated_to_r2'] = True
                    update_data['original_img_url'] = img_url
                else:
                    # For R2 re-optimization, preserve existing original URL if it exists
                    if 'original_img_url' not in article and not img_url.startswith('https://images.briefsnap.com'):
                        update_data['original_img_url'] = img_url
                    update_data['reoptimized'] = True
                
                # Update the article in Firestore
                article_ref = db.collection(FIRESTORE_ARTICLES_COLLECTION).document(doc_id)
                article_ref.update(update_data)
                
                print(f"  ✅ Processed to: {r2_url}")
                processed += 1
            else:
                print(f"  ❌ Failed to process image")
                failed += 1
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            failed += 1
        
        print("-" * 60)
        
        # Add a small delay to be respectful to servers
        time.sleep(1)
    
    # Print summary
    print("=" * 60)
    print(f"📊 Processing Summary:")
    print(f"  ✅ Successfully processed: {processed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📋 Total processed: {processed + failed}")
    print()
    print("📋 Processing Details:")
    print(f"  🔄 External images migrated: {len([x for x in images_to_process if x['type'] == 'external'])}")
    print(f"  🎨 R2 images optimized: {len([x for x in images_to_process if x['type'] == 'r2_optimization'])}")
    
    if processed > 0:
        print(f"\n🎉 Processing completed! {processed} images are now optimized on R2.")
        print("All processed images now have:")
        print("  - WebP format for optimal compression")
        print("  - Proper resolution limits applied")
        print("  - EXIF orientation correction")
        print("  - Optimized caching headers")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 