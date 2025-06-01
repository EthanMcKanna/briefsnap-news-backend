"""
Cloudflare R2 storage utility for uploading images with optimization.
"""

import os
import hashlib
import requests
import boto3
import io
from urllib.parse import urlparse
from datetime import datetime
from PIL import Image, ImageOps

from newsaggregator.config.settings import (
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_ENDPOINT_URL,
    R2_BUCKET_NAME,
    R2_CUSTOM_DOMAIN,
    IMAGE_OPTIMIZATION
)

# Try to register HEIF support for modern formats (optional)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # HEIF support is optional


class R2Storage:
    """Class for handling Cloudflare R2 storage operations."""
    
    def __init__(self):
        """Initialize R2 client."""
        # Check if all required credentials are available
        if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
            self.client = None
            self.enabled = False
            print("[WARNING] R2 credentials not configured. Image uploading to R2 is disabled.")
        else:
            try:
                self.client = boto3.client(
                    's3',
                    endpoint_url=R2_ENDPOINT_URL,
                    aws_access_key_id=R2_ACCESS_KEY_ID,
                    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                    region_name='auto'  # R2 uses 'auto' for region
                )
                self.enabled = True
            except Exception as e:
                print(f"[ERROR] Failed to initialize R2 client: {e}")
                self.client = None
                self.enabled = False
    
    def generate_filename(self, original_url, title=None, output_extension=None):
        """Generate a unique filename for the image.
        
        Args:
            original_url: Original image URL
            title: Optional article title for better naming
            output_extension: Extension for optimized image (overrides original)
            
        Returns:
            Generated filename with extension
        """
        # Use provided extension or determine from URL
        if output_extension:
            ext = output_extension
        else:
            # Parse the original URL to get file extension
            parsed_url = urlparse(original_url)
            path = parsed_url.path
            ext = os.path.splitext(path)[1].lower()
            
            # If no extension found, default based on optimization settings
            if not ext or ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                ext = '.webp' if IMAGE_OPTIMIZATION['convert_to_webp'] else '.jpg'
        
        # Create a hash of the URL and current timestamp for uniqueness
        url_hash = hashlib.md5(original_url.encode()).hexdigest()[:12]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Create filename
        if title:
            # Clean title for filename (remove special characters)
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            clean_title = clean_title.replace(' ', '_')[:50]  # Limit length
            filename = f"{timestamp}_{clean_title}_{url_hash}{ext}"
        else:
            filename = f"{timestamp}_{url_hash}{ext}"
        
        return filename
    
    def download_image(self, image_url, timeout=30):
        """Download image from URL.
        
        Args:
            image_url: URL of the image to download
            timeout: Request timeout in seconds
            
        Returns:
            Tuple of (image_data, content_type) or (None, None) if failed
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(image_url, headers=headers, timeout=timeout, stream=True)
            response.raise_for_status()
            
            # Check if it's actually an image
            content_type = response.headers.get('content-type', '').lower()
            if not content_type.startswith('image/'):
                print(f"[WARNING] URL does not return an image: {image_url} (content-type: {content_type})")
                return None, None
            
            # Read the image data
            image_data = response.content
            
            # Validate image size (minimum 1KB, maximum 10MB before optimization)
            if len(image_data) < 1024:
                print(f"[WARNING] Image too small: {image_url} ({len(image_data)} bytes)")
                return None, None
            
            if len(image_data) > 10 * 1024 * 1024:  # 10MB
                print(f"[WARNING] Image too large: {image_url} ({len(image_data)} bytes)")
                return None, None
            
            return image_data, content_type
            
        except Exception as e:
            print(f"[ERROR] Failed to download image from {image_url}: {e}")
            return None, None
    
    def optimize_image(self, image_data, content_type, original_filename=None):
        """Optimize image by resizing, converting format, and compressing.
        
        Args:
            image_data: Raw image bytes
            content_type: Original content type
            original_filename: Original filename (for extension determination)
            
        Returns:
            Tuple of (optimized_data, new_content_type, new_extension) or (None, None, None) if failed
        """
        if not IMAGE_OPTIMIZATION['enabled']:
            # Return original if optimization is disabled
            return image_data, content_type, self._get_extension_from_content_type(content_type)
        
        try:
            # Load image with PIL
            img = Image.open(io.BytesIO(image_data))
            
            # Auto-orient image based on EXIF data
            img = ImageOps.exif_transpose(img)
            
            original_size = img.size
            original_format = img.format
            
            print(f"[INFO] Original image: {original_size[0]}x{original_size[1]} {original_format} ({len(image_data)} bytes)")
            
            # Check if image needs resizing
            max_width = IMAGE_OPTIMIZATION['max_width']
            max_height = IMAGE_OPTIMIZATION['max_height']
            
            if img.width > max_width or img.height > max_height:
                # Calculate new size maintaining aspect ratio
                ratio = min(max_width / img.width, max_height / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                print(f"[INFO] Resized to: {new_size[0]}x{new_size[1]}")
            
            # Handle transparency
            has_transparency = (
                (img.mode in ('RGBA', 'LA', 'P') and 'transparency' in img.info) or
                (img.mode == 'RGBA' and img.getextrema()[3][0] < 255)
            )
            
            # Determine output format and quality
            if IMAGE_OPTIMIZATION['convert_to_webp']:
                output_format = 'WebP'
                output_content_type = 'image/webp'
                output_extension = '.webp'
                quality = IMAGE_OPTIMIZATION['webp_quality']
                
                # WebP supports transparency
                if has_transparency and IMAGE_OPTIMIZATION['preserve_transparency']:
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                else:
                    if img.mode in ('RGBA', 'LA'):
                        # Create white background for images without transparency
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'LA':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    elif img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')
                        
            else:
                # Keep original format or optimize
                if has_transparency and IMAGE_OPTIMIZATION['preserve_transparency']:
                    output_format = 'PNG'
                    output_content_type = 'image/png'
                    output_extension = '.png'
                    quality = None  # PNG doesn't use quality parameter
                else:
                    output_format = 'JPEG'
                    output_content_type = 'image/jpeg'
                    output_extension = '.jpg'
                    quality = IMAGE_OPTIMIZATION['jpeg_quality']
                    
                    # Convert to RGB for JPEG
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode in ('RGBA', 'LA'):
                            background.paste(img, mask=img.split()[-1])
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
            
            # Save optimized image
            output_buffer = io.BytesIO()
            save_kwargs = {'format': output_format}
            
            if quality is not None:
                save_kwargs['quality'] = quality
                save_kwargs['optimize'] = True
            
            if output_format == 'WebP':
                save_kwargs['method'] = 6  # Best compression
                
            elif output_format == 'PNG':
                save_kwargs['optimize'] = True
                
            img.save(output_buffer, **save_kwargs)
            optimized_data = output_buffer.getvalue()
            
            # Check if optimization was successful
            if len(optimized_data) > IMAGE_OPTIMIZATION['max_file_size']:
                print(f"[WARNING] Optimized image still too large: {len(optimized_data)} bytes")
                # Try with lower quality
                if output_format == 'WebP' and quality > 60:
                    return self._try_lower_quality(img, output_format, quality - 15)
                elif output_format == 'JPEG' and quality > 70:
                    return self._try_lower_quality(img, output_format, quality - 15)
                else:
                    return None, None, None
            
            if len(optimized_data) < IMAGE_OPTIMIZATION['min_file_size']:
                print(f"[WARNING] Optimized image too small: {len(optimized_data)} bytes")
                return None, None, None
            
            compression_ratio = (1 - len(optimized_data) / len(image_data)) * 100
            print(f"[INFO] Optimized: {len(optimized_data)} bytes ({compression_ratio:.1f}% reduction)")
            
            return optimized_data, output_content_type, output_extension
            
        except Exception as e:
            print(f"[ERROR] Image optimization failed: {e}")
            # Return original image as fallback
            return image_data, content_type, self._get_extension_from_content_type(content_type)
    
    def _try_lower_quality(self, img, output_format, quality):
        """Try to save image with lower quality."""
        try:
            output_buffer = io.BytesIO()
            save_kwargs = {
                'format': output_format,
                'quality': quality,
                'optimize': True
            }
            
            if output_format == 'WebP':
                save_kwargs['method'] = 6
                
            img.save(output_buffer, **save_kwargs)
            optimized_data = output_buffer.getvalue()
            
            output_content_type = 'image/webp' if output_format == 'WebP' else 'image/jpeg'
            output_extension = '.webp' if output_format == 'WebP' else '.jpg'
            
            if len(optimized_data) <= IMAGE_OPTIMIZATION['max_file_size']:
                print(f"[INFO] Reduced quality to {quality}: {len(optimized_data)} bytes")
                return optimized_data, output_content_type, output_extension
            else:
                return None, None, None
                
        except Exception as e:
            print(f"[ERROR] Lower quality optimization failed: {e}")
            return None, None, None
    
    def _get_extension_from_content_type(self, content_type):
        """Get file extension from content type."""
        content_type = content_type.lower()
        if 'jpeg' in content_type or 'jpg' in content_type:
            return '.jpg'
        elif 'png' in content_type:
            return '.png'
        elif 'gif' in content_type:
            return '.gif'
        elif 'webp' in content_type:
            return '.webp'
        else:
            return '.jpg'  # Default
    
    def get_optimal_cache_headers(self, content_type, file_size):
        """Get optimal cache headers for Cloudflare edge caching.
        
        Args:
            content_type: MIME type of the content
            file_size: Size of the file in bytes
            
        Returns:
            Dictionary of cache headers for object upload
        """
        # Base cache headers optimized for Cloudflare
        headers = {
            # Cache for 1 year for images (they're immutable with unique filenames)
            'CacheControl': 'public, max-age=31536000, immutable',
            
            # Optimize for delivery
            'ContentDisposition': 'inline',
            
            # Add metadata for tracking and optimization
            'Metadata': {
                'cached-at': datetime.now().isoformat(),
                'original-content-type': content_type,
                'file-size': str(file_size)
            }
        }
        
        # Optimize based on content type
        if content_type.startswith('image/'):
            if 'jpeg' in content_type or 'jpg' in content_type:
                # JPEG images - optimize for compression
                headers['Metadata']['image-format'] = 'jpeg'
                headers['Metadata']['optimization'] = 'lossy-compression'
            elif 'png' in content_type:
                # PNG images - good for graphics with transparency
                headers['Metadata']['image-format'] = 'png'
                headers['Metadata']['optimization'] = 'lossless-compression'
            elif 'webp' in content_type:
                # WebP - modern format with excellent compression
                headers['Metadata']['image-format'] = 'webp'
                headers['Metadata']['optimization'] = 'modern-compression'
                # WebP gets longer cache since it's more efficient
                headers['CacheControl'] = 'public, max-age=63072000, immutable'  # 2 years
            elif 'gif' in content_type:
                # GIF - typically animations
                headers['Metadata']['image-format'] = 'gif'
                headers['Metadata']['optimization'] = 'animation-optimized'
        
        # Optimize based on file size
        if file_size > 1024 * 1024:  # Files larger than 1MB
            # Longer cache for larger files since they're more expensive to transfer
            headers['CacheControl'] = 'public, max-age=63072000, immutable'  # 2 years
            headers['Metadata']['size-category'] = 'large'
        elif file_size < 50 * 1024:  # Files smaller than 50KB
            headers['Metadata']['size-category'] = 'small'
        else:
            headers['Metadata']['size-category'] = 'medium'
        
        return headers

    def upload_to_r2(self, image_data, filename, content_type='image/jpeg'):
        """Upload image data to Cloudflare R2 with optimized caching.
        
        Args:
            image_data: Binary image data
            filename: Filename to use in R2
            content_type: MIME type of the image
            
        Returns:
            Public URL of the uploaded image or None if failed
        """
        try:
            # Get optimal cache headers for this content
            cache_headers = self.get_optimal_cache_headers(content_type, len(image_data))
            
            # Upload to R2 with optimized headers (CORS headers are set at bucket level)
            put_params = {
                'Bucket': R2_BUCKET_NAME,
                'Key': filename,
                'Body': image_data,
                'ContentType': content_type,
                'CacheControl': cache_headers['CacheControl'],
                'ContentDisposition': cache_headers['ContentDisposition'],
                'Metadata': cache_headers['Metadata']
            }
            
            # Note: CORS headers are configured at bucket level via configure_bucket_for_cloudflare()
            # They cannot be set per-object in S3/R2
            
            print(f"[DEBUG] Uploading {len(image_data)} bytes to R2 as {filename}")
            print(f"[DEBUG] Cache-Control: {cache_headers['CacheControl']}")
            
            self.client.put_object(**put_params)
            
            # Return the public URL using custom domain
            public_url = f"https://{R2_CUSTOM_DOMAIN}/{filename}"
            
            print(f"[INFO] Successfully uploaded image to R2 with optimized caching: {public_url}")
            
            return public_url
            
        except Exception as e:
            print(f"[ERROR] Failed to upload image to R2: {e}")
            print(f"[DEBUG] Upload parameters: Bucket={R2_BUCKET_NAME}, Key={filename}, ContentType={content_type}")
            print(f"[DEBUG] File size: {len(image_data)} bytes")
            return None
    
    def upload_image_from_url(self, image_url, title=None):
        """Download image from URL, optimize it, and upload to R2.
        
        Args:
            image_url: URL of the image to download and upload
            title: Optional article title for better naming
            
        Returns:
            Public R2 URL of the uploaded image or None if failed
        """
        if not image_url:
            return None
        
        if not self.enabled:
            print("[WARNING] R2 storage is not enabled, returning original URL")
            return None
        
        print(f"[INFO] Processing image: {image_url}")
        
        # Download the image
        image_data, content_type = self.download_image(image_url)
        if not image_data:
            return None
        
        # Optimize the image
        print(f"[INFO] Optimizing image...")
        optimized_data, optimized_content_type, output_extension = self.optimize_image(
            image_data, content_type
        )
        
        if not optimized_data:
            print("[WARNING] Image optimization failed, using original")
            optimized_data = image_data
            optimized_content_type = content_type
            output_extension = self._get_extension_from_content_type(content_type)
        
        # Generate filename with correct extension
        filename = self.generate_filename(image_url, title, output_extension)
        
        # Upload to R2
        r2_url = self.upload_to_r2(optimized_data, filename, optimized_content_type)
        
        return r2_url
    
    def configure_bucket_for_cloudflare(self):
        """Configure bucket settings optimized for Cloudflare CDN.
        
        This method sets up bucket-level configurations that work well with Cloudflare.
        Note: Some settings may require additional permissions.
        
        Returns:
            True if configuration was successful, False otherwise
        """
        if not self.enabled:
            print("[WARNING] R2 is not enabled, cannot configure bucket")
            return False
            
        try:
            print("[INFO] Configuring bucket for optimal Cloudflare integration...")
            
            # Set CORS configuration for web access
            cors_configuration = {
                'CORSRules': [
                    {
                        'AllowedHeaders': ['*'],
                        'AllowedMethods': ['GET', 'HEAD'],
                        'AllowedOrigins': ['*'],
                        'ExposeHeaders': ['ETag', 'Content-Length', 'Content-Type'],
                        'MaxAgeSeconds': 86400  # 24 hours
                    }
                ]
            }
            
            try:
                self.client.put_bucket_cors(
                    Bucket=R2_BUCKET_NAME,
                    CORSConfiguration=cors_configuration
                )
                print("[INFO] ✅ CORS configuration applied successfully")
            except Exception as e:
                print(f"[WARNING] Could not set CORS configuration: {e}")
            
            # Try to set lifecycle configuration for cleanup (optional)
            try:
                # This is optional - removes incomplete multipart uploads after 7 days
                lifecycle_configuration = {
                    'Rules': [
                        {
                            'ID': 'cleanup-incomplete-uploads',
                            'Status': 'Enabled',
                            'AbortIncompleteMultipartUpload': {
                                'DaysAfterInitiation': 7
                            }
                        }
                    ]
                }
                
                self.client.put_bucket_lifecycle_configuration(
                    Bucket=R2_BUCKET_NAME,
                    LifecycleConfiguration=lifecycle_configuration
                )
                print("[INFO] ✅ Lifecycle configuration applied successfully")
            except Exception as e:
                print(f"[INFO] Lifecycle configuration not applied (this is optional): {e}")
            
            print("[INFO] ✅ Bucket configuration completed")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to configure bucket: {e}")
            return False

    def check_r2_connection(self):
        """Check if R2 connection is working and test caching setup.
        
        Returns:
            True if connection is working, False otherwise
        """
        if not self.enabled:
            print("[WARNING] R2 is not enabled")
            return False
            
        try:
            # Test basic connection
            print("[INFO] Testing R2 connection...")
            response = self.client.list_objects_v2(Bucket=R2_BUCKET_NAME, MaxKeys=1)
            print("[INFO] ✅ R2 connection successful")
            
            # Test if custom domain is properly configured
            print(f"[INFO] Testing custom domain: {R2_CUSTOM_DOMAIN}")
            try:
                import requests
                test_url = f"https://{R2_CUSTOM_DOMAIN}/"
                response = requests.head(test_url, timeout=10)
                if response.status_code in [200, 403, 404]:  # 403/404 are OK for empty bucket
                    print("[INFO] ✅ Custom domain is accessible")
                else:
                    print(f"[WARNING] Custom domain returned status {response.status_code}")
            except Exception as e:
                print(f"[WARNING] Could not test custom domain: {e}")
            
            # Check bucket CORS configuration
            try:
                cors_response = self.client.get_bucket_cors(Bucket=R2_BUCKET_NAME)
                print("[INFO] ✅ CORS configuration found")
            except Exception:
                print("[INFO] ⚠️  No CORS configuration found - consider running configure_bucket_for_cloudflare()")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] R2 connection failed: {e}")
            return False


# Global R2 storage instance
r2_storage = R2Storage() 