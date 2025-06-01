#!/usr/bin/env python3
"""
Test script for image optimization functionality in R2 storage.
This script tests various image formats and optimization scenarios.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables if .env file exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed, skipping .env file loading")

from newsaggregator.utils.r2_storage import r2_storage
from newsaggregator.config.settings import IMAGE_OPTIMIZATION

def test_image_optimization():
    """Test image optimization with various sample images."""
    print("🖼️ Image Optimization Test")
    print("=" * 30)
    
    # Test images from different sources
    test_images = [
        {
            'url': 'https://via.placeholder.com/1920x1080/0066CC/FFFFFF?text=Large+Test+Image',
            'name': 'Large placeholder (1920x1080)',
            'expected': 'Should be resized and optimized'
        },
        {
            'url': 'https://via.placeholder.com/800x600/FF6600/FFFFFF?text=Medium+Test+Image',
            'name': 'Medium placeholder (800x600)',
            'expected': 'Should be optimized without resizing'
        },
        {
            'url': 'https://via.placeholder.com/300x200/00CC66/FFFFFF?text=Small+Test+Image',
            'name': 'Small placeholder (300x200)',
            'expected': 'Should be optimized without resizing'
        }
    ]
    
    # Display optimization settings
    print(f"📝 Current Optimization Settings:")
    print(f"   - Enabled: {IMAGE_OPTIMIZATION['enabled']}")
    print(f"   - Convert to WebP: {IMAGE_OPTIMIZATION['convert_to_webp']}")
    print(f"   - Max dimensions: {IMAGE_OPTIMIZATION['max_width']}x{IMAGE_OPTIMIZATION['max_height']}")
    print(f"   - WebP quality: {IMAGE_OPTIMIZATION['webp_quality']}%")
    print(f"   - JPEG quality: {IMAGE_OPTIMIZATION['jpeg_quality']}%")
    print()
    
    if not r2_storage.enabled:
        print("❌ R2 storage is not enabled!")
        print("Testing optimization only (without upload)...")
        print()
        
        # Test optimization without uploading
        for i, test_image in enumerate(test_images, 1):
            print(f"[{i}/{len(test_images)}] Testing: {test_image['name']}")
            print(f"URL: {test_image['url']}")
            print(f"Expected: {test_image['expected']}")
            
            try:
                # Download image
                image_data, content_type = r2_storage.download_image(test_image['url'])
                if not image_data:
                    print("❌ Failed to download image")
                    continue
                
                print(f"Downloaded: {len(image_data)} bytes, {content_type}")
                
                # Test optimization
                optimized_data, optimized_content_type, output_extension = r2_storage.optimize_image(
                    image_data, content_type
                )
                
                if optimized_data:
                    compression_ratio = (1 - len(optimized_data) / len(image_data)) * 100
                    print(f"✅ Optimized: {len(optimized_data)} bytes ({compression_ratio:.1f}% reduction)")
                    print(f"   - Format: {content_type} → {optimized_content_type}")
                    print(f"   - Extension: {output_extension}")
                else:
                    print("❌ Optimization failed")
                    
            except Exception as e:
                print(f"❌ Error: {e}")
            
            print("-" * 50)
        
        return True
    
    # Test with R2 upload
    print("✅ R2 storage is enabled - testing full optimization + upload workflow")
    
    # Test R2 connection
    if not r2_storage.check_r2_connection():
        print("❌ R2 connection failed!")
        return False
    
    print()
    
    # Process test images
    for i, test_image in enumerate(test_images, 1):
        print(f"[{i}/{len(test_images)}] Processing: {test_image['name']}")
        print(f"URL: {test_image['url']}")
        print(f"Expected: {test_image['expected']}")
        
        try:
            # Upload with optimization
            r2_url = r2_storage.upload_image_from_url(
                test_image['url'], 
                f"Test Image {i}"
            )
            
            if r2_url:
                print(f"✅ Successfully uploaded: {r2_url}")
            else:
                print("❌ Upload failed")
                
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("-" * 50)
    
    return True

def test_optimization_settings():
    """Test different optimization settings."""
    print("\n🔧 Testing Optimization Settings")
    print("=" * 35)
    
    test_url = 'https://via.placeholder.com/1500x1000/FF0000/FFFFFF?text=Settings+Test'
    
    # Download test image once
    image_data, content_type = r2_storage.download_image(test_url)
    if not image_data:
        print("❌ Failed to download test image")
        return False
    
    print(f"Original: {len(image_data)} bytes, {content_type}")
    print()
    
    # Test different scenarios
    scenarios = [
        {
            'name': 'WebP Conversion (Quality 85)',
            'settings': {'convert_to_webp': True, 'webp_quality': 85}
        },
        {
            'name': 'WebP Conversion (Quality 60)',
            'settings': {'convert_to_webp': True, 'webp_quality': 60}
        },
        {
            'name': 'JPEG Optimization (Quality 90)',
            'settings': {'convert_to_webp': False, 'jpeg_quality': 90}
        },
        {
            'name': 'JPEG Optimization (Quality 70)',
            'settings': {'convert_to_webp': False, 'jpeg_quality': 70}
        }
    ]
    
    # Save original settings
    original_settings = IMAGE_OPTIMIZATION.copy()
    
    try:
        for scenario in scenarios:
            print(f"Testing: {scenario['name']}")
            
            # Update settings
            IMAGE_OPTIMIZATION.update(scenario['settings'])
            
            # Test optimization
            optimized_data, optimized_content_type, output_extension = r2_storage.optimize_image(
                image_data, content_type
            )
            
            if optimized_data:
                compression_ratio = (1 - len(optimized_data) / len(image_data)) * 100
                print(f"✅ Result: {len(optimized_data)} bytes ({compression_ratio:.1f}% reduction)")
                print(f"   - Format: {optimized_content_type}, Extension: {output_extension}")
            else:
                print("❌ Optimization failed")
            
            print()
            
    finally:
        # Restore original settings
        IMAGE_OPTIMIZATION.clear()
        IMAGE_OPTIMIZATION.update(original_settings)
    
    return True

def main():
    """Main test function."""
    try:
        success = test_image_optimization()
        if success:
            test_optimization_settings()
        
        print("\n🎉 Testing completed!")
        return True
        
    except KeyboardInterrupt:
        print("\n⚠️ Testing interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Testing failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 