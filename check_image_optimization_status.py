#!/usr/bin/env python3
"""
Status check script for image optimization in Briefsnap News Backend.
This script analyzes all images in Firebase and shows optimization status.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

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
from newsaggregator.config.settings import FIRESTORE_ARTICLES_COLLECTION, IMAGE_OPTIMIZATION

def analyze_images():
    """Analyze image optimization status."""
    print("📊 Image Optimization Status Report")
    print("=" * 40)
    
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
    
    # Analyze images
    stats = {
        'total_articles': len(articles_list),
        'articles_with_images': 0,
        'external_images': 0,
        'r2_images': 0,
        'optimized_images': 0,
        'webp_images': 0,
        'non_webp_r2_images': 0,
        'missing_optimization_flag': 0,
        'recently_optimized': 0
    }
    
    image_breakdown = defaultdict(int)
    
    for article in articles_list:
        img_url = article.get('img_url')
        if not img_url:
            continue
            
        stats['articles_with_images'] += 1
        
        if 'images.briefsnap.com' not in img_url:
            stats['external_images'] += 1
            image_breakdown['External (needs migration)'] += 1
        else:
            stats['r2_images'] += 1
            
            if img_url.endswith('.webp'):
                stats['webp_images'] += 1
            else:
                stats['non_webp_r2_images'] += 1
                
            if article.get('optimized', False):
                stats['optimized_images'] += 1
                if article.get('optimization_applied_at'):
                    stats['recently_optimized'] += 1
                    image_breakdown['R2 + Optimized + WebP'] += 1
                else:
                    image_breakdown['R2 + Optimized (old)'] += 1
            else:
                stats['missing_optimization_flag'] += 1
                if img_url.endswith('.webp'):
                    image_breakdown['R2 + WebP (no flag)'] += 1
                else:
                    image_breakdown['R2 + Non-WebP (no flag)'] += 1
    
    # Print results
    print(f"\n📈 Summary Statistics:")
    print(f"  📄 Total articles: {stats['total_articles']}")
    print(f"  🖼️  Articles with images: {stats['articles_with_images']}")
    print(f"  🔗 External images: {stats['external_images']}")
    print(f"  ☁️  R2 hosted images: {stats['r2_images']}")
    print(f"  ✨ Optimized images: {stats['optimized_images']}")
    print(f"  🎨 WebP format images: {stats['webp_images']}")
    print(f"  ⚠️  Non-WebP R2 images: {stats['non_webp_r2_images']}")
    print(f"  🚩 Missing optimization flags: {stats['missing_optimization_flag']}")
    print(f"  🕒 Recently optimized: {stats['recently_optimized']}")
    
    print(f"\n📊 Image Categories:")
    for category, count in sorted(image_breakdown.items()):
        percentage = (count / stats['articles_with_images']) * 100 if stats['articles_with_images'] > 0 else 0
        print(f"  {category}: {count} ({percentage:.1f}%)")
    
    # Recommendations
    print(f"\n💡 Recommendations:")
    
    if stats['external_images'] > 0:
        print(f"  🔄 Run migration to upload {stats['external_images']} external images to R2")
        
    needs_optimization = stats['r2_images'] - stats['optimized_images']
    if needs_optimization > 0:
        print(f"  🎨 Run optimization on {needs_optimization} R2 images that lack optimization")
        
    if stats['non_webp_r2_images'] > 0:
        print(f"  📐 Convert {stats['non_webp_r2_images']} non-WebP R2 images to WebP format")
        
    if stats['missing_optimization_flag'] > 0:
        print(f"  🏷️  {stats['missing_optimization_flag']} images missing optimization metadata")
    
    # Commands to run
    print(f"\n🛠️  Suggested Commands:")
    
    if stats['external_images'] > 0 or needs_optimization > 0:
        print("  # Process images that need migration or optimization:")
        print("  python migrate_images_to_r2.py")
        print()
        
    if stats['r2_images'] > stats['recently_optimized']:
        print("  # Force re-optimization of ALL R2 images:")
        print("  python migrate_images_to_r2.py --force-reoptimize")
        print()
    
    # Current optimization settings
    print(f"📝 Current Optimization Settings:")
    print(f"  - Enabled: {IMAGE_OPTIMIZATION['enabled']}")
    print(f"  - Convert to WebP: {IMAGE_OPTIMIZATION['convert_to_webp']}")
    print(f"  - Max dimensions: {IMAGE_OPTIMIZATION['max_width']}x{IMAGE_OPTIMIZATION['max_height']}")
    print(f"  - WebP quality: {IMAGE_OPTIMIZATION['webp_quality']}%")
    print(f"  - Max file size: {IMAGE_OPTIMIZATION['max_file_size'] / (1024*1024):.1f}MB")
    
    return True

def main():
    """Main function."""
    try:
        return analyze_images()
    except KeyboardInterrupt:
        print("\n⚠️ Analysis interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 