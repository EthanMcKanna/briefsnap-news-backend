"""Retry utilities for handling transient failures and rate limits."""

import time
import functools
import re
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from newsaggregator.config.settings import (
    GEMINI_BASE_DELAY, GEMINI_MAX_RETRIES, GEMINI_MAX_DELAY, 
    GEMINI_RATE_LIMIT_DELAY, GEMINI_API_KEY, GEMINI_API_KEY_2
)

class GeminiAPIManager:
    """Manages Gemini API keys and handles switching between them for rate limits."""
    
    def __init__(self):
        self.api_keys = [key for key in [GEMINI_API_KEY, GEMINI_API_KEY_2] if key]
        self.current_key_index = 0
        self.key_last_used = {}  # Track when each key was last used
        self.key_rate_limited_until = {}  # Track rate limit cooldown for each key
        
        if not self.api_keys:
            raise ValueError("At least one Gemini API key must be configured")
        
        # Initialize with the first API key
        self.configure_current_key()
    
    def configure_current_key(self):
        """Configure Gemini with the current API key."""
        current_key = self.api_keys[self.current_key_index]
        genai.configure(api_key=current_key)
        print(f"[INFO] Configured Gemini with API key #{self.current_key_index + 1}")
    
    def get_next_available_key(self):
        """Switch to the next available API key that's not rate limited."""
        current_time = time.time()
        
        # Check if we have multiple keys to switch between
        if len(self.api_keys) <= 1:
            return False
        
        # Try each key to find one that's not rate limited
        for i, key in enumerate(self.api_keys):
            if i == self.current_key_index:
                continue  # Skip current key
                
            # Check if this key is still rate limited
            if key in self.key_rate_limited_until:
                if current_time < self.key_rate_limited_until[key]:
                    print(f"[INFO] API key #{i + 1} still rate limited, skipping")
                    continue
                else:
                    # Rate limit has expired
                    del self.key_rate_limited_until[key]
            
            # Switch to this key
            self.current_key_index = i
            self.configure_current_key()
            return True
        
        return False
    
    def mark_key_rate_limited(self, retry_delay=None):
        """Mark the current key as rate limited."""
        current_key = self.api_keys[self.current_key_index]
        rate_limit_duration = retry_delay if retry_delay else GEMINI_RATE_LIMIT_DELAY
        self.key_rate_limited_until[current_key] = time.time() + rate_limit_duration
        print(f"[INFO] API key #{self.current_key_index + 1} marked as rate limited for {rate_limit_duration} seconds")

# Global API manager instance
api_manager = GeminiAPIManager()

def parse_retry_delay_from_error(error_message):
    """Extract retry delay from Gemini API error message.
    
    Args:
        error_message: The error message string
        
    Returns:
        Retry delay in seconds, or None if not found
    """
    # Look for retry_delay in the error message
    retry_delay_match = re.search(r'retry_delay[^}]*seconds: (\d+)', str(error_message))
    if retry_delay_match:
        return int(retry_delay_match.group(1))
    
    # Look for other patterns that might indicate delay
    # Sometimes the API suggests waiting time in different formats
    wait_match = re.search(r'wait (\d+) seconds?', str(error_message), re.IGNORECASE)
    if wait_match:
        return int(wait_match.group(1))
    
    return None

def is_rate_limit_error(error):
    """Check if the error is a rate limit error.
    
    Args:
        error: The exception object
        
    Returns:
        bool: True if it's a rate limit error
    """
    error_str = str(error)
    
    # Check for 429 status code or quota exceeded messages
    rate_limit_indicators = [
        '429',
        'quota exceeded',
        'rate limit',
        'too many requests',
        'GenerateRequestsPerMinutePerProjectPerModel',
        'quota_metric'
    ]
    
    return any(indicator in error_str.lower() for indicator in rate_limit_indicators)

def is_retryable_error(error):
    """Check if the error is retryable.
    
    Args:
        error: The exception object
        
    Returns:
        bool: True if the error should be retried
    """
    if isinstance(error, (ResourceExhausted, ServiceUnavailable)):
        return True
    
    error_str = str(error)
    
    # Retryable error patterns
    retryable_indicators = [
        '429',  # Rate limit
        '500',  # Internal server error
        '502',  # Bad gateway
        '503',  # Service unavailable
        '504',  # Gateway timeout
        'timeout',
        'connection',
        'quota exceeded',
        'rate limit',
        'temporarily unavailable'
    ]
    
    return any(indicator in error_str.lower() for indicator in retryable_indicators)

def smart_retry_with_backoff(func):
    """Enhanced decorator for smart retry logic with rate limit handling and API key switching.
    
    Args:
        func: Function to retry
        
    Returns:
        Decorated function with smart retry logic
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        retry_count = 0
        delay = GEMINI_BASE_DELAY
        
        while retry_count < GEMINI_MAX_RETRIES:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                retry_count += 1
                error_str = str(e)
                
                print(f"[WARNING] API call failed (attempt {retry_count}/{GEMINI_MAX_RETRIES})")
                print(f"[ERROR] {error_str}")
                
                # Check if this is the last retry attempt
                if retry_count == GEMINI_MAX_RETRIES:
                    print(f"[ERROR] Maximum retries ({GEMINI_MAX_RETRIES}) reached")
                    raise e
                
                # Check if it's a retryable error
                if not is_retryable_error(e):
                    print(f"[ERROR] Non-retryable error encountered")
                    raise e
                
                # Handle rate limit errors specially
                if is_rate_limit_error(e):
                    print(f"[INFO] Rate limit detected")
                    
                    # Extract retry delay from error message
                    suggested_delay = parse_retry_delay_from_error(error_str)
                    
                    # Mark current key as rate limited
                    api_manager.mark_key_rate_limited(suggested_delay)
                    
                    # Try to switch to another API key
                    if api_manager.get_next_available_key():
                        print(f"[INFO] Switched to backup API key, retrying immediately")
                        # Reset delay for new key
                        delay = GEMINI_BASE_DELAY
                        continue
                    else:
                        # No available keys, use suggested delay or default
                        if suggested_delay:
                            delay = suggested_delay
                            print(f"[INFO] Using API-suggested delay of {delay} seconds")
                        else:
                            delay = GEMINI_RATE_LIMIT_DELAY
                            print(f"[INFO] Using default rate limit delay of {delay} seconds")
                else:
                    # Regular exponential backoff for other errors
                    print(f"[INFO] Retrying with exponential backoff: {delay} seconds")
                
                # Sleep before retry
                time.sleep(delay)
                
                # Increase delay for next attempt (but not for rate limit switches)
                if not (is_rate_limit_error(e) and api_manager.get_next_available_key()):
                    delay = min(delay * 2, GEMINI_MAX_DELAY)
    
    return wrapper

# Keep the old decorator name for backward compatibility
retry_with_backoff = smart_retry_with_backoff 