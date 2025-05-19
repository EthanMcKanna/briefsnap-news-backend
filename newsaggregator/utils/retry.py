"""Retry utilities for handling transient failures."""

import time
import functools
from newsaggregator.config.settings import GEMINI_BASE_DELAY, GEMINI_MAX_RETRIES, GEMINI_MAX_DELAY

def retry_with_backoff(func):
    """Decorator for exponential backoff retry logic
    
    Args:
        func: Function to retry
        
    Returns:
        Decorated function with retry logic
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
                if retry_count == GEMINI_MAX_RETRIES:
                    print(f"ERROR: Maximum retries ({GEMINI_MAX_RETRIES}) reached for function call")
                    raise e
                
                print(f"WARNING: Function call failed (attempt {retry_count}/{GEMINI_MAX_RETRIES})")
                print(f"ERROR details: {str(e)}")
                print(f"Retrying in {delay} seconds...")
                
                time.sleep(delay)
                delay = min(delay * 2, GEMINI_MAX_DELAY)
    
    return wrapper 