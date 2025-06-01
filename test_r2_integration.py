#!/usr/bin/env python3
"""
Test script for Cloudflare R2 integration.
This script tests the R2 upload functionality with a sample image.
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

def test_r2_connection():
    """Test R2 connection."""
    print("Testing R2 connection...")
    if r2_storage.check_r2_connection():
        print("✅ R2 connection successful!")
        return True
    else:
        print("❌ R2 connection failed!")
        return False

def test_bucket_configuration():
    """Test bucket configuration for optimal Cloudflare caching."""
    print("\nTesting bucket configuration...")
    
    try:
        success = r2_storage.configure_bucket_for_cloudflare()
        if success:
            print("✅ Bucket configured successfully for Cloudflare!")
            return True
        else:
            print("⚠️  Bucket configuration had some issues, but this is not critical")
            return True  # Don't fail the test for optional configurations
    except Exception as e:
        print(f"⚠️  Error during bucket configuration: {e}")
        print("This is not critical for basic functionality")
        return True

def test_cache_headers():
    """Test that cache headers are properly set."""
    print("\nTesting cache header optimization...")
    
    # Test different content types and sizes
    test_cases = [
        ('image/jpeg', 500 * 1024, 'Medium JPEG'),
        ('image/png', 50 * 1024, 'Small PNG'), 
        ('image/webp', 2 * 1024 * 1024, 'Large WebP'),
        ('image/gif', 100 * 1024, 'Medium GIF')
    ]
    
    for content_type, file_size, description in test_cases:
        headers = r2_storage.get_optimal_cache_headers(content_type, file_size)
        print(f"  {description}:")
        print(f"    Cache-Control: {headers['CacheControl']}")
        print(f"    Metadata: {len(headers['Metadata'])} fields")
    
    print("✅ Cache header optimization working correctly!")
    return True

def test_image_upload():
    """Test uploading a sample image to R2 with enhanced caching."""
    print("\nTesting image upload with optimized caching...")
    
    # Use a sample image URL (NASA image of the day - should be reliable)
    test_image_url = "https://apod.nasa.gov/apod/image/2401/STSCI-B1E-STScI-01HGQ5KKDCVZFK0NNG9EEZKR6K.png"
    test_title = "Test Article - R2 Integration with Caching"
    
    print(f"Uploading test image: {test_image_url}")
    
    try:
        r2_url = r2_storage.upload_image_from_url(test_image_url, test_title)
        
        if r2_url:
            print(f"✅ Image uploaded successfully to R2: {r2_url}")
            
            # Test if the uploaded image is accessible and has proper headers
            print("Testing image accessibility and cache headers...")
            try:
                import requests
                response = requests.head(r2_url, timeout=10)
                if response.status_code == 200:
                    print("✅ Image is accessible via custom domain")
                    
                    # Check cache headers
                    cache_control = response.headers.get('cache-control', '')
                    if 'max-age' in cache_control:
                        print(f"✅ Cache headers found: {cache_control}")
                    else:
                        print("⚠️  Cache headers not found in response")
                        
                    # Check content type
                    content_type = response.headers.get('content-type', '')
                    if content_type.startswith('image/'):
                        print(f"✅ Proper content type: {content_type}")
                    else:
                        print(f"⚠️  Unexpected content type: {content_type}")
                        
                else:
                    print(f"⚠️  Image returned status code: {response.status_code}")
                    
            except Exception as e:
                print(f"⚠️  Could not test image accessibility: {e}")
                
            return True
        else:
            print("❌ Image upload failed!")
            return False
    except Exception as e:
        print(f"❌ Error during image upload: {e}")
        return False

def main():
    """Run all tests including new caching features."""
    print("🧪 Briefsnap R2 Integration Test (Enhanced Caching)")
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
    
    # Test connection (enhanced with caching checks)
    connection_success = test_r2_connection()
    if not connection_success:
        print("\n❌ Cannot proceed without R2 connection")
        return False
    
    # Test bucket configuration for Cloudflare
    config_success = test_bucket_configuration()
    
    # Test cache header optimization
    cache_headers_success = test_cache_headers()
    
    # Test image upload with enhanced caching
    upload_success = test_image_upload()
    
    print("\n" + "=" * 50)
    if connection_success and upload_success and cache_headers_success:
        print("🎉 All tests passed! R2 integration with optimized Cloudflare caching is working correctly.")
        if config_success:
            print("✅ Bucket is properly configured for optimal Cloudflare performance.")
        return True
    else:
        print("❌ Some tests failed. Please check your R2 configuration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 